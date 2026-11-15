"""E2E-2: `make up` is idempotent, `make down` would remove everything, modules/aws validates.

`make down` itself is never run: the destroy plans of the three stacks are checked instead, so the flow never wipes
local data.
"""
import re

from e2e_support import LOCAL_STACKS, REPO_ROOT, docker_names, make, planned_docker_names, project_prefix, run, tf_env


def test_second_up_plans_no_changes():
    make("up")
    make("up")
    for stack in LOCAL_STACKS:
        assert stack.plan_exit_code() == 0, f"{stack.dir.name} has pending changes after a second up"


def test_down_would_remove_everything():
    prefix = project_prefix()
    plans = {stack.dir.name: stack.destroy_plan() for stack in LOCAL_STACKS}
    every = [change for changes in plans.values() for change in changes]
    for kind in ("container", "network", "volume"):  # no project resource is left outside Terraform
        assert planned_docker_names(every, kind) == set(docker_names(kind, prefix)), f"{kind}s not covered"
    resources = plans["20-resources"]
    databases = {c["change"]["before"]["name"] for c in resources if c["type"] == "postgresql_database"}
    assert databases == {"store", "warehouse", "airflow"}
    assert any(c["type"] == "local_sensitive_file" for c in resources), ".env.local would not be removed"


def test_aws_placeholder_validates():
    aws = REPO_ROOT / "terraform" / "modules" / "aws"
    run(["terraform", f"-chdir={aws}", "init", "-input=false", "-backend=false"], env=tf_env(), check=True)
    run(["terraform", f"-chdir={aws}", "validate"], env=tf_env(), check=True)
    source = "".join(p.read_text() for p in aws.glob("*.tf"))
    assert not re.search(r'^\s*(resource|data|provider)\s+"', source, re.M), "modules/aws must declare no resources"
