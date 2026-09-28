"""E2E-1: a purchase journey over HTTP produces an order and the exact journey-1 events."""
import uuid

import httpx
import psycopg
import pytest

from e2e_support import ApiServer, local_env, read_messages, seed_store, topic_end_offsets
from telemetry import derive_event_id, validate_payload


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    env = local_env()
    seed_store(env)
    server = ApiServer(env, tmp_path_factory.mktemp("api") / "api.log").start()
    yield env, server
    server.stop()


@pytest.fixture(scope="module")
def journey(api):
    env, server = api
    start = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"])
    run_id = uuid.uuid4().hex[:8]
    session = {"X-Session-Id": f"s-{run_id}", "X-User-Id": f"anon-{run_id}"}
    calls = []  # (event_type, idempotency_key) in request order

    def call(method, path, event_type, key, **kwargs):
        headers = {**session, "Idempotency-Key": f"{run_id}-{key}"}
        response = httpx.request(method, server.url + path, headers=headers, timeout=10, **kwargs)
        assert response.is_success, f"{method} {path}: {response.status_code} {response.text}"
        assert response.headers["X-Session-Id"] == session["X-Session-Id"]
        calls.append((event_type, headers["Idempotency-Key"]))
        return response.json()

    results = call("GET", "/search", "search", "search", params={"q": "lamp"})["items"]
    call("GET", "/search", "search", "search", params={"q": "lamp"})  # client retry: same key (D13)
    first, second = results[0], results[1]
    call("GET", f"/products/{first['product_id']}", "product_view", "view")
    call("POST", "/cart/items", "add_to_cart", "add-1", json={"product_id": first["product_id"], "quantity": 1})
    call("POST", "/cart/items", "add_to_cart", "add-2", json={"product_id": second["product_id"], "quantity": 2})
    checkout = call("POST", "/checkout/start", "checkout_start", "checkout")
    order = call("POST", "/checkout/complete", "purchase", "purchase")

    expected_ids = [str(derive_event_id(key, event_type)) for event_type, key in calls]
    messages = read_messages(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"], start, expected_ids)
    return {"env": env, "session": session, "calls": calls, "expected_ids": expected_ids,
            "first": first, "second": second, "checkout": checkout, "order": order, "messages": messages}


def test_order_is_stored_and_cart_converted(journey):
    order, first, second = journey["order"], journey["first"], journey["second"]
    expected_total = first["price_minor"] * 1 + second["price_minor"] * 2
    assert journey["checkout"]["total_minor"] == order["total_minor"] == expected_total
    with psycopg.connect(journey["env"]["STORE_DB_DSN"]) as conn:
        rows = conn.execute("SELECT total_minor, currency, user_id FROM orders WHERE cart_id = %s",
                            (order["cart_id"],)).fetchall()
        status = conn.execute("SELECT status FROM carts WHERE cart_id = %s", (order["cart_id"],)).fetchone()
    assert rows == [(expected_total, "EUR", journey["session"]["X-User-Id"])]
    assert status == ("converted",)


def test_kafka_has_exactly_the_journey_events(journey):
    messages = journey["messages"]
    # The retried search reuses its key, so it has the same event_id as the first one.
    assert [m["event_id"] for m in messages] == journey["expected_ids"]
    assert journey["expected_ids"][0] == journey["expected_ids"][1]
    assert [validate_payload(m["value"])["event_type"] for m in messages] == [
        "search", "search", "product_view", "add_to_cart", "add_to_cart", "checkout_start", "purchase"]


def test_events_carry_identity_join_keys_and_prices(journey):
    payloads = [validate_payload(m["value"]) for m in journey["messages"]]
    session, order = journey["session"], journey["order"]
    assert {p["session_id"] for p in payloads} == {session["X-Session-Id"]}
    assert {p["user_id"] for p in payloads} == {session["X-User-Id"]}
    by_type = {}
    for p in payloads:
        by_type.setdefault(p["event_type"], []).append(p)
    assert by_type["product_view"][0]["product_id"] == journey["first"]["product_id"]
    assert [p["product_id"] for p in by_type["add_to_cart"]] == [journey["first"]["product_id"],
                                                                 journey["second"]["product_id"]]
    assert {p["cart_id"] for t in ("add_to_cart", "checkout_start", "purchase") for p in by_type[t]} == {
        order["cart_id"]}
    purchase = by_type["purchase"][0]
    assert purchase["order_id"] == order["order_id"]
    assert purchase["properties"]["total"] == {"amount_minor": order["total_minor"], "currency": "EUR"}
    assert by_type["search"][0]["properties"]["results_count"] >= 2


def test_openapi_docs_are_served(api):
    _, server = api
    assert httpx.get(f"{server.url}/docs", timeout=10).status_code == 200
    paths = httpx.get(f"{server.url}/openapi.json", timeout=10).json()["paths"]
    assert {"/home", "/products", "/search", "/products/{product_id}", "/cart/items", "/cart/items/{product_id}",
            "/cart", "/checkout/start", "/checkout/complete", "/health"} <= set(paths)
