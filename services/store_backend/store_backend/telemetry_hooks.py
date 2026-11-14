"""One hook per tracked action: build the contract event and publish it (spec 02 §6, spec 04).

Two delivery paths (D15, spec 04 §7):
- emit(): browsing events, published directly after the request's work. Publish failures are logged and
  counted by the producer and never fail the request; the event is lost (best effort).
- emit_in_tx(): state-change events, written to the outbox in the request's transaction, so the change and
  its event commit together. The relay (store_backend.outbox) publishes them at least once.
"""
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from store_backend.identity import get_identity
from store_backend.models import OutboxEvent
from telemetry import Event, build_event, serialize_event, validate_payload


def money(amount_minor: int, currency: str) -> dict[str, Any]:
    return {"amount_minor": amount_minor, "currency": currency}


def _event(request: Request, event_type: str, default_page_url: str, **fields: Any) -> Event:
    identity = get_identity(request)
    return build_event(
        event_type,
        idempotency_key=identity.idempotency_key,
        event_ts=datetime.now(timezone.utc),
        user_id=identity.user_id,
        session_id=identity.session_id,
        page_url=identity.page_url or default_page_url,
        **fields,
    )


def emit(request: Request, event_type: str, default_page_url: str, **fields: Any) -> None:
    request.app.state.producer.send_event(_event(request, event_type, default_page_url, **fields))


def emit_in_tx(db: Session, request: Request, event_type: str, default_page_url: str, **fields: Any) -> None:
    """Add the event to the outbox in db's transaction; the caller commits. A retried request adds nothing."""
    event = _event(request, event_type, default_page_url, **fields)
    payload = serialize_event(event)
    validate_payload(payload)  # the single producer-side check, on the exact bytes the relay will publish
    db.execute(insert(OutboxEvent).values(event_id=event.event_id, payload=payload.decode("utf-8"))
               .on_conflict_do_nothing(index_elements=[OutboxEvent.event_id]))
