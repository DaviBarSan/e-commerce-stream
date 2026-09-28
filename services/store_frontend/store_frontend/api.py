"""Store API client: identity headers on every call, one Idempotency-Key per user action (D13)."""
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Identity:
    session_id: str
    user_id: str
    page_url: str  # the storefront route the action happened on


class ApiError(Exception):
    """The store API answered with an error (404 / 409 / ...); shown to the user, not retried."""


def backend_url() -> str:
    url = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError("BACKEND_URL is not set (spec 02 §8): the store API base URL, e.g. http://127.0.0.1:8000")
    return url


def call(method: str, path: str, identity: Identity, **kwargs: Any) -> Any:
    """One user action = one Idempotency-Key. A transport failure is retried once with the same key."""
    headers = {
        "X-Session-Id": identity.session_id,
        "X-User-Id": identity.user_id,
        "X-Page-Url": identity.page_url,
        "Idempotency-Key": f"ui-{uuid.uuid4()}",
    }
    url = backend_url() + path
    for attempt in (1, 2):
        try:
            response = httpx.request(method, url, headers=headers, timeout=10, **kwargs)
            break
        except httpx.TransportError:
            if attempt == 2:
                raise
    if response.is_error:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith(
            "application/json") else response.text
        raise ApiError(f"{response.status_code}: {detail}")
    return response.json()


def price(amount_minor: int, currency: str | None) -> str:
    return f"{amount_minor / 100:.2f} {currency or ''}".strip()
