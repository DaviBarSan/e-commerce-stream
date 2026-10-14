"""E2E-1: one journey-1 session goes Kafka → raw → staging, typed and grouped into event families."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from e2e_support import ConsumerProcess, dbt, raw_rows, start_group_at_end, wait_for
from e2e_support import warehouse_query as query
from telemetry import build_event, get_producer

HOT_COLUMNS = ("schema_version", "event_type", "event_ts", "produced_at", "ingested_at", "user_id",
               "anonymous_id", "session_id", "product_id", "cart_id", "order_id")


def eur(amount):
    return {"amount_minor": amount, "currency": "EUR"}


def journey(run_id):
    """(event_type, fields, expected family, action, page_type) for one session with every family."""
    p1, p2, cart = f"p-{run_id}-1", f"p-{run_id}-2", f"c-{run_id}"
    return [
        ("page_view", {"page_url": "/", "properties": {"page": "home"}}, "navigation", "page_view", "home"),
        ("page_view", {"page_url": "/catalog", "properties": {"page": "catalog"}},
         "navigation", "page_view", "catalog"),
        ("search", {"page_url": "/search?q=lamp", "properties": {"query": "lamp", "results_count": 3}},
         "navigation", "search", "search"),
        ("product_view", {"page_url": f"/products/{p1}", "product_id": p1,
                          "properties": {"category": "lighting", "price": eur(1999)}},
         "navigation", "product_view", "pdp"),
        ("add_to_cart", {"page_url": f"/products/{p1}", "product_id": p1, "cart_id": cart,
                         "properties": {"quantity": 2, "unit_price": eur(1999)}}, "cart", "add", "pdp"),
        ("add_to_cart", {"page_url": f"/products/{p2}", "product_id": p2, "cart_id": cart,
                         "properties": {"quantity": 1, "unit_price": eur(4500)}}, "cart", "add", "pdp"),
        ("page_view", {"page_url": "/cart", "properties": {"page": "cart"}}, "navigation", "page_view", "cart"),
        ("remove_from_cart", {"page_url": "/cart", "product_id": p2, "cart_id": cart, "properties": {}},
         "cart", "remove", "cart"),
        ("add_to_cart", {"page_url": f"/products/{p2}", "product_id": p2, "cart_id": cart,
                         "properties": {"quantity": 1, "unit_price": eur(4500)}}, "cart", "add", "pdp"),
        ("checkout_start", {"page_url": "/checkout", "cart_id": cart,
                            "properties": {"items_count": 3, "cart_total": eur(8498)}},
         "checkout", "start", "checkout"),
        ("purchase", {"page_url": "/checkout/confirmation", "cart_id": cart, "order_id": f"o-{run_id}",
                      "properties": {"total": eur(8498)}}, "checkout", "purchase", "confirmation"),
    ]


@pytest.fixture(scope="module")
def staged(env, tmp_path_factory):
    run_id, t0 = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    steps = journey(run_id)
    events = [build_event(event_type, idempotency_key=f"s-{run_id}-{i}", event_ts=t0 + timedelta(seconds=i),
                          user_id=f"anon-{run_id}", session_id=f"s-{run_id}", **fields)
              for i, (event_type, fields, *_) in enumerate(steps)]
    ids = [str(e.event_id) for e in events]

    group = start_group_at_end(env, f"e2e-dbt-{run_id}")
    producer = get_producer(env)
    for event in events:
        producer.send_event(event)
    assert producer.flush(30) == 0
    producer.close()

    consumer = ConsumerProcess(env, tmp_path_factory.mktemp("ingest") / "consumer.log",
                               INGEST_GROUP_ID=group, INGEST_FLUSH_SECONDS=1).start()
    try:
        wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 60, message="the session in raw")
    finally:
        consumer.stop()

    build = dbt("build --select +staging")  # raises if any model or test fails

    def rows(relation):
        found = query(env, f"SELECT * FROM staging.{relation} WHERE event_id = ANY(%s::uuid[])", (ids,))
        return {str(r["event_id"]): r for r in found}

    return {
        "events": events, "steps": steps, "ids": ids, "build": build,
        "raw": {str(r["event_id"]): r for r in raw_rows(env, ids)},
        "clickstream": rows("stg_clickstream"),
        "families": {family: rows(f"stg_events__{family}") for family in ("navigation", "cart", "checkout")},
    }


def test_the_staging_build_passes_with_every_test(staged):
    assert "ERROR=0" in staged["build"].stdout
    assert "Completed successfully" in staged["build"].stdout


def test_each_event_appears_once_with_its_raw_columns(staged):
    clickstream = staged["clickstream"]
    assert set(clickstream) == set(staged["ids"])
    for event_id, row in clickstream.items():
        raw = staged["raw"][event_id]
        for column in HOT_COLUMNS:
            assert row[column] == raw[column], (event_id, column)
        assert row["page_url"] == raw["payload"]["page_url"]


def test_each_event_has_its_family_action_and_page_type(staged):
    for event_id, (event_type, _, family, action, page_type) in zip(staged["ids"], staged["steps"]):
        row = staged["clickstream"][event_id]
        assert (row["event_type"], row["family"], row["action"], row["page_type"]) == \
            (event_type, family, action, page_type), event_id


def test_each_family_view_holds_exactly_its_events(staged):
    for family, rows in staged["families"].items():
        expected = {i for i, step in zip(staged["ids"], staged["steps"]) if step[2] == family}
        assert set(rows) == expected, family
        for event_id in expected:
            assert rows[event_id]["action"] == staged["clickstream"][event_id]["action"]


def test_family_properties_are_typed(staged):
    ids, nav, cart, checkout = (staged["ids"], *(staged["families"][f] for f in ("navigation", "cart", "checkout")))

    assert [nav[ids[i]]["page"] for i in (0, 1, 6)] == ["home", "catalog", "cart"]
    assert (nav[ids[2]]["search_query"], nav[ids[2]]["search_results_count"]) == ("lamp", 3)
    product_view = nav[ids[3]]
    assert (product_view["product_category"], product_view["product_price_minor"], product_view["currency"]) == \
        ("lighting", 1999, "EUR")

    assert [(cart[ids[i]]["quantity"], cart[ids[i]]["unit_price_minor"], cart[ids[i]]["currency"])
            for i in (4, 5, 7, 8)] == [(2, 1999, "EUR"), (1, 4500, "EUR"), (None, None, None), (1, 4500, "EUR")]

    start, purchase = checkout[ids[9]], checkout[ids[10]]
    assert (start["items_count"], start["cart_total_minor"], start["order_total_minor"], start["currency"]) == \
        (3, 8498, None, "EUR")
    assert (purchase["order_total_minor"], purchase["cart_total_minor"], purchase["currency"]) == (8498, None, "EUR")
