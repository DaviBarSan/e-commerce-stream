"""E2E-2: lifecycle (idempotent apply, a destroy that would leave nothing, keep_data reuses the volume).

Nothing is destroyed: teardown is checked on `terraform plan -destroy`, so the flow never wipes local data.
"""
import tempfile
from pathlib import Path

from e2e_support import LOCAL_PLATFORM as STACK, docker_names, make, planned_docker_names, project_prefix, tf_env


def test_reapply_plans_no_changes():
    make("up")
    assert STACK.plan_exit_code() == 0, "second plan is not empty"


def test_a_destroy_would_leave_nothing():
    prefix = project_prefix()
    changes = STACK.destroy_plan()
    assert planned_docker_names(changes, "container") == {f"{prefix}{c}" for c in ("kafka", "kafka-ui", "postgres")}
    assert planned_docker_names(changes, "network") == set(docker_names("network", prefix))
    assert planned_docker_names(changes, "volume") == {f"{prefix}pgdata"}, "keep_data defaults to false"


def test_keep_data_leaves_the_volume_to_docker_and_reuses_it():
    """Planned from an empty scratch state, as after a destroy: no volume resource, the container mounts the existing
    volume by name, and the admin password is set with ALTER USER so a reused data directory accepts it."""
    prefix = project_prefix()
    with tempfile.TemporaryDirectory() as tmp:
        plan = STACK.plan_json(f"-state={Path(tmp) / 'scratch.tfstate'}", "-lock=false", env=tf_env(keep_data=True))
    changes = plan["resource_changes"]
    assert not [c for c in changes if c["type"] == "docker_volume"], "keep_data must not manage the volume"
    postgres = next(c["change"]["after"] for c in changes
                    if c["type"] == "docker_container" and c["change"]["after"]["name"] == f"{prefix}postgres")
    assert [m["source"] for m in postgres["mounts"]] == [f"{prefix}pgdata"]
    assert any(c["type"] == "terraform_data" and c["name"] == "admin_password" for c in changes)
