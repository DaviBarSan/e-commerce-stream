"""E2E-2: the 29/31-minute boundary fixture, a late event merging two sessions on an incremental run, and
idempotent reruns."""
import re
import uuid
from datetime import datetime, timedelta, timezone

from e2e_support import dbt, ingest_events
from e2e_support import warehouse_query as query
from telemetry import build_event


def page_view(user_id, run_id, n, event_ts):
    return build_event("page_view", idempotency_key=f"{run_id}-{n}", event_ts=event_ts, user_id=user_id,
                       session_id=f"s-{run_id}", page_url="/", properties={"page": "home"})


def session_keys(env, user_id=None, exclude_user=None):
    """{event_id: session_key} from int_sessions, for one user or everyone except one."""
    if user_id:
        rows = query(env, "SELECT event_id, session_key FROM intermediate.int_sessions WHERE user_id = %s",
                     (user_id,))
    else:
        rows = query(env, "SELECT event_id, session_key FROM intermediate.int_sessions WHERE user_id <> %s",
                     (exclude_user,))
    return {str(r["event_id"]): r["session_key"] for r in rows}


def fingerprint(env):
    """Counts and checksums of the sessionized layer and the marts, to compare reruns."""
    return {
        "int_sessions": query(env, "SELECT count(*) n, md5(string_agg(event_id::text || session_key, ',' "
                                   "ORDER BY event_id)) h FROM intermediate.int_sessions")[0],
        "fct_sessions": query(env, "SELECT count(*) n, sum(event_count) e, sum(reached_purchase) p "
                                   "FROM marts.fct_sessions")[0],
        "agg_funnel_daily": query(env, "SELECT count(*) n, sum(sessions) s FROM marts.agg_funnel_daily")[0],
    }


def test_the_session_boundary_fixture_holds(env):
    result = dbt("build --select session_gaps assert_session_boundaries_on_fixture")
    assert re.search(r"PASS=2\b", result.stdout), result.stdout
    assert "ERROR=0" in result.stdout


def test_a_late_event_merges_sessions_without_touching_other_users(env, tmp_path):
    run_id = uuid.uuid4().hex[:8]
    user = f"anon-{run_id}-late"
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)

    # 0 and 10 minutes, then a 50-minute gap: two sessions
    first = [page_view(user, run_id, n, t0 + timedelta(minutes=m)) for n, m in enumerate((0, 10, 60))]
    ingest_events(env, first, tmp_path / "first")
    dbt("build")
    before = session_keys(env, user)
    assert len(set(before.values())) == 2
    others_before = session_keys(env, exclude_user=user)

    # a late event at 35 minutes bridges the gap (25 minutes either side): one session
    late = page_view(user, run_id, 3, t0 + timedelta(minutes=35))
    ingest_events(env, [late], tmp_path / "late")
    dbt("build")  # incremental: int_sessions recomputes only this user's events
    after = session_keys(env, user)

    assert len(after) == 4 and len(set(after.values())) == 1
    assert after[str(late.event_id)] == after[str(first[0].event_id)]
    assert session_keys(env, exclude_user=user) == others_before


def test_rerunning_the_build_changes_nothing(env):
    dbt("build")
    before = fingerprint(env)
    second = dbt("build")
    assert "ERROR=0" in second.stdout
    assert fingerprint(env) == before
