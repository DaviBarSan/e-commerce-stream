"""E2E-2: broker outage, validation, factory errors and SDK isolation."""
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest

from e2e_support import (REPO_ROOT, journey_1_event, local_env, project_prefix, read_messages, run,
                         topic_end_offsets)
from telemetry import EventValidationError, NotProvisionedError, TelemetryConfigError, get_producer


def wait_healthy(container, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", container]).stdout.strip()
        if status == "healthy":
            return
        time.sleep(2)
    raise AssertionError(f"{container} not healthy after {timeout}s")


def test_broker_outage_loses_nothing():
    env = local_env()
    bootstrap, topic = env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"]
    kafka = f"{project_prefix()}kafka"
    start = topic_end_offsets(bootstrap, topic)
    producer = get_producer(env)
    run_id, now = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    events = [journey_1_event(run_id, n % 5, n, now) for n in range(50)]

    run(["docker", "stop", kafka], check=True)
    try:
        began = time.monotonic()
        for event in events:
            producer.send_event(event)  # must neither raise nor block while the broker is down
        assert time.monotonic() - began < 5, "send_event blocked during the outage"
        assert producer.flush(2) > 0, "events should be pending while the broker is down"
    finally:
        run(["docker", "start", kafka], check=True)
        wait_healthy(kafka)

    assert producer.flush(90) == 0
    stats = producer.stats()
    producer.close()
    assert (stats.delivered, stats.failed, stats.dropped) == (50, 0, 0)
    received = read_messages(bootstrap, topic, start, [e.event_id for e in events])
    assert {m["event_id"] for m in received} == {str(e.event_id) for e in events}


def test_invalid_event_is_rejected_and_not_published():
    env = local_env()
    bootstrap, topic = env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"]
    before = topic_end_offsets(bootstrap, topic)
    event = journey_1_event(uuid.uuid4().hex[:8], 0, 0, datetime.now(timezone.utc))
    broken = event.model_copy(update={"session_id": ""})  # model_copy skips validation
    producer = get_producer(env)
    with pytest.raises(EventValidationError):
        producer.send_event(broken)
    assert producer.flush(5) == 0 and producer.stats().sent == 0
    producer.close()
    assert topic_end_offsets(bootstrap, topic) == before


@pytest.mark.parametrize("env, error, needle", [
    ({"STREAMING_BACKEND": "pubsub", "EVENTS_TOPIC": "t"}, NotProvisionedError, "telemetry-pubsub"),
    ({"STREAMING_BACKEND": "kinesis", "EVENTS_TOPIC": "t"}, NotProvisionedError, "Phase 9"),
    ({"STREAMING_BACKEND": "rabbitmq", "EVENTS_TOPIC": "t"}, TelemetryConfigError, "STREAMING_BACKEND"),
    ({"EVENTS_TOPIC": "t"}, TelemetryConfigError, "STREAMING_BACKEND"),
    ({"STREAMING_BACKEND": "kafka", "EVENTS_TOPIC": "t"}, TelemetryConfigError, "KAFKA_BOOTSTRAP_SERVERS"),
])
def test_factory_errors_are_clear(env, error, needle):
    with pytest.raises(error, match=needle):
        get_producer(env)


# Prints the cloud SDKs loaded after `import telemetry`, then after creating a Kafka producer.
SDK_PROBE = "\n".join([
    "import sys",
    "import telemetry",
    "SDKS = ('confluent_kafka', 'google.cloud', 'boto3')",
    "loaded = lambda: sorted({s for s in SDKS for m in sys.modules if m == s or m.startswith(s + '.')})",
    "print(loaded())",
    "telemetry.get_producer({'STREAMING_BACKEND': 'kafka', 'KAFKA_BOOTSTRAP_SERVERS': 'localhost:1',"
    " 'EVENTS_TOPIC': 't'})",
    "print(loaded())",
])


def test_cloud_sdks_load_only_when_selected():
    out = subprocess.run([sys.executable, "-c", SDK_PROBE], capture_output=True, text=True, check=True).stdout
    assert out.splitlines() == ["[]", "['confluent_kafka']"], out
    check = run([sys.executable, "scripts/check_sdk_imports.py"], cwd=REPO_ROOT)
    assert check.returncode == 0, check.stdout + check.stderr
