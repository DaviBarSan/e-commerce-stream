"""E2E-1: three journeys go Kafka → raw → marts; sessions, the ordered funnel and the dimensions match them."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from e2e_support import dbt, ingest_events
from e2e_support import warehouse_query as query
from telemetry import build_event


def eur(amount):
    return {"amount_minor": amount, "currency": "EUR"}


def step(event_type, run_id, product="p1", **extra):
    """(event_type, fields) for one journey-1 step."""
    product_id, cart_id = f"p-{run_id}-{product}", f"c-{run_id}"
    fields = {
        "page_view": {"page_url": "/", "properties": {"page": "home"}},
        "search": {"page_url": "/search?q=lamp", "properties": {"query": "lamp", "results_count": 3}},
        "product_view": {"page_url": f"/products/{product_id}", "product_id": product_id,
                         "properties": {"category": "lighting", "price": eur(1999)}},
        "add_to_cart": {"page_url": f"/products/{product_id}", "product_id": product_id, "cart_id": cart_id,
                        "properties": {"quantity": 1, "unit_price": eur(1999)}},
        "checkout_start": {"page_url": "/checkout", "cart_id": cart_id,
                           "properties": {"items_count": 1, "cart_total": eur(1999)}},
        "purchase": {"page_url": "/checkout/confirmation", "cart_id": cart_id, "order_id": f"o-{run_id}",
                     "properties": {"total": eur(1999)}},
    }[event_type]
    return event_type, {**fields, **extra}


@pytest.fixture(scope="module")
def built(env, tmp_path_factory):
    run_id = uuid.uuid4().hex[:8]
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)
    users = {name: f"anon-{run_id}-{name}" for name in ("buyer", "browser", "returning")}

    # (user, client session, minutes after t0, step)
    plan = [
        ("buyer", "s1", 0, step("page_view", run_id)),
        ("buyer", "s1", 1, step("search", run_id)),
        ("buyer", "s1", 2, step("product_view", run_id)),
        ("buyer", "s1", 3, step("add_to_cart", run_id)),
        ("buyer", "s1", 4, step("checkout_start", run_id)),
        ("buyer", "s1", 5, step("purchase", run_id)),
        ("browser", "s2", 0, step("search", run_id)),
        ("browser", "s2", 2, step("product_view", run_id, product="p2")),
        ("browser", "s2", 4, step("add_to_cart", run_id, product="p2", cart_id=f"c-{run_id}-b")),
        # same client session_id across a 40-minute gap: two derived sessions
        ("returning", "s3", 0, step("page_view", run_id)),
        ("returning", "s3", 1, step("search", run_id)),
        ("returning", "s3", 2, step("product_view", run_id, product="p3")),
        ("returning", "s3", 42, step("product_view", run_id, product="p3")),
        ("returning", "s3", 43, step("add_to_cart", run_id, product="p3", cart_id=f"c-{run_id}-r")),
    ]
    events = [build_event(event_type, idempotency_key=f"{run_id}-{i}", event_ts=t0 + timedelta(minutes=minute),
                          user_id=users[user], session_id=f"{session}-{run_id}", **fields)
              for i, (user, session, minute, (event_type, fields)) in enumerate(plan)]
    ingest_events(env, events, tmp_path_factory.mktemp("ingest"))
    build = dbt("build")

    user_ids = list(users.values())
    sessions = query(env, "SELECT * FROM marts.fct_sessions WHERE user_id = ANY(%s) ORDER BY user_id, session_start_at",
                     (user_ids,))
    return {
        "build": build, "users": users, "t0": t0, "events": events,
        "sessions": sessions,
        "dim_sessions": query(env, "SELECT * FROM marts.dim_sessions WHERE user_id = ANY(%s) "
                                   "ORDER BY session_start_at", (user_ids,)),
        "dim_users": {r["user_id"]: r for r in query(env, "SELECT * FROM marts.dim_users WHERE user_id = ANY(%s)",
                                                       (user_ids,))},
        "fct_events": query(env, "SELECT * FROM marts.fct_events WHERE user_id = ANY(%s)", (user_ids,)),
        "funnel_totals": query(env, "SELECT sum(reached_search) s1, sum(reached_product_view) s2, "
                                    "sum(reached_add_to_cart) s3, sum(reached_checkout) s4, "
                                    "sum(reached_purchase) s5 FROM marts.fct_sessions WHERE user_id = ANY(%s)",
                               (user_ids,))[0],
    }


def sessions_of(built, name):
    return [s for s in built["sessions"] if s["user_id"] == built["users"][name]]


def test_the_full_build_passes(built):
    assert "ERROR=0" in built["build"].stdout and "Completed successfully" in built["build"].stdout


def test_a_40_minute_gap_splits_one_client_session_into_two(built):
    assert len(built["sessions"]) == 4
    assert len(sessions_of(built, "returning")) == 2
    returning = [s for s in built["dim_sessions"] if s["user_id"] == built["users"]["returning"]]
    assert len({s["client_session_id"] for s in returning}) == 1


def test_the_buyer_reaches_every_funnel_step_in_order(built):
    (buyer,) = sessions_of(built, "buyer")
    t0 = built["t0"]
    assert [buyer[f"reached_{s}"] for s in ("search", "product_view", "add_to_cart", "checkout", "purchase")] \
        == [1, 1, 1, 1, 1]
    assert buyer["is_converted"] is True
    assert (buyer["first_search_at"], buyer["first_purchase_at"]) == (t0 + timedelta(minutes=1),
                                                                     t0 + timedelta(minutes=5))
    assert buyer["landing_page_type"] == "home" and buyer["exit_page_type"] == "confirmation"
    assert buyer["duration_seconds"] == 300 and buyer["event_count"] == 6


def test_the_browser_stops_after_add_to_cart(built):
    (browser,) = sessions_of(built, "browser")
    assert [browser[f"reached_{s}"] for s in ("search", "product_view", "add_to_cart", "checkout", "purchase")] \
        == [1, 1, 1, 0, 0]
    assert browser["is_converted"] is False


def test_the_funnel_never_increases(built):
    totals = built["funnel_totals"]
    assert [totals[k] for k in ("s1", "s2", "s3", "s4", "s5")] == [3, 3, 2, 1, 1]


def test_users_and_events_join_to_the_dimensions(built):
    users = built["dim_users"]
    assert users[built["users"]["returning"]]["is_returning"] is True
    assert users[built["users"]["buyer"]]["is_returning"] is False
    assert users[built["users"]["buyer"]]["lifetime_orders"] == 1
    assert all(u["is_anonymous"] for u in users.values())

    session_keys = {s["session_key"] for s in built["dim_sessions"]}
    assert len(built["fct_events"]) == len(built["events"])
    for event in built["fct_events"]:
        assert event["session_key"] in session_keys
        assert event["date_day"] == event["event_ts"].astimezone(timezone.utc).date()
        assert event["hour_of_day"] == event["event_ts"].astimezone(timezone.utc).hour
