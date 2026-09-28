"""E2E-1: a purchase clicked through the storefront creates the order and exactly the journey-1 events."""
import re

import psycopg
import pytest
from playwright.sync_api import expect

from e2e_support import session_events, topic_end_offsets

JOURNEY = [  # (event_type, properties.page or None, page_url pattern)
    ("page_view", "home", r"^/$"),
    ("search", None, r"^/search\?q=lamp$"),
    ("product_view", None, r"^/products/p-\d{4}$"),
    ("add_to_cart", None, r"^/products/p-\d{4}$"),
    ("page_view", "cart", r"^/cart$"),
    ("checkout_start", None, r"^/cart$"),
    ("purchase", None, r"^/checkout$"),
]


@pytest.fixture(scope="module")
def purchase(stack, browser):
    env, ui = stack["env"], stack["ui"]
    start = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"])
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(30_000)

    page.goto(ui.url + "/")
    expect(page.locator(".product-link").first).to_be_visible()
    expect(page.locator("#session-id")).not_to_be_empty()
    session_id, user_id = page.locator("#session-id").inner_text(), page.locator("#user-id").inner_text()

    page.fill("#search-input", "lamp")
    page.click("#search-button")
    expect(page).to_have_url(re.compile(r"/search\?q=lamp$"))
    expect(page.locator(".product-link").first).to_be_visible()

    page.locator(".product-link").first.click()
    expect(page.locator("#product-name")).to_be_visible()
    product_id = page.url.rstrip("/").rsplit("/", 1)[-1]

    page.click("#add-to-cart")
    expect(page.locator("#notice")).to_contain_text("Added to cart")

    page.click("#cart-link")
    expect(page.locator("#cart-total")).to_be_visible()
    page.click("#checkout")
    expect(page).to_have_url(re.compile(r"/checkout$"))

    page.fill("#checkout-name", "Ada Lovelace")
    page.fill("#checkout-email", "ada@example.com")
    page.fill("#checkout-address", "1 Analytical Engine Way")
    page.click("#place-order")
    expect(page).to_have_url(re.compile(r"/checkout/confirmation$"))
    expect(page.locator("#order-id")).not_to_be_empty()
    order_id = page.locator("#order-id").inner_text()
    context.close()

    events = session_events(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"], start, session_id,
                            until=lambda evs: any(e["event_type"] == "purchase" for e in evs))
    return {"env": env, "session_id": session_id, "user_id": user_id, "product_id": product_id,
            "order_id": order_id, "events": events}


def test_the_order_exists_and_the_cart_is_converted(purchase):
    with psycopg.connect(purchase["env"]["STORE_DB_DSN"], connect_timeout=10) as conn:
        row = conn.execute(
            "SELECT o.user_id, c.status, c.session_id FROM orders o JOIN carts c USING (cart_id) "
            "WHERE o.order_id = %s", (purchase["order_id"],)).fetchone()
    assert row == (purchase["user_id"], "converted", purchase["session_id"])


def test_kafka_has_exactly_the_journey_events(purchase):
    events = purchase["events"]
    assert [(e["event_type"], e["properties"].get("page")) for e in events] == [
        (t, page) for t, page, _ in JOURNEY], [e["event_type"] for e in events]
    for event, (_, _, url_pattern) in zip(events, JOURNEY):
        assert re.match(url_pattern, event["page_url"]), (event["event_type"], event["page_url"])
    assert {e["user_id"] for e in events} == {purchase["user_id"]}
    assert events[2]["product_id"] == events[3]["product_id"] == purchase["product_id"]
    assert events[-1]["order_id"] == purchase["order_id"]


def test_identity_was_created_in_the_browser(purchase):
    assert purchase["session_id"].startswith("s-") and purchase["user_id"].startswith("anon-")
