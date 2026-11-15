"""E2E-2: an event accepted just before make stop, idempotent stop/start, and make up after a stop."""
import uuid

from e2e_support import (LOCAL_SERVICES, LOCAL_STACKS, Shopper, inspect, local_env, long_running_containers, make,
                         persisted_counts, project_containers, raw_rows, wait_for)


def container_ids():
    return {name: inspect(name, "{{.Id}}") for name in project_containers()}


def assert_all_running():
    for name in long_running_containers():
        assert inspect(name, "{{.State.Running}}") == "true", f"{name} is not running"


def test_an_event_accepted_just_before_stop_reaches_raw_once():
    env = local_env()
    shopper = Shopper(LOCAL_SERVICES.outputs()["store_api_url"], uuid.uuid4().hex[:8], "late")
    shopper.add("p-0003", "add")  # through the outbox (D15)
    make("stop")
    make("start")
    rows = wait_for(lambda: raw_rows(env, shopper.event_ids, "event_id"), 90, interval=1,
                    message="the add_to_cart event in raw")
    assert [str(r["event_id"]) for r in rows] == shopper.event_ids


def test_stop_and_start_are_idempotent():
    local_env()
    ids = container_ids()
    make("stop")
    make("stop")
    assert project_containers(running_only=True) == []
    make("start")
    make("start")
    assert_all_running()
    assert container_ids() == ids, "stop/start replaced containers"


def test_make_up_after_a_stop_brings_everything_back_with_the_data():
    env = local_env()
    names, before = project_containers(), persisted_counts(env)
    make("stop")
    make("up")
    assert_all_running()
    assert project_containers() == names, "make up left orphaned or missing containers"
    for stack in LOCAL_STACKS:
        assert stack.plan_exit_code() == 0, f"{stack.dir.name} has pending changes"
    assert persisted_counts(env) == before
