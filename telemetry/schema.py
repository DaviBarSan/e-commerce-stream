"""Event contract v1 (spec 04 §3-§4): typed model, JSON Schema validation and wire format.

`event.v1.json` is the source of truth. The models mirror it; the event-contract E2E flows
check that both accept and reject the same payloads.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Literal, Union

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_serializer, field_validator

SCHEMA_VERSION = "1"

# Fixed namespace for deterministic event IDs (D13). Changing it changes every event_id: don't.
EVENT_ID_NAMESPACE = uuid.UUID("6f1c2a4e-8b3d-4f7a-9c5e-2d1b0a9e8f73")


class EventValidationError(ValueError):
    """An event doesn't satisfy the v1 contract."""


# --- building blocks -------------------------------------------------------------------------

Id = Annotated[str, Field(min_length=1)]


class _Model(BaseModel):
    # strict: no silent coercion ("3" is not an int); extra="allow": additive fields stay v1.
    model_config = ConfigDict(strict=True, extra="allow", frozen=True)


class Money(_Model):
    amount_minor: Annotated[int, Field(ge=0)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class _Envelope(_Model):
    schema_version: Literal["1"]
    event_id: uuid.UUID
    event_type: str
    event_ts: datetime
    produced_at: datetime
    user_id: Id
    anonymous_id: Id | None = None
    session_id: Id
    page_url: Id
    product_id: Id | None = None
    cart_id: Id | None = None
    order_id: Id | None = None
    context: dict[str, Any] | None = None

    @field_validator("event_ts", "produced_at", mode="before")
    @classmethod
    def _utc_z_on_the_wire(cls, value: Any) -> Any:
        # A "before" validator hands its result to strict *python* validation, which refuses
        # strings for datetimes, so parse the wire string here.
        if isinstance(value, str):
            if not value.endswith("Z"):
                raise ValueError("timestamps must be UTC with a 'Z' suffix")
            try:
                return datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"not an RFC 3339 timestamp: {value!r}") from exc
        return value

    @field_validator("event_ts", "produced_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamps must be timezone-aware UTC")
        return value

    @field_serializer("event_ts", "produced_at")
    def _render_utc(self, value: datetime) -> str:
        return _to_wire_ts(value)

    @field_serializer("event_id")
    def _render_uuid(self, value: uuid.UUID) -> str:
        return str(value)


# --- event types (spec 04 §4) -----------------------------------------------------------------

class PageViewProperties(_Model):
    page: Literal["home", "catalog", "cart"]


class PageView(_Envelope):
    event_type: Literal["page_view"]
    properties: PageViewProperties


class SearchProperties(_Model):
    query: str
    results_count: Annotated[int, Field(ge=0)]


class Search(_Envelope):
    event_type: Literal["search"]
    properties: SearchProperties


class ProductViewProperties(_Model):
    category: Id
    price: Money


class ProductView(_Envelope):
    event_type: Literal["product_view"]
    product_id: Id
    properties: ProductViewProperties


class AddToCartProperties(_Model):
    quantity: Annotated[int, Field(ge=1)]
    unit_price: Money


class AddToCart(_Envelope):
    event_type: Literal["add_to_cart"]
    product_id: Id
    cart_id: Id
    properties: AddToCartProperties


class RemoveFromCartProperties(_Model):
    pass


class RemoveFromCart(_Envelope):
    event_type: Literal["remove_from_cart"]
    product_id: Id
    cart_id: Id
    properties: RemoveFromCartProperties


class CheckoutStartProperties(_Model):
    items_count: Annotated[int, Field(ge=1)]
    cart_total: Money


class CheckoutStart(_Envelope):
    event_type: Literal["checkout_start"]
    cart_id: Id
    properties: CheckoutStartProperties


class PurchaseProperties(_Model):
    total: Money


class Purchase(_Envelope):
    event_type: Literal["purchase"]
    cart_id: Id
    order_id: Id
    properties: PurchaseProperties


EVENT_MODELS: tuple[type[_Envelope], ...] = (
    PageView, Search, ProductView, AddToCart, RemoveFromCart, CheckoutStart, Purchase,
)
Event = Annotated[
    Union[PageView, Search, ProductView, AddToCart, RemoveFromCart, CheckoutStart, Purchase],
    Field(discriminator="event_type"),
]
EventType = Literal[
    "page_view", "search", "product_view", "add_to_cart", "remove_from_cart", "checkout_start", "purchase",
]
_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


# --- public API -------------------------------------------------------------------------------

def derive_event_id(idempotency_key: str, event_type: str) -> uuid.UUID:
    """Deterministic event ID (D13): a retried request with the same key yields the same ID."""
    if not idempotency_key:
        raise ValueError("idempotency_key must not be empty")
    return uuid.uuid5(EVENT_ID_NAMESPACE, f"{idempotency_key}:{event_type}")


def build_event(
    event_type: str,
    *,
    idempotency_key: str,
    event_ts: datetime,
    produced_at: datetime | None = None,
    **fields: Any,
) -> Event:
    """Build a validated event, filling schema_version, event_id (D13) and produced_at.

    Goes through the same strict JSON path as parse_event, so nothing is coerced.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(derive_event_id(idempotency_key, event_type)),
        "event_type": event_type,
        "event_ts": _to_wire_ts(event_ts),
        "produced_at": _to_wire_ts(produced_at or datetime.now(timezone.utc)),
        **fields,
    }
    return parse_event(payload)


def _to_wire_ts(value: datetime) -> str:
    """RFC 3339 UTC with 'Z', using the shortest exact precision (s, ms or µs)."""
    if value.utcoffset() is None:
        raise EventValidationError("timestamps must be timezone-aware")
    us = value.microsecond
    timespec = "seconds" if us == 0 else "milliseconds" if us % 1000 == 0 else "microseconds"
    return value.astimezone(timezone.utc).isoformat(timespec=timespec).replace("+00:00", "Z")


def parse_event(data: bytes | str | dict[str, Any]) -> Event:
    """Parse a wire payload (or its decoded dict) into a typed event, strictly."""
    raw = json.dumps(data) if isinstance(data, dict) else data
    try:
        return _EVENT_ADAPTER.validate_json(raw, strict=True)
    except ValidationError as exc:
        raise EventValidationError(str(exc)) from exc


def serialize_event(event: Event) -> bytes:
    """Wire format: UTF-8 JSON, timestamps with 'Z', unset optional fields omitted."""
    return event.model_dump_json(exclude_none=True).encode("utf-8")


@lru_cache(maxsize=1)
def json_schema() -> dict[str, Any]:
    """The v1 JSON Schema (source of truth)."""
    return json.loads(files("telemetry").joinpath("schemas/event.v1.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json_schema(), format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate_payload(data: bytes | str | dict[str, Any]) -> dict[str, Any]:
    """Validate a payload against the JSON Schema (the consumer-side check). Returns the decoded dict."""
    try:
        payload = json.loads(data) if isinstance(data, (bytes, str)) else data
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:  # arbitrary bytes arrive at the consumer
        raise EventValidationError(f"not valid JSON: {exc}") from exc
    error = best_match(_validator().iter_errors(payload))
    if error is not None:
        path = "$" + "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path)
        raise EventValidationError(f"{path}: {error.message}")
    return payload
