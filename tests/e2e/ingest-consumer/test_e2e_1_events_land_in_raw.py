"""E2E-1: published events land in raw.clickstream_events with every D11 column, exactly once."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from e2e_support import ConsumerProcess, journey_1_event, local_env, raw_rows, start_group_at_end, wait_for
from telemetry import get_producer

SESSIONS, STEPS = 10, 30  # 300 events


def publish(env, events):
    producer = get_producer(env)
    for event in events:
        producer.send_event(event)
    assert producer.flush(30) == 0
    producer.close()


def duplicates_logged(consumer):
    return sum(r["duplicates"] for r in consumer.log_records("flush"))


@pytest.fixture(scope="module")
def ingested(tmp_path_factory):
    env = local_env()
    run_id, t0 = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    events = [journey_1_event(run_id, s, step, t0 + timedelta(seconds=step))
              for step in range(STEPS) for s in range(SESSIONS)]
    ids = [e.event_id for e in events]
    group = start_group_at_end(env, f"e2e-{run_id}")  # skip earlier runs' history
    publish(env, events)

    consumer = ConsumerProcess(env, tmp_path_factory.mktemp("ingest") / "consumer.log",
                               INGEST_GROUP_ID=group, INGEST_FLUSH_SECONDS=1).start()
    try:
        wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 30, message="300 rows")
        rows = raw_rows(env, ids)

        before = duplicates_logged(consumer)
        publish(env, events)  # the same event_ids again
        wait_for(lambda: duplicates_logged(consumer) >= before + len(ids), 30, message="re-published duplicates")
        count_after_republish = len(raw_rows(env, ids, "event_id"))
        dbt_visible = len(raw_rows(env, ids, "event_id", dsn_key="DBT_WAREHOUSE_DSN"))
        flushes = consumer.log_records("flush")
    finally:
        exit_code = consumer.stop()
    return {"env": env, "events": events, "rows": rows, "count_after_republish": count_after_republish,
            "dbt_visible": dbt_visible, "flushes": flushes, "exit_code": exit_code}


def test_every_event_lands_with_its_d11_columns(ingested):
    by_id = {str(r["event_id"]): r for r in ingested["rows"]}
    assert len(by_id) == len(ingested["events"])
    topic = ingested["env"]["EVENTS_TOPIC"]
    for event in ingested["events"]:
        row = by_id[str(event.event_id)]
        for column in ("schema_version", "event_type", "session_id", "user_id", "anonymous_id",
                       "product_id", "cart_id", "order_id"):
            assert row[column] == getattr(event, column), column
        assert row["event_ts"] == event.event_ts and row["produced_at"] == event.produced_at
        assert row["ingested_at"] >= row["produced_at"]
        assert row["source_topic"] == topic and row["source_partition"] >= 0 and row["source_offset"] >= 0
        assert row["payload"]["event_id"] == str(event.event_id)
        assert row["payload"]["properties"] == event.model_dump(mode="json")["properties"]


def test_republished_events_add_no_rows(ingested):
    assert ingested["count_after_republish"] == len(ingested["events"])


def test_dbt_runner_can_read_the_raw_table(ingested):
    assert ingested["dbt_visible"] == len(ingested["events"])


def test_flushes_are_logged_and_the_consumer_stops_cleanly(ingested):
    assert ingested["flushes"], "no flush log lines"
    for record in ingested["flushes"]:
        assert {"batch_size", "inserted", "duplicates", "dlq_count", "write_ms", "lag"} <= record.keys()
    assert sum(r["inserted"] for r in ingested["flushes"]) >= len(ingested["events"])
    assert ingested["exit_code"] == 0
