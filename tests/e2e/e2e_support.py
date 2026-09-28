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


def wait_container_healthy(container, timeout=180):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", container]).stdout.strip()
        if status == "healthy":
            return
        time.sleep(2)
    raise AssertionError(f"{container} not healthy after {timeout}s")


# --- store API on the host (store-api; containers come with store-deploy) ------------------

class ApiServer:
    """Runs `uvicorn store_backend.main:app` on the host with the contract env, logging to a file."""

    def __init__(self, env, log_path, port=8000):
        self.env = {**os.environ, **env}
        self.log_path = Path(log_path)
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.proc = None

    def start(self, timeout=60):
        import sys
        import time

        import httpx

        self._log = open(self.log_path, "ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "store_backend.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO_ROOT, env=self.env, stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"API exited early:\n{self.log_path.read_text(errors='replace')}")
            try:
                if httpx.get(f"{self.url}/health", timeout=2).status_code == 200:
                    return self
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        raise AssertionError(f"API not healthy after {timeout}s:\n{self.log_path.read_text(errors='replace')}")

    def stop(self, timeout=30):
        """Graceful stop (lifespan shutdown flushes the producer); kill if it doesn't exit."""
        import signal

        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(10)
        self._log.close()

    def log(self):
        return self.log_path.read_text(errors="replace")


def seed_store(env):
    import sys

    return run([sys.executable, "-m", "store_backend.seed"], env={**os.environ, **env}, check=True)


# --- ingest consumer on the host (ingest-consumer; containers come with ingest-deploy) --------

class ConsumerProcess:
    """Runs `python -m ingest_consumer` on the host with the contract env (plus overrides), logging to a file."""

    def __init__(self, env, log_path, **overrides):
        self.env = {**os.environ, **env, **{k: str(v) for k, v in overrides.items()}}
        self.log_path = Path(log_path)
        self.proc = None

    def start(self):
        import sys

        self._log = open(self.log_path, "ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen([sys.executable, "-m", "ingest_consumer"], cwd=REPO_ROOT, env=self.env,
                                     stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags)
        # Ready once it logs "start": the sink has created the raw table by then.
        started_before = len(self.log_records("start"))

        def ready():
            if not self.running():
                raise AssertionError(f"consumer exited early:\n{self.log_path.read_text(errors='replace')}")
            return len(self.log_records("start")) > started_before

        wait_for(ready, 60, interval=0.2, message="the consumer to start")
        return self

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout=60):
        """Graceful stop: the consumer flushes, commits and exits. Returns the exit code."""
        import signal

        if self.running():
            self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        self._log.close()
        return self.proc.returncode

    def kill(self):
        """Hard kill: no flush, no commit."""
        self.proc.kill()
        self.proc.wait(10)
        self._log.close()

    def log_records(self, event=None):
        """The consumer's JSON log lines (optionally only one event type)."""
        records = []
        for line in self.log_path.read_text(errors="replace").splitlines():
            start = line.find("{")
            if start >= 0:
                try:
                    record = json.loads(line[start:])
                except ValueError:
                    continue
                if event is None or record.get("event") == event:
                    records.append(record)
        return records


def start_group_at_end(env, group_id):
    """Commit a new consumer group's offsets at the topic's current end, so a test's consumer skips the history."""
    from confluent_kafka import Consumer, TopicPartition

    topic = env["EVENTS_TOPIC"]
    ends = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], topic)
    consumer = Consumer({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "group.id": group_id,
                         "enable.auto.commit": False})
    try:
        consumer.commit(offsets=[TopicPartition(topic, p, o) for p, o in ends.items()], asynchronous=False)
    finally:
        consumer.close()
    return group_id


def raw_rows(env, event_ids, columns="*", dsn_key="WAREHOUSE_DSN"):
    """Rows of the raw table for the given event_ids, as dicts."""
    import psycopg
    from psycopg.rows import dict_row

    table = f'{env["WAREHOUSE_RAW_SCHEMA"]}.clickstream_events'
    with psycopg.connect(env[dsn_key], row_factory=dict_row, connect_timeout=10) as conn:
        return conn.execute(f"SELECT {columns} FROM {table} WHERE event_id = ANY(%s::uuid[])",
                            ([str(i) for i in event_ids],)).fetchall()


def wait_for(predicate, timeout, interval=0.5, message="condition"):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {message}")


def produce_raw(bootstrap, topic, messages):
    """Produce raw (key, value) messages; return their (partition, offset) in order."""
    from confluent_kafka import Producer

    delivered = [None] * len(messages)

    def on_delivery(index):
        return lambda err, msg: delivered.__setitem__(index, None if err else (msg.partition(), msg.offset()))

    producer = Producer({"bootstrap.servers": bootstrap, "acks": "all"})
    for index, (key, value) in enumerate(messages):
        producer.produce(topic, key=key, value=value, on_delivery=on_delivery(index))
    assert producer.flush(30) == 0 and all(delivered), "raw produce failed"
    return delivered


def session_events(bootstrap, topic, start_offsets, session_id, until=None, timeout=60):
    """Event payloads of one session, in order, read from start_offsets until until(events) is true (or timeout).

    Without `until`, it reads until the topic is quiet for a few seconds.
    """
    import time

    from confluent_kafka import Consumer, TopicPartition

    events = []
    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "e2e-session-reader",
                         "enable.auto.commit": False})
    try:
        consumer.assign([TopicPartition(topic, p, o) for p, o in start_offsets.items()])
        deadline, last_seen = time.monotonic() + timeout, time.monotonic()
        while time.monotonic() < deadline:
            if until is not None and until(events):
                break
            if until is None and time.monotonic() - last_seen > 5:
                break
            msg = consumer.poll(0.5)
            if msg is None or msg.error():
                continue
            try:
                payload = json.loads(msg.value())
            except (ValueError, AttributeError):
                continue
            if isinstance(payload, dict) and payload.get("session_id") == session_id:
                events.append(payload)
                last_seen = time.monotonic()
    finally:
        consumer.close()
    return events


# --- storefront on the host (store-frontend; containers come with store-deploy) -------------

class ReflexServer:
    """Runs the Reflex storefront in production mode (UI and Reflex backend on one port)."""

    def __init__(self, env, log_path, backend_url, port=3000):
        self.env = {**os.environ, **env, "BACKEND_URL": backend_url, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        self.log_path = Path(log_path)
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.proc = None

    def start(self, timeout=600):
        """Builds the frontend on first run, which can take a few minutes."""
        import sys
        import time

        import httpx

        self._log = open(self.log_path, "ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "reflex", "run", "--env", "prod",
             "--frontend-port", str(self.port), "--backend-port", str(self.port)],
            cwd=REPO_ROOT / "services" / "store_frontend", env=self.env,
            stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"Reflex exited early:\n{self.log_path.read_text(errors='replace')[-4000:]}")
            try:
                if (httpx.get(f"{self.url}/ping", timeout=2).status_code == 200
                        and httpx.get(self.url, timeout=5).status_code == 200):
                    return self
            except httpx.TransportError:
                pass
            time.sleep(1)
        raise AssertionError(f"Reflex not up after {timeout}s:\n{self.log_path.read_text(errors='replace')[-4000:]}")

    def stop(self):
        """Stop the whole process tree (Reflex starts a web server and a bun process)."""
        if self.proc is None or self.proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
        else:
            self.proc.terminate()
        self.proc.wait(30)
        self._log.close()
