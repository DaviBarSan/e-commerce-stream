"""E2E-2: DAG discovery, metadata surviving a restart, idempotent applies, dbt-driven rebuilds and teardown.

Teardown is checked on the destroy plan; nothing is destroyed, so the flow never wipes local data.
"""
import uuid

import pytest

from e2e_support import (LOCAL_PLATFORM, LOCAL_RESOURCES, LOCAL_SERVICES, LOCAL_STACKS, REPO_ROOT, AirflowApi,
                         airflow_container, local_env, make, planned_docker_names, project_prefix, run,
                         wait_container_healthy, wait_for)

PROBE_DAG = '''"""Temporary DAG written by the airflow-local E2E-2 flow; it removes this file itself."""
from datetime import datetime

from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk import DAG

with DAG(dag_id="{dag_id}", schedule=None, start_date=datetime(2026, 1, 1), catchup=False):
    EmptyOperator(task_id="noop")
'''


@pytest.fixture(scope="module")
def api():
    return AirflowApi(local_env())


def container_id(name):
    return run(["docker", "inspect", "-f", "{{.Id}}", name], check=True).stdout.strip()


def image_id(name):
    return run(["docker", "image", "inspect", "-f", "{{.Id}}", name], check=True).stdout.strip()


def test_a_dag_is_discovered_and_its_state_survives_a_scheduler_restart(api):
    dag_id = f"e2e_probe_{uuid.uuid4().hex[:8]}"
    path = REPO_ROOT / "dags" / f"{dag_id}.py"
    path.write_text(PROBE_DAG.format(dag_id=dag_id))
    try:
        dag = wait_for(lambda: (r := api.request("GET", f"/dags/{dag_id}")).status_code == 200 and r.json(),
                       120, interval=3, message=f"{dag_id} to be discovered")
        assert dag["is_paused"] is True, "new DAGs must start paused"

        assert api.request("PATCH", f"/dags/{dag_id}", json={"is_paused": False}).status_code == 200
        run(["docker", "restart", airflow_container("scheduler")], check=True, timeout=120)
        wait_container_healthy(airflow_container("scheduler"))
        assert api.request("GET", f"/dags/{dag_id}").json()["is_paused"] is False, "paused state was lost"
    finally:
        path.unlink(missing_ok=True)

    def gone():
        resp = api.request("GET", f"/dags/{dag_id}")
        return resp.status_code == 404 or resp.json().get("is_stale") is True

    wait_for(gone, 120, interval=3, message=f"{dag_id} to be removed or marked stale")


def test_a_second_up_plans_no_changes():
    make("up")
    for stack in LOCAL_STACKS:
        assert stack.plan_exit_code() == 0, f"{stack.dir.name} has pending changes after a second up"


def test_a_dbt_change_rebuilds_only_airflow():
    image = f"{project_prefix()}airflow:local"
    platform = [f"{project_prefix()}{c}" for c in ("kafka", "kafka-ui", "postgres")]
    airflow = [airflow_container(c) for c in ("api-server", "scheduler", "dag-processor")]
    before = {name: container_id(name) for name in platform + airflow}
    image_before = image_id(image)

    probe = REPO_ROOT / "dbt" / "models" / "staging" / "_e2e_rebuild_probe.yml"
    probe.write_text("# Temporary file from the airflow-local E2E-2 flow.\nversion: 2\n")
    try:
        assert LOCAL_PLATFORM.plan_exit_code() == 0
        assert LOCAL_RESOURCES.plan_exit_code() == 0
        assert LOCAL_SERVICES.plan_exit_code() == 2, "a dbt change must rebuild the Airflow image"
        make("up")
        after = {name: container_id(name) for name in platform + airflow}
        assert image_id(image) != image_before, "the image was not rebuilt"
        assert all(after[n] == before[n] for n in platform), "platform containers were replaced"
        assert all(after[n] != before[n] for n in airflow), "Airflow containers kept the old image"
        for name in airflow:
            wait_container_healthy(name)
    finally:
        probe.unlink(missing_ok=True)
        make("up")  # back to the committed project


def test_down_would_remove_airflow_and_its_image():
    changes = LOCAL_SERVICES.destroy_plan()
    airflow = {airflow_container(c) for c in ("init", "api-server", "scheduler", "dag-processor")}
    assert airflow <= planned_docker_names(changes, "container"), "Airflow containers missing from the destroy plan"
    assert f"{project_prefix()}airflow:local" in planned_docker_names(changes, "image"), "the image would be kept"
