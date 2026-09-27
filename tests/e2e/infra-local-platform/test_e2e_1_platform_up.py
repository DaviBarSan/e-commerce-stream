"""E2E-1: the platform comes up and can be reached from the host and the Docker network."""
import urllib.request

import pytest
from confluent_kafka.admin import AdminClient

from e2e_support import LOCAL_PLATFORM as STACK, REPO_ROOT, make, pg_connect, project_prefix, run, versions


@pytest.fixture(scope="module")
def platform():
    # Start clean: these flows destroy 10-platform, which must never happen under a live 20-resources.
    make("down")
    STACK.init()
    STACK.apply()
    return STACK.outputs()


def test_terraform_fmt_and_validate_are_clean():
    run(["terraform", "fmt", "-check", "-recursive", "terraform"], cwd=REPO_ROOT, check=True)
    STACK.init()
    STACK.tf("validate")


def test_every_container_is_healthy(platform):
    prefix = project_prefix()
    expected = {f"{prefix}kafka", f"{prefix}kafka-ui", f"{prefix}postgres"}
    for name in expected:
        status = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", name], check=True).stdout.strip()
        assert status == "healthy", f"{name}: {status}"


def test_kafka_reachable_from_host(platform):
    admin = AdminClient({"bootstrap.servers": platform["kafka_bootstrap_host"]})
    metadata = admin.list_topics(timeout=15)
    brokers = [f"{b.host}:{b.port}" for b in metadata.brokers.values()]
    assert brokers == [platform["kafka_bootstrap_host"]], brokers


def test_kafka_reachable_from_network(platform):
    result = run(
        ["docker", "run", "--rm", "--network", platform["network_name"], versions()["KAFKA_IMAGE"],
         "/opt/kafka/bin/kafka-broker-api-versions.sh", "--bootstrap-server", platform["kafka_bootstrap_internal"]],
        timeout=180, check=True,
    )
    assert platform["kafka_bootstrap_internal"] in result.stdout, result.stdout


def test_kafka_ui_responds(platform):
    with urllib.request.urlopen(platform["kafka_ui_url"], timeout=15) as resp:
        assert resp.status == 200


def test_postgres_select_1(platform):
    with pg_connect(platform) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
