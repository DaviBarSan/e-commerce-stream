"""E2E-2: an API crash during a broker outage loses no state-change event."""
import time
import uuid

import httpx
import psycopg

from e2e_support import (ApiServer, ConsumerProcess, local_env, project_prefix, raw_rows, run, seed_store,
                         start_group_at_end, wait_container_healthy, wait_for)
from telemetry import derive_event_id


def outbox_ids(env, event_ids):
    with psycopg.connect(env["STORE_DB_DSN"]) as conn:
        rows = conn.execute("SELECT event_id::text FROM outbox_events WHERE event_id = ANY(%s::uuid[])",
                            (event_ids,)).fetchall()
    return sorted(r[0] for r in rows)


def test_a_crash_during_a_broker_outage_loses_nothing(tmp_path):
    env = local_env()
    seed_store(env)
    kafka = f"{project_prefix()}kafka"
    run_id = uuid.uuid4().hex[:8]
    headers = {"X-Session-Id": f"s-{run_id}", "X-User-Id": f"anon-{run_id}"}
    expected = {str(derive_event_id(f"{run_id}-add", "add_to_cart")): "add_to_cart",
                str(derive_event_id(f"{run_id}-purchase", "purchase")): "purchase"}
    ids = sorted(expected)

    server = ApiServer(env, tmp_path / "api-1.log").start()
    run(["docker", "stop", kafka], check=True, timeout=120)
    try:
        for path, key, body in [("/cart/items", "add", {"product_id": "p-0003", "quantity": 2}),
                                ("/checkout/complete", "purchase", None)]:
            began = time.monotonic()
            response = httpx.post(server.url + path, json=body, timeout=10,
                                  headers={**headers, "Idempotency-Key": f"{run_id}-{key}"})
            assert response.status_code == 201, response.text
            assert time.monotonic() - began < 3, f"{path} waited on the broker"
        assert outbox_ids(env, ids) == ids, "both events must wait in the outbox"
        server.kill()  # no shutdown: anything in the producer's memory is gone
    finally:
        run(["docker", "start", kafka], check=True, timeout=120)
        wait_container_healthy(kafka)

    group = start_group_at_end(env, f"e2e-outbox-{run_id}")  # nothing reached Kafka during the outage
    server = ApiServer(env, tmp_path / "api-2.log").start()
    consumer = ConsumerProcess(env, tmp_path / "consumer.log", INGEST_GROUP_ID=group, INGEST_FLUSH_SECONDS=1).start()
    try:
        wait_for(lambda: len(raw_rows(env, ids, "event_id")) == 2, 60, message="both events in raw")
        wait_for(lambda: outbox_ids(env, ids) == [], 30, message="the outbox to drain")
    finally:
        consumer.stop()
        server.stop()

    rows = raw_rows(env, ids, "event_id::text AS event_id, event_type")
    assert {r["event_id"]: r["event_type"] for r in rows} == expected and len(rows) == 2
