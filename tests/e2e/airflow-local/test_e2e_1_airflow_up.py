"""E2E-1: Airflow comes up under `make up`, keeps its metadata in the airflow database and can run dbt."""
import httpx
import psycopg
import pytest

from e2e_support import (CONTRACT_KEYS, LOCAL_PLATFORM, REPO_ROOT, AirflowApi, airflow_container, make, pg_connect,
                         read_env_file, run, wait_for)


@pytest.fixture(scope="module")
def env():
    make("up")  # idempotent: keeps the developer's data (E2E flows never destroy)
    return read_env_file(REPO_ROOT / ".env.local")


@pytest.fixture(scope="module")
def api(env):
    return AirflowApi(env)


def test_env_file_has_the_airflow_contract_keys(env):
    assert sorted(env) == sorted(CONTRACT_KEYS)
    assert env["AIRFLOW_API_URL"].startswith("http://127.0.0.1:"), env["AIRFLOW_API_URL"]
    assert env["AIRFLOW_ADMIN_PASSWORD"], "AIRFLOW_ADMIN_PASSWORD is empty"


def test_health_reports_every_component_healthy(api):
    components = ("metadatabase", "scheduler", "dag_processor")

    def healthy():
        health = api.health() or {}
        return all(health.get(c, {}).get("status") == "healthy" for c in components) and health

    health = wait_for(healthy, 120, interval=3, message="every Airflow component to report healthy")
    assert {c: health[c]["status"] for c in components} == dict.fromkeys(components, "healthy")


def test_the_api_requires_a_token(api):
    assert api.request("GET", "/dags").status_code == 200
    assert httpx.get(f"{api.url}/api/v2/dags", timeout=30).status_code in (401, 403)
    bad = httpx.post(f"{api.url}/auth/token", json={"username": "admin", "password": "wrong"}, timeout=30)
    assert bad.status_code == 401


def test_metadata_lives_in_the_airflow_database(env):
    with psycopg.connect(env["AIRFLOW_DB_DSN"], connect_timeout=10) as conn:
        owners = dict(conn.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE tablename IN ('alembic_version', 'dag', 'dag_run')"
        ).fetchall())
    assert owners == dict.fromkeys(["alembic_version", "dag", "dag_run"], "airflow")

    with pg_connect(LOCAL_PLATFORM.outputs(), dbname="warehouse") as conn:
        leaked = conn.execute(
            "SELECT schemaname, tablename FROM pg_tables WHERE tablename IN ('alembic_version', 'dag', 'dag_run')"
        ).fetchall()
    assert leaked == [], f"Airflow tables in the warehouse database: {leaked}"


def test_dbt_runs_inside_the_scheduler(env):
    scheduler = airflow_container("scheduler")
    debug = run(["docker", "exec", scheduler, "/opt/dbt-venv/bin/dbt", "debug"], timeout=180)
    assert debug.returncode == 0, debug.stdout + debug.stderr
    assert "All checks passed" in debug.stdout
    assert "postgres:5432" in debug.stdout or "host: postgres" in debug.stdout, debug.stdout
    assert "dbt_runner" in debug.stdout, debug.stdout

    parse = run(["docker", "exec", scheduler, "/opt/dbt-venv/bin/dbt", "parse"], timeout=300)
    assert parse.returncode == 0, parse.stdout + parse.stderr

    # D17: dbt lives in its own virtualenv, not in Airflow's Python environment.
    airflow_python = run(["docker", "exec", scheduler, "python", "-c", "import dbt.version"])
    assert airflow_python.returncode != 0, "dbt is importable from Airflow's environment"
