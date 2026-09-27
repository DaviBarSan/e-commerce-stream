"""E2E-2: the JSON Schema and the model agree, and event IDs are deterministic (D13)."""
import json
import typing
from importlib.resources import files

import pytest

from telemetry import EventValidationError, derive_event_id, parse_event, validate_payload
from telemetry.schema import EVENT_MODELS, EventType, json_schema

EXAMPLES = files("telemetry").joinpath("schemas/examples")
INVALID = sorted(EXAMPLES.joinpath("invalid").iterdir(), key=lambda p: p.name)


@pytest.mark.parametrize("path", INVALID, ids=[p.name for p in INVALID])
def test_invalid_examples_are_rejected_by_schema_and_model(path):
    raw = path.read_bytes()
    with pytest.raises(EventValidationError):
        validate_payload(raw)
    with pytest.raises(EventValidationError):
        parse_event(raw)


def test_model_and_schema_declare_the_same_types_and_required_fields():
    schema = json_schema()
    model_types = {typing.get_args(m.model_fields["event_type"].annotation)[0] for m in EVENT_MODELS}
    assert model_types == set(schema["properties"]["event_type"]["enum"]) == set(typing.get_args(EventType))
    for model in EVENT_MODELS:
        required = {name for name, field in model.model_fields.items() if field.is_required()}
        rule = next(r["then"] for r in schema["allOf"]
                    if r["if"]["properties"]["event_type"]["const"] == typing.get_args(
                        model.model_fields["event_type"].annotation)[0])
        assert required == set(schema["required"]) | set(rule.get("required", [])), model.__name__


def test_event_id_is_deterministic():
    first = derive_event_id("idem-123", "add_to_cart")
    assert derive_event_id("idem-123", "add_to_cart") == first  # retried request -> same id
    assert derive_event_id("idem-124", "add_to_cart") != first  # another action
    assert derive_event_id("idem-123", "purchase") != first     # same action, other event
    assert first.version == 5
    with pytest.raises(ValueError):
        derive_event_id("", "add_to_cart")


def test_additive_fields_stay_valid():
    payload = json.loads(EXAMPLES.joinpath("valid/add_to_cart.json").read_text())
    payload["context"] = {"utm": {"source": "promo"}}
    payload["new_top_level_field"] = "from a newer v1 producer"
    payload["properties"]["gift_wrap"] = True
    validate_payload(payload)
    event = parse_event(payload)
    assert event.model_extra == {"new_top_level_field": "from a newer v1 producer"}
