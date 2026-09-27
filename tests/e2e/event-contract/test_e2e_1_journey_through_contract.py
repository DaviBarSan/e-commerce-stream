"""E2E-1: a journey-1 session travels through the contract (build -> wire bytes -> schema -> parse)."""
import json
import typing
from datetime import datetime, timedelta, timezone
from importlib.resources import files

import pytest

from telemetry import build_event, parse_event, serialize_event, validate_payload
from telemetry.schema import EventType

EXAMPLES = files("telemetry").joinpath("schemas/examples")
T0 = datetime(2026, 9, 27, 14, 0, 0, 123456, tzinfo=timezone.utc)
SESSION = {"user_id": "anon-3f9a", "session_id": "s-journey-1"}
EUR = lambda amount: {"amount_minor": amount, "currency": "EUR"}  # noqa: E731

# page_view -> search -> product_view -> add_to_cart -> checkout_start -> purchase (spec 04 §4)
JOURNEY_1 = [
    ("page_view", {"page_url": "/", "properties": {"page": "home"}}),
    ("search", {"page_url": "/search?q=lamp", "properties": {"query": "lamp", "results_count": 3}}),
    ("product_view", {"page_url": "/products/42", "product_id": "42",
                      "properties": {"category": "lighting", "price": EUR(1999)}}),
    ("add_to_cart", {"page_url": "/products/42", "product_id": "42", "cart_id": "c-1",
                     "properties": {"quantity": 2, "unit_price": EUR(1999)}}),
    ("checkout_start", {"page_url": "/checkout", "cart_id": "c-1",
                        "properties": {"items_count": 2, "cart_total": EUR(3998)}}),
    ("purchase", {"page_url": "/checkout/confirmation", "cart_id": "c-1", "order_id": "o-1",
                  "properties": {"total": EUR(3998)}}),
]
REQUIRED_TOP_LEVEL = {  # D10
    "product_view": {"product_id"}, "add_to_cart": {"product_id", "cart_id"},
    "checkout_start": {"cart_id"}, "purchase": {"cart_id", "order_id"},
}


@pytest.fixture(scope="module")
def journey():
    return [
        build_event(event_type, idempotency_key=f"req-{step}", event_ts=T0 + timedelta(seconds=10 * step),
                    **SESSION, **fields)
        for step, (event_type, fields) in enumerate(JOURNEY_1)
    ]


def test_journey_round_trips_through_the_wire_format(journey):
    for event in journey:
        wire = serialize_event(event)
        payload = validate_payload(wire)  # consumer-side check on the exact bytes
        assert payload["event_ts"].endswith("Z") and payload["produced_at"].endswith("Z")
        assert "anonymous_id" not in payload, "unset optional fields must be omitted"
        assert parse_event(wire) == event


def test_journey_keeps_session_order_and_join_keys(journey):
    assert [e.event_type for e in journey] == [t for t, _ in JOURNEY_1]
    assert {e.session_id for e in journey} == {SESSION["session_id"]}
    assert [e.event_ts for e in journey] == sorted(e.event_ts for e in journey)
    assert len({e.event_id for e in journey}) == len(journey)
    for event in journey:
        payload = json.loads(serialize_event(event))
        missing = REQUIRED_TOP_LEVEL.get(event.event_type, set()) - payload.keys()
        assert not missing, f"{event.event_type} lacks top-level {missing}"


def test_valid_examples_pass_schema_and_model_and_cover_every_type():
    seen = set()
    for path in EXAMPLES.joinpath("valid").iterdir():
        raw = path.read_bytes()
        validate_payload(raw)
        event = parse_event(raw)
        assert json.loads(serialize_event(event)) == json.loads(raw), path.name
        seen.add(event.event_type)
    assert seen == set(typing.get_args(EventType))
