"""E2E-2: `make up` is idempotent, `make down` removes everything, modules/aws validates."""
import re

from e2e_support import LOCAL_PLATFORM, LOCAL_RESOURCES, REPO_ROOT, docker_names, make, project_prefix, run, tf_env


def test_second_up_plans_no_changes():
    make("up")
    make("up")
    for stack in (LOCAL_PLATFORM, LOCAL_RESOURCES):
        assert stack.plan_exit_code() == 0, f"{stack.dir.name} has pending changes after a second up"


def test_down_removes_everything():
    make("down")
    prefix = project_prefix()
    for kind in ("container", "network", "volume"):
        assert docker_names(kind, prefix) == [], f"leftover {kind}s"
    for stack in (LOCAL_RESOURCES, LOCAL_PLATFORM):
        assert stack.tf("state", "list").stdout.strip() == "", f"{stack.dir.name} state is not empty"
    assert not (REPO_ROOT / ".env.local").exists(), ".env.local was not removed"


def test_aws_placeholder_validates():
    aws = REPO_ROOT / "terraform" / "modules" / "aws"
    run(["terraform", f"-chdir={aws}", "init", "-input=false", "-backend=false"], env=tf_env(), check=True)
    run(["terraform", f"-chdir={aws}", "validate"], env=tf_env(), check=True)
    source = "".join(p.read_text() for p in aws.glob("*.tf"))
    assert not re.search(r'^\s*(resource|data|provider)\s+"', source, re.M), "modules/aws must declare no resources"
