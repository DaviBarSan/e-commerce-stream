"""E2E-1: the whole local environment comes up through `make up` and exposes the contract."""
import psycopg
import pytest
from confluent_kafka.admin import AdminClient, ConfigResource
from psycopg import errors

from e2e_support import CONTRACT_KEYS, LOCAL_PLATFORM, REPO_ROOT, make, pg_connect, read_env_file

EXPECTED_TOPICS = {  # name -> (partitions, retention hours), spec 01 §5
    "clickstream.events.v1": (3, 168),
    "clickstream.events.dlq": (1, 336),
}


@pytest.fixture(scope="module")
def env():
    make("down")
    make("up")
    return read_env_file(REPO_ROOT / ".env.local")


def test_env_file_has_every_contract_key(env):
    assert sorted(env) == sorted(CONTRACT_KEYS)
    assert env["STREAMING_BACKEND"] == "kafka" and env["WAREHOUSE_BACKEND"] == "postgres"
    for key in ["KAFKA_BOOTSTRAP_SERVERS", "EVENTS_TOPIC", "EVENTS_DLQ_TOPIC", "WAREHOUSE_DSN",
                "WAREHOUSE_RAW_SCHEMA", "STORE_DB_DSN", "DBT_WAREHOUSE_DSN", "AIRFLOW_DB_DSN"]:
        assert env[key], f"{key} is empty"


def test_topics_have_configured_partitions_and_retention(env):
    admin = AdminClient({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"]})
    topics = admin.list_topics(timeout=15).topics
    for name, (partitions, hours) in EXPECTED_TOPICS.items():
        assert name in topics, f"missing topic {name}"
        assert len(topics[name].partitions) == partitions, name
        config = admin.describe_configs([ConfigResource("topic", name)])
        retention = next(iter(config.values())).result()["retention.ms"].value
        assert int(retention) == hours * 3600 * 1000, name


def test_databases_schemas_and_roles_exist(env):
    admin = LOCAL_PLATFORM.outputs()
    with pg_connect(admin) as conn:
        dbs = {r[0] for r in conn.execute("SELECT datname FROM pg_database")}
        roles = {r[0] for r in conn.execute("SELECT rolname FROM pg_roles")}
    assert {"store", "warehouse", "airflow"} <= dbs
    assert {"store_app", "ingest_writer", "dbt_runner", "airflow"} <= roles
    with pg_connect(admin, dbname="warehouse") as conn:
        schemas = dict(conn.execute(
            "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname IN ('raw','staging','marts')"
        ).fetchall())
    assert schemas == {"raw": "ingest_writer", "staging": "dbt_runner", "marts": "dbt_runner"}


def test_role_dsns_connect_to_their_databases(env):
    for key, db in [("STORE_DB_DSN", "store"), ("AIRFLOW_DB_DSN", "airflow"),
                    ("WAREHOUSE_DSN", "warehouse"), ("DBT_WAREHOUSE_DSN", "warehouse")]:
        with psycopg.connect(env[key], connect_timeout=10) as conn:
            assert conn.execute("SELECT current_database()").fetchone() == (db,), key


def test_grants_are_enforced(env):
    raw = env["WAREHOUSE_RAW_SCHEMA"]
    ingest = psycopg.connect(env["WAREHOUSE_DSN"], autocommit=True)
    dbt = psycopg.connect(env["DBT_WAREHOUSE_DSN"], autocommit=True)
    try:
        ingest.execute(f"CREATE TABLE {raw}.e2e_grants (v int)")
        ingest.execute(f"INSERT INTO {raw}.e2e_grants VALUES (1)")
        dbt.execute("CREATE TABLE marts.e2e_grants (v int)")

        # dbt_runner reads raw (default privileges) but can't write it.
        assert dbt.execute(f"SELECT v FROM {raw}.e2e_grants").fetchall() == [(1,)]
        with pytest.raises(errors.InsufficientPrivilege):
            dbt.execute(f"INSERT INTO {raw}.e2e_grants VALUES (2)")
        # ingest_writer can't read marts.
        with pytest.raises(errors.InsufficientPrivilege):
            ingest.execute("SELECT * FROM marts.e2e_grants")
    finally:
        ingest.execute(f"DROP TABLE IF EXISTS {raw}.e2e_grants")
        dbt.execute("DROP TABLE IF EXISTS marts.e2e_grants")
        ingest.close()
        dbt.close()


def test_make_smoke_passes(env):
    result = make("smoke")
    assert "smoke: ok" in result.stdout, result.stdout
