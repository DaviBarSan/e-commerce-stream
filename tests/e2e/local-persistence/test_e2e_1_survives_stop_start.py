"""E2E-1: data, run history and task logs survive make stop / make start and an Airflow container replacement."""
import hashlib
import os
import uuid

import pytest

from e2e_support import TRANSFORM_DAG as DAG
from e2e_support import (LOCAL_SERVICES, LOCAL_STACKS, REPO_ROOT, AirflowApi, Shopper, airflow_container, inspect,
                         local_env, long_running_containers, make, persisted_counts, project_containers, project_prefix,
                         raw_rows, tf_env, wait_container_healthy, wait_for)

ONE_SHOT = ("airflow-init", "store-seed")


def host_name(name):
    """A container path segment as stored on the host: on Windows, Docker Desktop keeps ':' as U+F03A."""
    return name.replace(":", "\uf03a") if os.name == "nt" else name


def env_file_hash():
    return hashlib.sha256((REPO_ROOT / ".env.local").read_bytes()).hexdigest()


def snapshot(env, run_id):
    api = AirflowApi(env)  # a fresh token: the admin login must still work
    return {"counts": persisted_counts(env), "states": api.task_states(DAG, run_id),
            "log": api.task_log(DAG, run_id, "dbt_marts")}


@pytest.fixture(scope="module")
def before():
    env = local_env()
    api = AirflowApi(env)
    api.wait_for_dag(DAG)

    shopper = Shopper(LOCAL_SERVICES.outputs()["store_api_url"], uuid.uuid4().hex[:8], "buyer")
    shopper.add("p-0001", "add")
    shopper.checkout()
    shopper.purchase()
    wait_for(lambda: len(raw_rows(env, shopper.event_ids, "event_id")) == len(shopper.event_ids), 60, interval=1,
             message="the purchase events in raw")

    was_paused = api.request("GET", f"/dags/{DAG}").json()["is_paused"]
    api.set_paused(DAG, False)
    try:
        run_id = api.trigger(DAG, conf={"raw_freshness_minutes": 600})
        assert api.wait_for_run(DAG, run_id, timeout=900)["state"] == "success"
    finally:
        api.set_paused(DAG, was_paused)  # leave the DAG as the developer had it

    prefix = project_prefix()
    return {
        "env": env, "run_id": run_id, "env_hash": env_file_hash(), "containers": project_containers(),
        "one_shot_started": {c: inspect(f"{prefix}{c}", "{{.State.StartedAt}}") for c in ONE_SHOT},
        "snapshot": snapshot(env, run_id), "prefix": prefix,
    }


def test_make_stop_stops_every_container_and_keeps_them(before):
    make("stop")
    assert project_containers(running_only=True) == [], "containers still running after make stop"
    assert project_containers() == before["containers"], "make stop removed containers"


def test_make_start_resumes_without_terraform_changes(before):
    make("start")
    for name in long_running_containers():
        assert inspect(name, "{{.State.Running}}") == "true", f"{name} is not running"
    started = {c: inspect(f"{before['prefix']}{c}", "{{.State.StartedAt}}") for c in ONE_SHOT}
    assert started == before["one_shot_started"], "a one-shot container was run again"
    for stack in LOCAL_STACKS:
        assert stack.plan_exit_code() == 0, f"{stack.dir.name} has pending changes after make start"
    assert env_file_hash() == before["env_hash"], ".env.local changed"


def test_data_history_and_logs_are_unchanged(before):
    after = snapshot(before["env"], before["run_id"])
    assert after["counts"] == before["snapshot"]["counts"]
    assert after["states"] == before["snapshot"]["states"]
    assert after["log"] == before["snapshot"]["log"]
    assert after["log"][1], "the dbt_marts log is empty"


def test_task_logs_survive_an_airflow_container_replacement(before):
    containers = [airflow_container(c) for c in ("scheduler", "api-server")]
    ids = {c: inspect(c, "{{.Id}}") for c in containers}
    LOCAL_SERVICES.tf("apply", "-input=false", "-auto-approve", "-replace=module.airflow.docker_container.scheduler",
                      "-replace=module.airflow.docker_container.api_server", env=tf_env())
    for c in containers:
        wait_container_healthy(c, timeout=300)
        assert inspect(c, "{{.Id}}") != ids[c], f"{c} was not replaced"

    try_number, events = AirflowApi(before["env"]).task_log(DAG, before["run_id"], "dbt_marts")
    assert (try_number, events) == before["snapshot"]["log"], "the task log changed after the replacement"
    log_file = (REPO_ROOT / "airflow-logs" / f"dag_id={DAG}" / f"run_id={host_name(before['run_id'])}"
                / "task_id=dbt_marts" / f"attempt={try_number}.log")
    assert log_file.exists(), f"{log_file} is not on the host"
