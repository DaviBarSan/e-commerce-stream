"""E2E-2: reruns change nothing, an unsupported schema_version is held back with a warning, and the models
contain no dialect-specific SQL."""
import json
import re
import uuid
from datetime import datetime, timezone

from e2e_support import REPO_ROOT, dbt
from e2e_support import warehouse_query as query

DIALECT_TOKENS = [r"::", r"#>>", r"->>", r"->", r"\bjson_value\b", r"\bsafe_cast\b", r"\bjsonb\b",
                  r"\bjson_extract", r"\bilike\b"]


def build_staging():
    return dbt("build --select +staging")


def snapshot(env):
    """Row counts and the event_id fingerprint of every staging relation."""
    result = {}
    for relation in ("stg_clickstream", "stg_events__navigation", "stg_events__cart", "stg_events__checkout"):
        row = query(env, f"SELECT count(*) AS n, md5(string_agg(event_id::text, ',' ORDER BY event_id)) AS h "
                         f"FROM staging.{relation}")[0]
        result[relation] = (row["n"], row["h"])
    return result


def test_rerunning_the_build_changes_nothing(env):
    build_staging()
    before = snapshot(env)
    second = build_staging()
    assert "ERROR=0" in second.stdout
    assert snapshot(env) == before


def test_an_unsupported_schema_version_is_held_back_and_reported(env):
    import psycopg

    event_id, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    payload = {"schema_version": "2", "event_id": event_id, "event_type": "page_view", "page_url": "/",
               "user_id": "anon-e2e-v2", "session_id": "s-e2e-v2", "properties": {"page": "home"}}
    table = f'{env["WAREHOUSE_RAW_SCHEMA"]}.clickstream_events'
    # ingest_writer owns raw; the row mimics what a future v2 consumer would write.
    with psycopg.connect(env["WAREHOUSE_DSN"], connect_timeout=10) as conn:
        conn.execute(
            f"INSERT INTO {table} (event_id, schema_version, event_type, event_ts, produced_at, ingested_at, "
            "session_id, user_id, source_topic, source_partition, source_offset, payload) "
            "VALUES (%s, '2', 'page_view', %s, %s, %s, 's-e2e-v2', 'anon-e2e-v2', 'e2e', 0, 0, %s)",
            (event_id, now, now, now, json.dumps(payload)))
    try:
        build = build_staging()  # raises if the build fails: the warning must not fail it
        assert re.search(r"WARN=[1-9]", build.stdout), build.stdout
        assert "assert_raw_schema_versions_supported" in build.stdout
        assert query(env, "SELECT 1 FROM staging.stg_clickstream WHERE event_id = %s", (event_id,)) == []
    finally:
        with psycopg.connect(env["WAREHOUSE_DSN"], connect_timeout=10) as conn:
            conn.execute(f"DELETE FROM {table} WHERE event_id = %s", (event_id,))


def test_models_contain_no_dialect_specific_sql():
    offenders = []
    for path in sorted((REPO_ROOT / "dbt" / "models").rglob("*.sql")):
        text = path.read_text()
        for token in DIALECT_TOKENS:
            if re.search(token, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert offenders == [], "dialect-specific SQL outside dbt/macros/:\n" + "\n".join(offenders)
