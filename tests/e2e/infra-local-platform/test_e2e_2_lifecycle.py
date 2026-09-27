"""E2E-2: lifecycle (idempotent apply, clean destroy, keep_data reuses the volume)."""
from e2e_support import LOCAL_PLATFORM as STACK, docker_names, pg_connect, project_prefix, run, tf_env


def test_reapply_plans_no_changes():
    STACK.init()
    STACK.apply()
    assert STACK.plan_exit_code() == 0, "second plan is not empty"


def test_destroy_leaves_nothing():
    STACK.destroy()
    prefix = project_prefix()
    for kind in ("container", "network", "volume"):
        assert docker_names(kind, prefix) == [], f"leftover {kind}s"


def test_keep_data_volume_survives_destroy():
    keep = tf_env(keep_data=True)
    volume = f"{project_prefix()}pgdata"
    try:
        STACK.apply(env=keep)
        with pg_connect(STACK.outputs(env=keep)) as conn:
            conn.execute("CREATE TABLE e2e_marker (v text)")
            conn.execute("INSERT INTO e2e_marker VALUES ('kept')")

        STACK.destroy(env=keep)
        assert docker_names("container", project_prefix()) == []
        assert volume in docker_names("volume", volume), "volume was removed despite keep_data"

        # New state -> new password; the reused data directory must accept it.
        STACK.apply(env=keep)
        with pg_connect(STACK.outputs(env=keep)) as conn:
            assert conn.execute("SELECT v FROM e2e_marker").fetchone() == ("kept",)
    finally:
        STACK.destroy(env=keep)
        run(["docker", "volume", "rm", "-f", volume])
    assert docker_names("volume", volume) == []
