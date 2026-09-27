"""E2E-1: a thousand journey-1 events reach Kafka, keyed and ordered per session."""
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from e2e_support import journey_1_event, local_env, read_messages, topic_end_offsets
from telemetry import get_producer, validate_payload

SESSIONS, EVENTS_PER_SESSION = 50, 20  # 1,000 events


@pytest.fixture(scope="module")
def published():
    env = local_env()
    bootstrap, topic = env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"]
    start = topic_end_offsets(bootstrap, topic)
    run_id, t0 = uuid.uuid4().hex[:8], datetime.now(timezone.utc)

    sent = defaultdict(list)  # session_id -> event_ids in send order
    producer = get_producer(env)
    for step in range(EVENTS_PER_SESSION):  # interleave the sessions
        for session_no in range(SESSIONS):
            event = journey_1_event(run_id, session_no, step, t0 + timedelta(seconds=step))
            producer.send_event(event)
            sent[event.session_id].append(str(event.event_id))
    pending = producer.flush(30)
    stats = producer.stats()
    producer.close()

    all_ids = [i for ids in sent.values() for i in ids]
    return {"pending": pending, "stats": stats, "sent": sent,
            "messages": read_messages(bootstrap, topic, start, all_ids)}


def test_everything_is_delivered(published):
    total = SESSIONS * EVENTS_PER_SESSION
    stats = published["stats"]
    assert published["pending"] == 0
    assert (stats.sent, stats.delivered, stats.failed, stats.dropped) == (total, total, 0, 0)
    expected = {i for ids in published["sent"].values() for i in ids}
    assert len(published["messages"]) >= total
    assert {m["event_id"] for m in published["messages"]} == expected


def test_messages_carry_key_headers_and_a_valid_payload(published):
    for msg in published["messages"]:
        payload = validate_payload(msg["value"])
        assert msg["key"].decode() == payload["session_id"]
        assert msg["headers"] == {
            "schema_version": payload["schema_version"],
            "event_type": payload["event_type"],
            "content-type": "application/json",
        }


def test_each_session_arrives_in_send_order_on_one_partition(published):
    by_session, partitions = defaultdict(list), defaultdict(set)
    for msg in published["messages"]:
        session_id = json.loads(msg["value"])["session_id"]
        by_session[session_id].append(msg["event_id"])
        partitions[session_id].add(msg["partition"])
    for session_id, expected in published["sent"].items():
        assert by_session[session_id] == expected, f"{session_id} out of order"
        assert len(partitions[session_id]) == 1, f"{session_id} spread over partitions"
