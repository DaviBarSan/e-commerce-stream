"""E2E-2: a source change rebuilds only its image and container; a restart keeps the seeded catalog unchanged."""
import psycopg

from e2e_support import (LOCAL_PLATFORM, LOCAL_RESOURCES, LOCAL_SERVICES, REPO_ROOT, local_env, make, project_prefix,
                         read_env_file, run, wait_container_healthy)


def container_id(name):
    return run(["docker", "inspect", "-f", "{{.Id}}", name], check=True).stdout.strip()


def product_count(env):
    with psycopg.connect(env["STORE_DB_DSN"]) as conn:
        return conn.execute("SELECT count(*) FROM products").fetchone()[0]


def test_a_backend_change_replaces_only_the_api():
    local_env()
    prefix = project_prefix()
    api, web = f"{prefix}store-api", f"{prefix}store-web"
    others = [f"{prefix}{c}" for c in ("kafka", "postgres", "airflow-scheduler")]
    before = {name: container_id(name) for name in [api, web, *others]}

    probe = REPO_ROOT / "services" / "store_backend" / "store_backend" / "_e2e_rebuild_probe.py"
    probe.write_text('"""Temporary module from the store-deploy E2E-2 flow."""\n')
    try:
        assert LOCAL_PLATFORM.plan_exit_code() == 0
        assert LOCAL_RESOURCES.plan_exit_code() == 0
        assert LOCAL_SERVICES.plan_exit_code() == 2, "a backend change must rebuild the API image"
        make("up")
        after = {name: container_id(name) for name in [api, web, *others]}
        assert after[api] != before[api], "the API container kept the old image"
        assert after[web] == before[web], "the storefront was replaced by a backend change"
        assert all(after[n] == before[n] for n in others), "unrelated containers were replaced"
        wait_container_healthy(api)
    finally:
        probe.unlink(missing_ok=True)
        make("up")  # back to the committed sources
    assert LOCAL_SERVICES.plan_exit_code() == 0


def test_the_catalog_survives_a_restart_without_duplicates():
    env = local_env()
    seeded = product_count(env)
    assert seeded > 0

    # Recreate the store containers (the seed runs again) without touching the database.
    replace = [f"-replace=module.app.docker_container.{c}" for c in ("seed", "api", "web")]
    LOCAL_SERVICES.tf("apply", "-input=false", "-auto-approve", *replace)
    wait_container_healthy(f"{project_prefix()}store-api")
    assert product_count(read_env_file(REPO_ROOT / ".env.local")) == seeded, "the seed is not idempotent"
