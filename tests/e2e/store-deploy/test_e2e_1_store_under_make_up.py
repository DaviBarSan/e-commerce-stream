"""E2E-1: the store runs under `make up`; the storefront reaches the API in-network and events reach Kafka."""
import uuid

import httpx
import psycopg
import pytest
from playwright.sync_api import expect, sync_playwright

from e2e_support import (LOCAL_SERVICES, Shopper, local_env, project_prefix, read_messages, run, topic_end_offsets,
                         wait_container_healthy)


@pytest.fixture(scope="module")
def store():
    env = local_env()
    outputs = LOCAL_SERVICES.outputs()
    return {"env": env, "api": outputs["store_api_url"], "web": outputs["store_web_url"]}


def container_env(name):
    out = run(["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", name], check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_the_containers_are_healthy_and_the_seed_ran(store):
    for component in ("store-api", "store-web"):
        wait_container_healthy(f"{project_prefix()}{component}", timeout=60)
    seed = run(["docker", "inspect", "-f", "{{.State.ExitCode}}", f"{project_prefix()}store-seed"], check=True)
    assert seed.stdout.strip() == "0"
    with psycopg.connect(store["env"]["STORE_DB_DSN"]) as conn:
        assert conn.execute("SELECT count(*) FROM products").fetchone()[0] > 0


def test_the_api_serves_health_and_docs(store):
    assert httpx.get(f"{store['api']}/health", timeout=10).json() == {"status": "ok"}
    assert httpx.get(f"{store['api']}/docs", timeout=10).status_code == 200


def test_the_storefront_renders_products_from_the_api_container(store):
    assert httpx.get(f"{store['web']}/ping", timeout=10).status_code == 200
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_default_timeout(30_000)
            page.goto(store["web"] + "/")
            # The products come from store-api through BACKEND_URL=http://store-api:8000 (in-network).
            expect(page.locator(".product-link").first).to_be_visible()
        finally:
            browser.close()
    assert container_env(f"{project_prefix()}store-web")["BACKEND_URL"] == "http://store-api:8000"


def test_a_purchase_against_the_containers_reaches_kafka(store):
    env = store["env"]
    api_env = container_env(f"{project_prefix()}store-api")
    assert api_env["KAFKA_BOOTSTRAP_SERVERS"] == "kafka:19092", "the API must publish in-network"

    start = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"])
    shopper = Shopper(store["api"], uuid.uuid4().hex[:8], "deploy")
    shopper.call("GET", "/home", "page_view", "home")
    shopper.add("p-0007", "add")
    shopper.checkout()
    order = shopper.purchase()
    assert order["order_id"].startswith("o-")

    messages = read_messages(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"], start, shopper.event_ids,
                             timeout=30)
    assert sorted(m["event_id"] for m in messages) == sorted(shopper.event_ids)
