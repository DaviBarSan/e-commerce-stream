"""clickstream_transform (F05.4, spec 05 §8): raw freshness check, one dbt build per layer, run summary.

check_raw_freshness → dbt_seed → dbt_staging → dbt_intermediate → dbt_marts → publish_run_summary

Each dbt task writes its artifacts (run_results.json, manifest.json, compiled SQL, dbt.log) to
DBT_RUNS_DIR/<run>/<task>, which is the host's airflow-runs/ folder: a failed layer can be read there and
rerun alone by clearing its task. Only core operators, so the DAG runs unchanged on Composer (spec 05 §7).
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG, Param

DBT = "/opt/dbt-venv/bin/dbt"
RUNS_DIR = os.environ.get("DBT_RUNS_DIR", "/opt/airflow/dbt-runs")
# The run ID with characters a Windows host path can't hold (: and +) removed.
RUN_FOLDER = "{{ run_id | replace(':', '') | replace('+', '') }}"

LAYERS = {  # task_id -> dbt selector
    "dbt_seed": "resource_type:seed",
    "dbt_staging": "path:models/staging",
    "dbt_intermediate": "path:models/intermediate",
    "dbt_marts": "path:models/marts",
}

schedule = os.environ.get("TRANSFORM_SCHEDULE", "@hourly").strip()

log = logging.getLogger(__name__)


def dbt_env(task_id: str) -> dict[str, str]:
    """Per-task artifact paths; the rest of the container env (DSN, target) is kept (append_env)."""
    folder = f"{RUNS_DIR}/{RUN_FOLDER}/{task_id}"
    return {"DBT_TARGET_PATH": folder, "DBT_LOG_PATH": folder}


def publish_run_summary(run_id: str) -> dict:
    """Per-layer and total counts by status from each layer's run_results.json; written next to them."""
    run_dir = Path(RUNS_DIR) / run_id.replace(":", "").replace("+", "")
    statuses = ("success", "error", "fail", "warn", "skipped")
    summary = {"run_id": run_id, "layers": {}, "total": dict.fromkeys(statuses, 0) | {"elapsed_s": 0.0}}
    for task_id in LAYERS:
        results = json.loads((run_dir / task_id / "run_results.json").read_text(encoding="utf-8"))
        counts = dict.fromkeys(statuses, 0)
        for result in results["results"]:
            status = "success" if result["status"] in ("success", "pass") else result["status"]
            counts[status] = counts.get(status, 0) + 1
        layer = counts | {"elapsed_s": round(results["elapsed_time"], 2)}
        summary["layers"][task_id] = layer
        for key, value in layer.items():
            summary["total"][key] = summary["total"].get(key, 0) + value
    summary["total"]["elapsed_s"] = round(summary["total"]["elapsed_s"], 2)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(json.dumps({"event": "run_summary", **summary}))
    return summary


with DAG(
    dag_id="clickstream_transform",
    description="Raw freshness check, then one dbt build per layer (seed, staging, intermediate, marts).",
    schedule=None if schedule.lower() == "none" else schedule,
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,  # incremental models must never build twice at once
    params={"raw_freshness_minutes": Param(int(os.environ.get("RAW_FRESHNESS_MINUTES", "30")), type="integer",
                                           minimum=1, description="Fail when raw has no rows this recent.")},
    tags=["clickstream", "dbt"],
):
    freshness = BashOperator(
        task_id="check_raw_freshness",
        bash_command=f"cd /opt/dbt && {DBT} source freshness --select source:raw.clickstream_events",
        env={**dbt_env("check_raw_freshness"), "RAW_FRESHNESS_MINUTES": "{{ params.raw_freshness_minutes }}"},
        append_env=True,
    )

    previous = freshness
    for task_id, selector in LAYERS.items():
        layer = BashOperator(
            task_id=task_id,
            bash_command=f"cd /opt/dbt && {DBT} build --select {selector} --indirect-selection buildable",
            env=dbt_env(task_id),
            append_env=True,
            retries=1,
            retry_delay=timedelta(seconds=30),
        )
        previous >> layer
        previous = layer

    summary = PythonOperator(
        task_id="publish_run_summary",
        python_callable=publish_run_summary,
        op_kwargs={"run_id": "{{ run_id }}"},
    )
    previous >> summary
