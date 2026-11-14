"""E2E-2: a crashed consumer is restarted and loses nothing; stops are graceful; replicas share partitions;
a code change rebuilds only the consumer."""
import uuid
from datetime import datetime, timezone

from e2e_support import (LOCAL_PLATFORM, LOCAL_RESOURCES, LOCAL_SERVICES, REPO_ROOT, consumer_container,
                         container_state, journey_1_event, local_env, make, project_prefix, raw_rows, run, tf_env,
                         wait_for)
from e2e_support import container_log_records as log_records
from telemetry import get_producer

# Kills the consumer process inside the container (not PID 1, the init process), like a crash.
CRASH = ("import os, signal; [os.kill(int(p), signal.SIGKILL) for p in os.listdir('/proc') if p.isdigit() "
         "and int(p) not in (1, os.getpid()) and b'ingest_consumer' in open(f'/proc/{p}/cmdline', 'rb').read()]")


def publish(env, run_id, count, sessions):
    now = datetime.now(timezone.utc)
    events = [journey_1_event(run_id, n % sessions, n // sessions, now) for n in range(count)]
    producer = get_producer(env)
    for event in events:
        producer.send_event(event)
    assert producer.flush(30) == 0
    producer.close()
    return [e.event_id for e in events]


def group_is_split(env, members, group="clickstream-ingest"):
    """True once the group is stable with `members` consumers, each assigned at least one partition."""
    from confluent_kafka.admin import AdminClient

    admin = AdminClient({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"]})
    description = admin.describe_consumer_groups([group])[group].result(timeout=15)
    assigned = [m for m in description.members if m.assignment.topic_partitions]
    return description.state.name == "STABLE" and len(description.members) == members == len(assigned)


def test_a_crashed_consumer_is_restarted_and_loses_nothing():
    env = local_env()
    container = consumer_container()
    restarts = int(container_state(container)[1])
    ids = publish(env, uuid.uuid4().hex[:8], 2000, 40)
    wait_for(lambda: len(raw_rows(env, ids, "event_id")), 60, interval=0.05, message="the first rows")
    run(["docker", "exec", container, "python", "-c", CRASH], check=True)

    wait_for(lambda: int(container_state(container)[1]) > restarts, 60, interval=1, message="a restart")
    wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 90, interval=1, message="all 2000 in raw")


def test_a_stop_is_graceful_and_a_start_resumes():
    env = local_env()
    container = consumer_container()
    stops = len(log_records(container, "stop"))
    run(["docker", "stop", container], check=True, timeout=60)
    assert len(log_records(container, "stop")) == stops + 1, "no clean shutdown (flush, commit, close)"
    exit_code = run(["docker", "inspect", "-f", "{{.State.ExitCode}}", container], check=True).stdout.strip()
    assert exit_code == "0"

    run(["docker", "start", container], check=True)
    ids = publish(env, uuid.uuid4().hex[:8], 100, 10)
    wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 30, interval=1, message="events after start")


def test_three_replicas_split_the_partitions():
    env = local_env()
    three = tf_env(consumer_replicas=3)
    try:
        run(["make", "up"], env=three, timeout=1200, check=True)
        containers = [consumer_container(n) for n in (1, 2, 3)]
        wait_for(lambda: group_is_split(env, 3), 90, interval=2, message="a stable group of 3 consumers")
        before = {c: len(log_records(c, "flush")) for c in containers}
        ids = publish(env, uuid.uuid4().hex[:8], 600, 60)
        wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 60, interval=1, message="600 in raw")
        busy = [c for c in containers
                if any(r["batch_size"] > 0 for r in log_records(c, "flush")[before[c]:])]
        assert len(busy) == 3, f"only {busy} consumed: the partitions weren't split"
    finally:
        make("up")  # back to one replica
    assert run(["docker", "ps", "-a", "-q", "-f", f"name={consumer_container(2)}"]).stdout.strip() == ""


def test_a_consumer_change_rebuilds_only_the_consumer():
    local_env()
    prefix = project_prefix()
    consumer, api = consumer_container(), f"{prefix}store-api"
    before = {name: run(["docker", "inspect", "-f", "{{.Id}}", name], check=True).stdout for name in (consumer, api)}

    probe = REPO_ROOT / "services" / "ingest_consumer" / "ingest_consumer" / "_e2e_rebuild_probe.py"
    probe.write_text('"""Temporary module from the ingest-deploy E2E-2 flow."""\n')
    try:
        assert LOCAL_PLATFORM.plan_exit_code() == 0
        assert LOCAL_RESOURCES.plan_exit_code() == 0
        assert LOCAL_SERVICES.plan_exit_code() == 2, "a consumer change must rebuild its image"
        make("up")
        after = {name: run(["docker", "inspect", "-f", "{{.Id}}", name], check=True).stdout for name in (consumer, api)}
        assert after[consumer] != before[consumer], "the consumer kept the old image"
        assert after[api] == before[api], "the store API was replaced by a consumer change"
    finally:
        probe.unlink(missing_ok=True)
        make("up")
    assert LOCAL_SERVICES.plan_exit_code() == 0
