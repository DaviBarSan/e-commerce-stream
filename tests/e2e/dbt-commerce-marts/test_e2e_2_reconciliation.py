"""E2E-2: orders placed during a broker outage reconcile between marts.fct_orders and store.orders."""
import uuid

import psycopg

from e2e_support import (ApiServer, Shopper, dbt, ingest_until, project_prefix, run, start_group_at_end,
                         wait_container_healthy)
from e2e_support import warehouse_query as query


def test_orders_from_an_outage_reconcile_with_the_store(env, tmp_path):
    run_id = uuid.uuid4().hex[:8]
    kafka = f"{project_prefix()}kafka"
    group = start_group_at_end(env, f"e2e-reconcile-{run_id}")  # before the outage: nothing is missed
    server = ApiServer(env, tmp_path / "api.log").start()
    shoppers, order_ids = [], []
    try:
        run(["docker", "stop", kafka], check=True, timeout=120)
        try:
            for name, products in [("first", ["p-0004"]), ("second", ["p-0005", "p-0006"])]:
                shopper = Shopper(server.url, run_id, name)
                for i, product in enumerate(products):
                    shopper.add(product, f"add-{i}", quantity=i + 1)
                order_ids.append(shopper.purchase()["order_id"])
                shoppers.append(shopper)
        finally:
            run(["docker", "start", kafka], check=True, timeout=120)
            wait_container_healthy(kafka)
        # State changes waited in the outbox; the relay publishes them now that Kafka is back.
        outbox = [event_id for shopper in shoppers for event_id in shopper.event_ids]  # adds and purchases
        ingest_until(env, group, outbox, tmp_path / "consumer.log", timeout=90)
    finally:
        server.stop()

    dbt("build")

    with psycopg.connect(env["STORE_DB_DSN"]) as conn:
        store = conn.execute("SELECT order_id, total_minor, currency FROM orders WHERE order_id = ANY(%s) "
                             "ORDER BY order_id", (order_ids,)).fetchall()
    marts = query(env, "SELECT order_id, order_total_minor, currency FROM marts.fct_orders "
                       "WHERE order_id = ANY(%s) ORDER BY order_id", (order_ids,))
    assert len(store) == len(order_ids) == 2
    assert [(r["order_id"], r["order_total_minor"], r["currency"]) for r in marts] == store
