"""Helpers shared by every feature's E2E flows."""
import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# versions.env key -> Terraform variable (mirrors the TF_VAR_* exports in the Makefile).
TF_VAR_FROM_VERSIONS = {
    "KAFKA_IMAGE": "kafka_image",
    "KAFKA_UI_IMAGE": "kafka_ui_image",
    "POSTGRES_IMAGE": "postgres_image",
}


def run(cmd, cwd=REPO_ROOT, env=None, timeout=120, check=False):
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise AssertionError(f"{' '.join(map(str, cmd))} exited {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def versions():
    pairs = {}
    for line in (REPO_ROOT / "versions.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key] = value
    return pairs


def tf_env(**tf_vars):
    """Environment for terraform: pinned images from versions.env plus extra TF_VAR_* overrides."""
    env = dict(os.environ, TF_IN_AUTOMATION="1")
    pinned = versions()
    for key, var in TF_VAR_FROM_VERSIONS.items():
        env[f"TF_VAR_{var}"] = pinned[key]
    for var, value in tf_vars.items():
        env[f"TF_VAR_{var}"] = str(value).lower() if isinstance(value, bool) else str(value)
    return env


class Stack:
    """A Terraform root stack under terraform/envs."""

    def __init__(self, relpath):
        self.dir = REPO_ROOT / "terraform" / "envs" / relpath

    def tf(self, *args, env=None, timeout=900, check=True):
        return run(["terraform", f"-chdir={self.dir}", *args], env=env or tf_env(), timeout=timeout, check=check)

    def init(self, env=None):
        return self.tf("init", "-input=false", env=env)

    def apply(self, env=None):
        return self.tf("apply", "-input=false", "-auto-approve", env=env)

    def destroy(self, env=None):
        return self.tf("destroy", "-input=false", "-auto-approve", env=env)

    def plan_exit_code(self, env=None):
        """0 = no changes, 2 = changes pending. A plan error (exit 1) raises with Terraform's output."""
        result = self.tf("plan", "-input=false", "-no-color", "-detailed-exitcode", env=env, check=False)
        if result.returncode == 1:
            raise AssertionError(f"plan failed in {self.dir}\n{result.stdout}\n{result.stderr}")
        return result.returncode

    def outputs(self, env=None):
        raw = json.loads(self.tf("output", "-json", env=env).stdout)
        return {name: item["value"] for name, item in raw.items()}


def docker_names(kind, prefix):
    """Names of Docker containers/networks/volumes whose name starts with prefix."""
    cmd = {
        "container": ["docker", "ps", "-a", "--format", "{{.Names}}"],
        "network": ["docker", "network", "ls", "--format", "{{.Name}}"],
        "volume": ["docker", "volume", "ls", "--format", "{{.Name}}"],
    }[kind]
    out = run(cmd, check=True).stdout
    return [n for n in out.split() if n.startswith(prefix)]


LOCAL_PLATFORM = Stack("local/10-platform")


def project_prefix(stack=LOCAL_PLATFORM):
    """`<project_name>-`, read from the stack's committed terraform.tfvars."""
    tfvars = (stack.dir / "terraform.tfvars").read_text()
    return re.search(r'^project_name\s*=\s*"([^"]+)"', tfvars, re.M).group(1) + "-"


def pg_connect(platform_outputs, dbname="postgres"):
    """Connect from the host as the Postgres admin, using the 10-platform outputs."""
    import psycopg

    out = platform_outputs
    return psycopg.connect(
        host=out["postgres_host"], port=out["postgres_port"], dbname=dbname,
        user=out["postgres_admin_user"], password=out["postgres_admin_password"], connect_timeout=10,
    )


LOCAL_RESOURCES = Stack("local/20-resources")

# Environment contract keys (spec 01 §4.2), written to .env.<env> by every env.
CONTRACT_KEYS = [
    "STREAMING_BACKEND", "KAFKA_BOOTSTRAP_SERVERS", "GCP_PROJECT_ID", "EVENTS_TOPIC", "EVENTS_DLQ_TOPIC",
    "WAREHOUSE_BACKEND", "WAREHOUSE_DSN", "WAREHOUSE_DATASET", "WAREHOUSE_RAW_SCHEMA",
    "STORE_DB_DSN", "DBT_WAREHOUSE_DSN", "AIRFLOW_DB_DSN",
]


def make(*args, timeout=1200, check=True):
    """Run a Makefile target from the repo root (same entry point as a developer)."""
    return run(["make", *args], env=tf_env(), timeout=timeout, check=check)


def read_env_file(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env
