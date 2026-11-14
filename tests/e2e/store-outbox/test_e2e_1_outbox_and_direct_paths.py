"""E2E-1: state changes reach Kafka through the outbox, browsing events take the direct path."""
import json
import uuid

import httpx
import psycopg
import pytest

from e2e_support import ApiServer, local_env, read_messages, seed_store, topic_end_offsets
from telemetry import derive_event_id

# Records every row inserted into the outbox while the flow runs, so the test sees rows the relay deletes.
AUDIT_SETUP = """
CREATE TABLE IF NOT EXISTS e2e_outbox_audit (session_id text, event_type text);
CREATE OR REPLACE FUNCTION e2e_outbox_audit_row() RETURNS trigger AS $$
BEGIN
  INSERT INTO e2e_outbox_audit VALUES (NEW.payload::json->>'session_id', NEW.payload::json->>'event_type');
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER e2e_outbox_audit AFTER INSERT ON outbox_events
  FOR EACH ROW EXECUTE FUNCTION e2e_outbox_audit_row();
"""
AUDIT_TEARDOWN = """
DROP TRIGGER IF EXISTS e2e_outbox_audit ON outbox_events;
DROP FUNCTION IF EXISTS e2e_outbox_audit_row();
DROP TABLE IF EXISTS e2e_outbox_audit;
"""


@pytest.fixture(scope="module")
def journey(tmp_path_factory):
    env = local_env()
    seed_store(env)
    server = ApiServer(env, tmp_path_factory.mktemp("api") / "api.log").start()  # creates outbox_events
    store = psycopg.connect(env["STORE_DB_DSN"], autocommit=True)
    store.execute(AUDIT_SETUP)
    try:
        start = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"])
        run_id = uuid.uuid4().hex[:8]
        session = {"X-Session-Id": f"s-{run_id}", "X-User-Id": f"anon-{run_id}"}
        calls = []  # (event_type, idempotency_key) in request order

        def call(method, path, event_type, key, **kwargs):
            headers = {**session, "Idempotency-Key": f"{run_id}-{key}"}
            response = httpx.request(method, server.url + path, headers=headers, timeout=10, **kwargs)
            assert response.is_success, f"{method} {path}: {response.status_code} {response.text}"
            calls.append((event_type, headers["Idempotency-Key"]))
            return response.json()

        call("GET", "/home", "page_view", "home")
        call("GET", "/products/p-0001", "product_view", "view")
        call("POST", "/cart/items", "add_to_cart", "add-1", json={"product_id": "p-0001", "quantity": 1})
        call("POST", "/cart/items", "add_to_cart", "add-2", json={"product_id": "p-0002", "quantity": 1})
        call("DELETE", "/cart/items/p-0002", "remove_from_cart", "remove")
        call("POST", "/checkout/complete", "purchase", "purchase")

        expected_ids = [str(derive_event_id(key, event_type)) for event_type, key in calls]
        messages = read_messages(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"], start, expected_ids,
                                 timeout=10)
        audited = store.execute("SELECT event_type FROM e2e_outbox_audit WHERE session_id = %s",
                                (session["X-Session-Id"],)).fetchall()
        pending = store.execute("SELECT count(*) FROM outbox_events WHERE event_id = ANY(%s::uuid[])",
                                (expected_ids,)).fetchone()[0]
        yield {"calls": calls, "expected_ids": expected_ids, "messages": messages,
               "audited": [r[0] for r in audited], "pending": pending, "server": server}
    finally:
        store.execute(AUDIT_TEARDOWN)
        store.close()
        server.stop()


def test_kafka_has_every_event_exactly_once_in_session_order(journey):
    assert [m["event_id"] for m in journey["messages"]] == journey["expected_ids"]
    assert len({m["partition"] for m in journey["messages"]}) == 1, "one session must map to one partition"


def test_the_outbox_is_empty_afterwards(journey):
    assert journey["pending"] == 0


def test_only_state_changes_went_through_the_outbox(journey):
    assert journey["audited"] == ["add_to_cart", "add_to_cart", "remove_from_cart", "purchase"]


def test_the_relay_logged_its_committed_cycles(journey):
    cycles = []
    for line in journey["server"].log().splitlines():
        start = line.find('{"event": "outbox_cycle"')
        if start >= 0:
            cycles.append(json.loads(line[start:]))
    committed = [c for c in cycles if c["outcome"] == "committed"]
    assert sum(c["published"] for c in committed) >= 4, cycles
    assert all({"published", "pending_after", "cycle_ms", "outcome"} <= set(c) for c in cycles)
