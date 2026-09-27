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
        args = ("plan", "-input=false", "-no-color", "-detailed-exitcode")
        result = self.tf(*args, env=env, check=False)
        if result.returncode == 1 and "broker not connected" in result.stderr:
            result = self.tf(*args, env=env, check=False)  # same one retry as the Makefile's tf()
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


def local_env():
    """Ensure the local environment is up (idempotent) and return .env.local."""
    make("up")
    return read_env_file(REPO_ROOT / ".env.local")


# --- clickstream helpers (telemetry and later features) ------------------------------------

def _eur(amount):
    return {"amount_minor": amount, "currency": "EUR"}


def _journey_1_step(step, cart_id, product_id):
    """The journey-1 steps (spec 04 §4) as (event_type, fields), repeating every 6 steps."""
    steps = [
        ("page_view", {"page_url": "/", "properties": {"page": "home"}}),
        ("search", {"page_url": "/search?q=lamp", "properties": {"query": "lamp", "results_count": 3}}),
        ("product_view", {"page_url": f"/products/{product_id}", "product_id": product_id,
                          "properties": {"category": "lighting", "price": _eur(1999)}}),
        ("add_to_cart", {"page_url": f"/products/{product_id}", "product_id": product_id, "cart_id": cart_id,
                         "properties": {"quantity": 1, "unit_price": _eur(1999)}}),
        ("checkout_start", {"page_url": "/checkout", "cart_id": cart_id,
                            "properties": {"items_count": 1, "cart_total": _eur(1999)}}),
        ("purchase", {"page_url": "/checkout/confirmation", "cart_id": cart_id, "order_id": f"o-{cart_id}",
                      "properties": {"total": _eur(1999)}}),
    ]
    return steps[step % len(steps)]


def journey_1_event(run_id, session_no, step, event_ts):
    """The step-th event of a repeating journey-1 session. Keys (and so event_ids) are unique per run."""
    from telemetry import build_event

    session_id = f"s-{run_id}-{session_no}"
    event_type, fields = _journey_1_step(step, cart_id=f"c-{run_id}-{session_no}-{step // 6}",
                                         product_id=str(100 + session_no))
    return build_event(event_type, idempotency_key=f"{session_id}-{step}", event_ts=event_ts,
                       user_id=f"anon-{run_id}-{session_no}", session_id=session_id, **fields)


def topic_end_offsets(bootstrap, topic):
    """{partition: high watermark} for every partition of a topic."""
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "e2e-watermarks"})
    try:
        partitions = consumer.list_topics(topic, timeout=15).topics[topic].partitions
        return {p: consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=15)[1] for p in partitions}
    finally:
        consumer.close()


def read_messages(bootstrap, topic, start_offsets, wanted_event_ids, timeout=60):
    """Read the topic from start_offsets until every wanted event_id is seen, or the timeout expires.

    Returns the matching messages in consumption order: event_id, key, value, headers, partition.
    """
    import time

    from confluent_kafka import Consumer, TopicPartition

    wanted, found = {str(i) for i in wanted_event_ids}, []
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "e2e-reader", "enable.auto.commit": False})
    try:
        consumer.assign([TopicPartition(topic, p, off) for p, off in start_offsets.items()])
        deadline = time.monotonic() + timeout
        while wanted - {m["event_id"] for m in found} and time.monotonic() < deadline:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                event_id = json.loads(msg.value()).get("event_id")
            except (ValueError, AttributeError):
                continue  # not an event (e.g. a smoke-test message)
            if event_id in wanted:
                found.append({"event_id": event_id, "key": msg.key(), "value": msg.value(),
                              "headers": {k: v.decode() for k, v in (msg.headers() or [])},
                              "partition": msg.partition()})
    finally:
        consumer.close()
    return found
