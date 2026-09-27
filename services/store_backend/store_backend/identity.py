"""Request identity headers (spec 02 §6): session, user, idempotency key and page URL."""
import uuid
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

SESSION_HEADER = "X-Session-Id"
USER_HEADER = "X-User-Id"
IDEMPOTENCY_HEADER = "Idempotency-Key"
PAGE_URL_HEADER = "X-Page-Url"


@dataclass(frozen=True)
class Identity:
    session_id: str
    user_id: str
    idempotency_key: str  # one per user action; event_id is derived from it (D13)
    page_url: str | None  # the storefront page, when the client sends it


class IdentityMiddleware(BaseHTTPMiddleware):
    """Reads the identity headers, creates missing ones, and echoes them in the response."""

    async def dispatch(self, request: Request, call_next):
        headers = request.headers
        identity = Identity(
            session_id=headers.get(SESSION_HEADER) or f"s-{uuid.uuid4()}",
            user_id=headers.get(USER_HEADER) or f"anon-{uuid.uuid4()}",
            idempotency_key=headers.get(IDEMPOTENCY_HEADER) or f"gen-{uuid.uuid4()}",
            page_url=headers.get(PAGE_URL_HEADER) or None,
        )
        request.state.identity = identity
        response = await call_next(request)
        response.headers[SESSION_HEADER] = identity.session_id
        response.headers[USER_HEADER] = identity.user_id
        response.headers[IDEMPOTENCY_HEADER] = identity.idempotency_key
        return response


def get_identity(request: Request) -> Identity:
    return request.state.identity
