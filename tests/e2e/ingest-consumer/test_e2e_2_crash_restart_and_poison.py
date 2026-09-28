"""E2E-2: a hard kill loses nothing, poison messages go to the DLQ, a graceful stop leaves nothing uncommitted."""
import base64
import json
import time
import uuid
from datetime import datetime, timezone

from confluent_kafka import Consumer, TopicPartition

from e2e_support import (ConsumerProcess, journey_1_event, local_env, produce_raw, raw_rows, start_group_at_end,
                         topic_end_offsets, wait_for)
from telemetry import get_producer, serialize_event


def test_hard_kill_mid_ingest_loses_nothing(tmp_path):
    env = local_env()
    run_id, now = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    events = [journey_1_event(run_id, n % 40, n, now) for n in range(2000)]
    ids = [e.event_id for e in events]
    group = start_group_at_end(env, f"e2e-{run_id}")  # skip earlier runs' history
    producer = get_producer(env)
    for event in events:
        producer.send_event(event)
    assert producer.flush(30) == 0
    producer.close()

    settings = {"INGEST_GROUP_ID": group, "INGEST_BATCH_SIZE": 20, "INGEST_FLUSH_SECONDS": 1}
    first = ConsumerProcess(env, tmp_path / "first.log", **settings).start()
    at_kill = wait_for(lambda: len(raw_rows(env, ids, "event_id")), 90, interval=0.05, message="first rows")
    first.kill()  # no flush, no commit
    at_kill = len(raw_rows(env, ids, "event_id"))
    assert at_kill < len(ids), "the consumer finished before it was killed; the test proves nothing"

    second = ConsumerProcess(env, tmp_path / "second.log", **settings).start()
    try:
        wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 90, message="all 2000 rows")
    finally:
        assert second.stop() == 0
    rows = raw_rows(env, ids, "event_id")
    assert len(rows) == len({r["event_id"] for r in rows}) == len(ids)


def read_dlq(env, start_offsets, wanted, timeout=60):
    """DLQ envelopes whose (source_partition, source_offset) is in wanted."""
    consumer = Consumer({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "group.id": "e2e-dlq-reader",
                         "enable.auto.commit": False})
    found = {}
    try:
        consumer.assign([TopicPartition(env["EVENTS_DLQ_TOPIC"], p, o) for p, o in start_offsets.items()])
        deadline = time.monotonic() + timeout
        while len(found) < len(wanted) and time.monotonic() < deadline:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            envelope = json.loads(msg.value())
            source = (envelope["source_partition"], envelope["source_offset"])
            if envelope["source_topic"] == env["EVENTS_TOPIC"] and source in wanted:
                found[source] = envelope
    finally:
        consumer.close()
    return found


def committed_offsets(env, group_id):
    topic = env["EVENTS_TOPIC"]
    consumer = Consumer({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "group.id": group_id})
    try:
        partitions = [TopicPartition(topic, p) for p in topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], topic)]
        return {tp.partition: tp.offset for tp in consumer.committed(partitions, timeout=15)}
    finally:
        consumer.close()


def test_poison_messages_go_to_the_dlq_and_a_graceful_stop_commits_everything(tmp_path):
    env = local_env()
    bootstrap, topic = env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"]
    run_id, now = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    group = start_group_at_end(env, f"e2e-{run_id}")  # skip earlier runs' history
    consumer = ConsumerProcess(env, tmp_path / "consumer.log", INGEST_GROUP_ID=group, INGEST_FLUSH_SECONDS=1).start()
    try:
        good = [journey_1_event(run_id, 0, 0, now), journey_1_event(run_id, 0, 1, now)]
        not_json = b"\xff\xfe this is not JSON"
        breaks_schema = json.loads(serialize_event(journey_1_event(run_id, 0, 2, now)))
        breaks_schema["session_id"] = ""
        breaks_schema = json.dumps(breaks_schema).encode()
        key = good[0].session_id.encode()

        dlq_start = topic_end_offsets(bootstrap, env["EVENTS_DLQ_TOPIC"])
        positions = produce_raw(bootstrap, topic, [(key, serialize_event(good[0])), (key, not_json),
                                                   (key, breaks_schema), (key, serialize_event(good[1]))])

        wait_for(lambda: len(raw_rows(env, [e.event_id for e in good], "event_id")) == 2, 60, message="valid rows")
        bad = {positions[1]: not_json, positions[2]: breaks_schema}
        envelopes = read_dlq(env, dlq_start, set(bad))
        assert set(envelopes) == set(bad), "a poison message is missing from the DLQ"
        for source, envelope in envelopes.items():
            assert base64.b64decode(envelope["original_payload_b64"]) == bad[source]
            assert envelope["error"] and envelope["consumer"] == "ingest_consumer" and envelope["failed_at"]
        assert "session_id" in envelopes[positions[2]]["error"]
        assert consumer.running(), "the consumer stopped on a poison message"
    finally:
        exit_code = consumer.stop()

    assert exit_code == 0
    assert committed_offsets(env, group) == topic_end_offsets(bootstrap, topic), "uncommitted messages remain"
