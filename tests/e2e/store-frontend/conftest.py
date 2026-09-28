"""Shared fixtures: the store API and the Reflex storefront on the host, and a headless browser."""
import pytest
from playwright.sync_api import sync_playwright

from e2e_support import ApiServer, ReflexServer, local_env, seed_store


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    env = local_env()
    seed_store(env)
    logs = tmp_path_factory.mktemp("storefront")
    api = ApiServer(env, logs / "api.log").start()
    ui = ReflexServer(env, logs / "reflex.log", backend_url=api.url).start()
    yield {"env": env, "api": api, "ui": ui}
    ui.stop()
    api.stop()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()
