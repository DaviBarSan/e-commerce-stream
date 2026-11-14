"""E2E-2: stale raw stops the run; a failing layer is found on the host and rerun alone; runs never overlap."""
import json
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from e2e_support import TRANSFORM_DAG as DAG
from e2e_support import TRANSFORM_LAYERS as LAYERS
from e2e_support import apply_schedule, mart_counts, parse_ts, restore_default_schedule, run_folder, wait_for
from e2e_support import warehouse_query as query


@pytest.fixture(scope="module")
def manual():
    env, api = apply_schedule("none")  # triggered runs only
    try:
        api.set_paused(DAG, False)
        yield env, api
    finally:
        api.set_paused(DAG, True)
        restore_default_schedule()


def raw_age_seconds(env):
    newest = query(env, f"SELECT max(ingested_at) AS t FROM {env['WAREHOUSE_RAW_SCHEMA']}.clickstream_events",
                   dsn_key="WAREHOUSE_DSN")[0]["t"]
    return (datetime.now(timezone.utc) - newest).total_seconds()


def test_stale_raw_fails_the_freshness_check_and_skips_every_layer(manual):
    env, api = manual
    wait_for(lambda: raw_age_seconds(env) > 70, 240, interval=5, message="raw to be quiet for over a minute")
    before = mart_counts(env)

    run_id = api.trigger(DAG, conf={"raw_freshness_minutes": 1})
    assert api.wait_for_run(DAG, run_id)["state"] == "failed"
    states = api.task_states(DAG, run_id)
    assert states["check_raw_freshness"] == "failed"
    assert all(states[t] == "upstream_failed" for t in [*LAYERS, "publish_run_summary"]), states
    assert mart_counts(env) == before


def test_a_failing_layer_is_found_on_the_host_and_rerun_alone(manual):
    env, api = manual
    raw = f"{env['WAREHOUSE_RAW_SCHEMA']}.clickstream_events"
    event_id, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    payload = {"event_id": event_id, "schema_version": "1", "event_type": "e2e_unknown_type", "page_url": "/"}
    with psycopg.connect(env["WAREHOUSE_DSN"], autocommit=True) as conn:  # bypasses the consumer's validation
        conn.execute(
            f"INSERT INTO {raw} (event_id, schema_version, event_type, event_ts, produced_at, ingested_at, "
            "session_id, user_id, source_topic, source_partition, source_offset, payload) "
            "VALUES (%s, '1', 'e2e_unknown_type', %s, %s, %s, 's-e2e-bad', 'anon-e2e-bad', 'e2e', 0, -1, %s)",
            (event_id, now, now, now, json.dumps(payload)))
    try:
        run_id = api.trigger(DAG)
        assert api.wait_for_run(DAG, run_id)["state"] == "failed"
        states = api.task_states(DAG, run_id)
        assert (states["check_raw_freshness"], states["dbt_seed"], states["dbt_staging"]) == (
            "success", "success", "failed"), states
        assert all(states[t] == "upstream_failed" for t in ["dbt_intermediate", "dbt_marts", "publish_run_summary"])

        results = json.loads((run_folder(run_id) / "dbt_staging" / "run_results.json").read_text(encoding="utf-8"))
        failing = [r["unique_id"] for r in results["results"] if r["status"] in ("fail", "error")]
        assert any("relationships_stg_clickstream_event_type" in u for u in failing), failing
    finally:
        with psycopg.connect(env["WAREHOUSE_DSN"], autocommit=True) as conn:
            conn.execute(f"DELETE FROM {raw} WHERE event_id = %s", (event_id,))

    api.clear(DAG, run_id, "dbt_staging")  # resume the same run from staging
    wait_for(lambda: api.run(DAG, run_id)["state"] == "success", 600, interval=5, message="the cleared run")
    assert set(api.task_states(DAG, run_id).values()) == {"success"}


def test_two_runs_are_serial_and_the_second_changes_nothing(manual):
    env, api = manual
    before = mart_counts(env)  # the previous flow's rerun built everything; no new raw rows since
    first, second = api.trigger(DAG), api.trigger(DAG)
    runs = [api.wait_for_run(DAG, r, timeout=900) for r in (first, second)]
    assert [r["state"] for r in runs] == ["success", "success"]
    assert parse_ts(runs[0]["end_date"]) <= parse_ts(runs[1]["start_date"]), "the runs overlapped"
    assert mart_counts(env) == before
