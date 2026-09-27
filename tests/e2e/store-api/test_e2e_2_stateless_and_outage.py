"""E2E-2: carts survive an API restart, a broker outage never fails a request, the seed is idempotent."""
import time
import uuid

import httpx
import psycopg
import pytest

from e2e_support import (ApiServer, local_env, project_prefix, read_messages, run, seed_store, topic_end_offsets,
                         wait_container_healthy)
from telemetry import derive_event_id


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    env = local_env()
    seed_store(env)
    server = ApiServer(env, tmp_path_factory.mktemp("api") / "api.log").start()
    yield env, server
    server.stop()


def headers(run_id, key):
    return {"X-Session-Id": f"s-{run_id}", "X-User-Id": f"anon-{run_id}", "Idempotency-Key": f"{run_id}-{key}"}


def test_cart_survives_an_api_restart(api):
    _, server = api
    run_id = uuid.uuid4().hex[:8]
    added = httpx.post(f"{server.url}/cart/items", json={"product_id": "p-0001", "quantity": 3},
                       headers=headers(run_id, "add"), timeout=10)
    assert added.status_code == 201
    server.stop()
    server.start()
    cart = httpx.get(f"{server.url}/cart", headers=headers(run_id, "view"), timeout=10).json()
    assert [(i["product_id"], i["quantity"]) for i in cart["items"]] == [("p-0001", 3)]


def test_broker_outage_never_fails_a_request_and_loses_no_event(api):
    env, server = api
    bootstrap, topic = env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"]
    kafka = f"{project_prefix()}kafka"
    start = topic_end_offsets(bootstrap, topic)
    run_id = uuid.uuid4().hex[:8]

    run(["docker", "stop", kafka], check=True)
    try:
        began = time.monotonic()
        during = httpx.post(f"{server.url}/cart/items", json={"product_id": "p-0002", "quantity": 1},
                            headers=headers(run_id, "during-outage"), timeout=10)
        assert during.status_code == 201, during.text
        assert time.monotonic() - began < 3, "the request waited on the broker"
    finally:
        run(["docker", "start", kafka], check=True)
        wait_container_healthy(kafka)

    after = httpx.post(f"{server.url}/cart/items", json={"product_id": "p-0003", "quantity": 1},
                       headers=headers(run_id, "after-outage"), timeout=10)
    assert after.status_code == 201, after.text

    wanted = [derive_event_id(f"{run_id}-{key}", "add_to_cart") for key in ("during-outage", "after-outage")]
    received = read_messages(bootstrap, topic, start, wanted, timeout=120)
    assert {m["event_id"] for m in received} == {str(w) for w in wanted}, "an event was lost"
    assert "Traceback" not in server.log()


def test_seed_is_idempotent(api):
    env, _ = api
    count = "SELECT count(*), count(DISTINCT sku) FROM products"
    with psycopg.connect(env["STORE_DB_DSN"]) as conn:
        before = conn.execute(count).fetchone()
    seed_store(env)
    with psycopg.connect(env["STORE_DB_DSN"]) as conn:
        after = conn.execute(count).fetchone()
    assert before == after == (200, 200)
