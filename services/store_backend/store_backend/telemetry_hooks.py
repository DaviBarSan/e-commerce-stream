"""One hook per tracked action: build the contract event and publish it (spec 02 §6, spec 04).

Called after the database commit, so events describe actions that happened. Publish failures are
logged and counted by the producer and never fail the request (spec 04 §7).
"""
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from store_backend.identity import get_identity
from telemetry import build_event


def money(amount_minor: int, currency: str) -> dict[str, Any]:
    return {"amount_minor": amount_minor, "currency": currency}


def emit(request: Request, event_type: str, default_page_url: str, **fields: Any) -> None:
    identity = get_identity(request)
    event = build_event(
        event_type,
        idempotency_key=identity.idempotency_key,
        event_ts=datetime.now(timezone.utc),
        user_id=identity.user_id,
        session_id=identity.session_id,
        page_url=identity.page_url or default_page_url,
        **fields,
    )
    request.app.state.producer.send_event(event)
