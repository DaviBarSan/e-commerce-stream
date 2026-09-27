"""HTTP routers (spec 02 §6)."""
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session
