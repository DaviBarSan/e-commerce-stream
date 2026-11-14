"""E2E-1: carts and orders from real API journeys reach fct_carts, fct_order_lines and fct_orders."""
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from e2e_support import ApiServer, Shopper, dbt, ingest_events, ingest_until, start_group_at_end
from e2e_support import warehouse_query as query
from telemetry import build_event


@pytest.fixture(scope="module")
def built(env, tmp_path_factory):
    logs = tmp_path_factory.mktemp("commerce")
    run_id = uuid.uuid4().hex[:8]
    group = start_group_at_end(env, f"e2e-commerce-{run_id}")
    server = ApiServer(env, logs / "api.log").start()
    try:
        buyer = Shopper(server.url, run_id, "buyer")
        buyer.add("p-0001", "add-1")
        buyer.add("p-0001", "add-2")
        buyer.add("p-0002", "add-3")
        buyer.remove("p-0002", "remove")
        buyer.add("p-0002", "add-4")
        checkout = buyer.checkout()
        order = buyer.purchase()

        browser = Shopper(server.url, run_id, "browser")
        cart = browser.add("p-0003", "add")
    finally:
        server.stop()  # flushes the direct events; the relay has published the outbox by then

    ingest_until(env, group, buyer.event_ids + browser.event_ids, logs / "consumer.log")
    first = dbt("build")

    def carts():
        rows = query(env, "SELECT * FROM marts.fct_carts WHERE cart_id = ANY(%s)",
                     ([order["cart_id"], cart["cart_id"]],))
        return {r["cart_id"]: r for r in rows}

    before = carts()
    # Move the warehouse clock past 30 minutes with a later event from another user.
    clock = build_event("page_view", idempotency_key=f"{run_id}-clock", user_id=f"anon-{run_id}-clock",
                        session_id=f"s-{run_id}-clock", page_url="/", properties={"page": "home"},
                        event_ts=datetime.now(timezone.utc) + timedelta(minutes=31))
    ingest_events(env, [clock], logs / "clock")
    dbt("build")

    with psycopg.connect(env["STORE_DB_DSN"]) as conn:
        stored = conn.execute("SELECT total_minor, currency FROM orders WHERE order_id = %s",
                              (order["order_id"],)).fetchone()
    return {
        "build": first, "order": order, "checkout": checkout, "buyer_cart": order["cart_id"],
        "browser_cart": cart["cart_id"], "carts_before": before, "carts_after": carts(), "stored": stored,
        "lines": query(env, "SELECT * FROM marts.fct_order_lines WHERE order_id = %s ORDER BY product_id",
                       (order["order_id"],)),
        "orders": query(env, "SELECT * FROM marts.fct_orders WHERE order_id = %s", (order["order_id"],)),
        "prices": {r["product_id"]: r["price_minor"] for r in query(
            env, "SELECT product_id, last_price_minor AS price_minor FROM marts.dim_products "
                 "WHERE product_id IN ('p-0001', 'p-0002')")},
    }


def test_the_build_passes(built):
    assert "ERROR=0" in built["build"].stdout and "Completed successfully" in built["build"].stdout


def test_order_lines_hold_exactly_the_purchased_lines(built):
    lines, prices = built["lines"], built["prices"]
    # p-0001 added twice; p-0002 added, removed, then added again: one unit.
    assert [(l["product_id"], l["quantity"]) for l in lines] == [("p-0001", 2), ("p-0002", 1)]
    for line in lines:
        assert line["unit_price_minor"] == prices[line["product_id"]]
        assert line["line_total_minor"] == line["quantity"] * line["unit_price_minor"]
        assert line["currency"] == "EUR"


def test_the_order_total_matches_the_purchase_and_the_store(built):
    (order,) = built["orders"]
    assert order["items_count"] == 2 and order["units"] == 3
    assert order["order_total_minor"] == built["order"]["total_minor"] == built["stored"][0]
    assert order["currency"] == built["stored"][1] == "EUR"


def test_the_bought_cart_is_converted_with_its_milestones(built):
    cart = built["carts_after"][built["buyer_cart"]]
    assert cart["status"] == "converted"
    assert cart["created_at"] <= cart["checkout_started_at"] <= cart["purchased_at"]
    assert cart["minutes_to_checkout"] >= 0 and cart["minutes_to_purchase"] >= 0
    assert (cart["line_count"], cart["unit_count"]) == (2, 3)
    assert cart["checkout_total_minor"] == built["checkout"]["total_minor"]


def test_the_idle_cart_is_abandoned_once_the_clock_passes_30_minutes(built):
    assert built["carts_before"][built["browser_cart"]]["status"] in ("open", "abandoned")
    after = built["carts_after"][built["browser_cart"]]
    assert after["status"] == "abandoned"
    assert after["purchased_at"] is None and (after["line_count"], after["unit_count"]) == (1, 1)
    assert built["carts_after"][built["buyer_cart"]]["status"] == "converted"
