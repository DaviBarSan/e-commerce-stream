"""E2E-1: with `make up` alone, events land in the raw table and invalid messages go to the DLQ."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from e2e_support import (consumer_container, container_log_records, container_state, journey_1_event, local_env,
                         produce_raw, raw_rows, run, topic_end_offsets, wait_for)
from telemetry import get_producer


@pytest.fixture(scope="module")
def env():
    return local_env()


def test_the_consumer_container_runs_in_the_ingest_group(env):
    starts = wait_for(lambda: container_log_records(consumer_container(), "start"), 60, interval=2,
                      message="the consumer's start log line")
    assert starts[-1]["group_id"] == "clickstream-ingest"
    assert container_state(consumer_container())[2] == "true"


def test_published_events_reach_raw_with_no_host_consumer(env):
    run_id, t0 = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    events = [journey_1_event(run_id, n % 10, n // 10, t0 + timedelta(seconds=n // 10)) for n in range(300)]
    ids = [e.event_id for e in events]
    producer = get_producer(env)
    for event in events:
        producer.send_event(event)
    assert producer.flush(30) == 0
    producer.close()

    wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 30, interval=1, message="300 events in raw")


def test_an_invalid_message_goes_to_the_dlq_and_the_consumer_keeps_running(env):
    from confluent_kafka import Consumer, TopicPartition

    before = container_state(consumer_container())
    dlq_start = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_DLQ_TOPIC"])
    [(partition, offset)] = produce_raw(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"],
                                        [(b"e2e-ingest-deploy", b"not json")])

    reader = Consumer({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "group.id": "e2e-dlq-reader",
                       "enable.auto.commit": False})
    reader.assign([TopicPartition(env["EVENTS_DLQ_TOPIC"], p, o) for p, o in dlq_start.items()])
    try:
        def dead_letter():
            msg = reader.poll(1.0)
            if msg is None or msg.error():
                return None
            record = json.loads(msg.value())
            return record if (record["source_partition"], record["source_offset"]) == (partition, offset) else None

        record = wait_for(dead_letter, 30, interval=0, message="the dead letter")
    finally:
        reader.close()
    assert record["source_topic"] == env["EVENTS_TOPIC"] and "JSON" in record["error"]
    assert container_state(consumer_container())[:2] == before[:2], "the consumer restarted"
