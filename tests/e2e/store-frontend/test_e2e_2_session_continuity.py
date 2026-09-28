"""E2E-2: a reload keeps the cart and identity and adds no event; a returning visitor keeps user_id only."""
import pytest
from playwright.sync_api import expect

from e2e_support import session_events, topic_end_offsets


@pytest.fixture(scope="module")
def visit(stack, browser):
    env, ui = stack["env"], stack["ui"]
    start = topic_end_offsets(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"])
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(30_000)

    page.goto(ui.url + "/products/p-0001")
    expect(page.locator("#product-name")).to_be_visible()
    expect(page.locator("#session-id")).not_to_be_empty()
    before = page.locator("#session-id").inner_text(), page.locator("#user-id").inner_text()

    page.click("#add-to-cart")
    expect(page.locator("#notice")).to_contain_text("Added to cart")
    page.reload()
    expect(page.locator("#product-name")).to_be_visible()
    expect(page.locator("#session-id")).not_to_be_empty()
    after_reload = page.locator("#session-id").inner_text(), page.locator("#user-id").inner_text()

    page.click("#cart-link")
    expect(page.locator("#cart-total")).to_be_visible()
    cart_lines = page.locator(".cart-line").all_inner_texts()
    storage = context.storage_state()  # localStorage survives; sessionStorage (the session) doesn't
    context.close()

    returning = browser.new_context(storage_state=storage)
    page = returning.new_page()
    page.goto(ui.url + "/")
    expect(page.locator("#session-id")).not_to_be_empty()
    next_visit = page.locator("#session-id").inner_text(), page.locator("#user-id").inner_text()
    returning.close()

    events = session_events(env["KAFKA_BOOTSTRAP_SERVERS"], env["EVENTS_TOPIC"], start, before[0])
    return {"before": before, "after_reload": after_reload, "cart_lines": cart_lines, "next_visit": next_visit,
            "events": events}


def test_reload_keeps_identity_and_cart(visit):
    assert visit["after_reload"] == visit["before"]
    assert len(visit["cart_lines"]) == 1 and "p-0001" in visit["cart_lines"][0]


def test_each_click_is_one_event_and_the_reload_adds_none(visit):
    types = [e["event_type"] for e in visit["events"]]
    # product page, add to cart, product page again after the reload, cart
    assert types == ["product_view", "add_to_cart", "product_view", "page_view"], types
    assert len({e["event_id"] for e in visit["events"]}) == len(types)


def test_a_returning_visitor_keeps_user_id_but_gets_a_new_session(visit):
    session_before, user_before = visit["before"]
    session_next, user_next = visit["next_visit"]
    assert user_next == user_before
    assert session_next != session_before
