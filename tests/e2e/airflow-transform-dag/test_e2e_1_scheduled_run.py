"""E2E-1: a scheduled run builds every layer, fills the marts and leaves its dbt artifacts on the host."""
import json
import uuid
from datetime import datetime, timezone

import pytest

from e2e_support import TRANSFORM_DAG as DAG
from e2e_support import TRANSFORM_LAYERS as LAYERS
from e2e_support import TRANSFORM_TASKS as TASKS
from e2e_support import (LOCAL_SERVICES, Shopper, apply_schedule, parse_ts, raw_rows, restore_default_schedule,
                         run_folder, wait_for)
from e2e_support import warehouse_query as query


@pytest.fixture(scope="module")
def scheduled():
    env, api = apply_schedule("*/2 * * * *")
    try:
        api.set_paused(DAG, True)
        store_api = LOCAL_SERVICES.outputs()["store_api_url"]
        run_id = uuid.uuid4().hex[:8]
        buyer, browser = Shopper(store_api, run_id, "buyer"), Shopper(store_api, run_id, "browser")
        buyer.call("GET", "/home", "page_view", "home")
        buyer.add("p-0001", "add")
        buyer.checkout()
        order = buyer.purchase()
        browser.add("p-0002", "add")
        ids = buyer.event_ids + browser.event_ids
        # The consumer container ingests them; the outbox relay publishes the cart and purchase events.
        wait_for(lambda: len(raw_rows(env, ids, "event_id")) == len(ids), 60, interval=1, message="events in raw")
        landed = datetime.now(timezone.utc)

        api.set_paused(DAG, False)  # catchup=False: the latest interval is scheduled right away

        def finished_scheduled_run():
            for r in api.runs(DAG):
                started = parse_ts(r["start_date"])
                if r["run_type"] == "scheduled" and started and started > landed and r["state"] in ("success",
                                                                                                    "failed"):
                    return r
            return None

        dag_run = wait_for(finished_scheduled_run, 420, interval=10, message="a finished scheduled run")
        api.set_paused(DAG, True)
        rid = dag_run["dag_run_id"]
        users = [buyer.headers["X-User-Id"], browser.headers["X-User-Id"]]
        yield {
            "run": dag_run, "states": api.task_states(DAG, rid), "folder": run_folder(rid), "order": order,
            "summary": api.xcom(DAG, rid, "publish_run_summary") if dag_run["state"] == "success" else None,
            "orders": query(env, "SELECT * FROM marts.fct_orders WHERE order_id = %s", (order["order_id"],)),
            "sessions": query(env, "SELECT user_id FROM marts.fct_sessions WHERE user_id = ANY(%s)", (users,)),
            "users": users,
        }
    finally:
        restore_default_schedule()


def test_the_scheduled_run_succeeds_with_every_task(scheduled):
    assert scheduled["run"]["state"] == "success", scheduled["states"]
    assert scheduled["states"] == dict.fromkeys(TASKS, "success")


def test_the_marts_hold_the_new_journeys(scheduled):
    (order,) = scheduled["orders"]
    assert order["order_total_minor"] == order["purchase_total_minor"] == scheduled["order"]["total_minor"]
    assert {r["user_id"] for r in scheduled["sessions"]} == set(scheduled["users"])


def test_the_summary_covers_every_layer_with_no_errors(scheduled):
    summary = scheduled["summary"]
    assert sorted(summary["layers"]) == sorted(LAYERS)  # the API returns XCom dicts with reordered keys
    assert summary["total"]["error"] == summary["total"]["fail"] == 0
    for layer in LAYERS:
        results = json.loads((scheduled["folder"] / layer / "run_results.json").read_text(encoding="utf-8"))
        assert len(results["results"]) == sum(v for k, v in summary["layers"][layer].items() if k != "elapsed_s")


def test_the_artifacts_are_on_the_host(scheduled):
    folder = scheduled["folder"]
    for task in ["check_raw_freshness", *LAYERS]:
        assert (folder / task / "dbt.log").exists(), f"{task}: no dbt.log"
    for layer in LAYERS:
        assert (folder / layer / "run_results.json").exists() and (folder / layer / "manifest.json").exists()
    assert (folder / "dbt_marts" / "compiled" / "clickstream" / "models" / "marts" / "fct_orders.sql").exists()
    assert json.loads((folder / "summary.json").read_text(encoding="utf-8")) == scheduled["summary"]
