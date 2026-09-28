"""Sink interface for the raw table (D11); the backend is chosen by WAREHOUSE_BACKEND."""
from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ingest_consumer.settings import Settings

# Raw table columns in order (D11, spec 05 §5).
COLUMNS = (
    "event_id", "schema_version", "event_type", "event_ts", "produced_at", "ingested_at",
    "session_id", "user_id", "anonymous_id", "product_id", "cart_id", "order_id",
    "source_topic", "source_partition", "source_offset", "payload",
)
RAW_TABLE = "clickstream_events"


@dataclass(frozen=True)
class RawRow:
    event_id: str
    schema_version: str
    event_type: str
    event_ts: datetime
    produced_at: datetime
    ingested_at: datetime
    session_id: str
    user_id: str
    anonymous_id: str | None
    product_id: str | None
    cart_id: str | None
    order_id: str | None
    source_topic: str
    source_partition: int
    source_offset: int
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, ingested_at: datetime, topic: str, partition: int,
                     offset: int) -> RawRow:
        """Build a row from a payload that already passed validate_payload."""
        return cls(
            event_id=payload["event_id"],
            schema_version=payload["schema_version"],
            event_type=payload["event_type"],
            event_ts=datetime.fromisoformat(payload["event_ts"]),
            produced_at=datetime.fromisoformat(payload["produced_at"]),
            ingested_at=ingested_at,
            session_id=payload["session_id"],
            user_id=payload["user_id"],
            anonymous_id=payload.get("anonymous_id"),
            product_id=payload.get("product_id"),
            cart_id=payload.get("cart_id"),
            order_id=payload.get("order_id"),
            source_topic=topic,
            source_partition=partition,
            source_offset=offset,
            payload=payload,
        )


class EventSink(ABC):
    @abstractmethod
    def write(self, rows: list[RawRow]) -> int:
        """Insert a batch in one transaction; return how many rows were new (duplicates are skipped)."""

    @abstractmethod
    def close(self) -> None:
        """Release resources."""


class NotProvisionedError(RuntimeError):
    """The selected warehouse backend isn't available yet."""


_SINKS = {"postgres": "ingest_consumer.sinks.postgres"}


def get_sink(settings: Settings) -> EventSink:
    """The sink for WAREHOUSE_BACKEND; only its module (and SDK) is imported."""
    if settings.warehouse_backend == "bigquery":
        raise NotProvisionedError("WAREHOUSE_BACKEND=bigquery is not provisioned until Phase 8 (PLAN.md T8.4)")
    if settings.warehouse_backend not in _SINKS:
        raise RuntimeError(f"WAREHOUSE_BACKEND={settings.warehouse_backend!r} is not one of {sorted(_SINKS)}")
    return importlib.import_module(_SINKS[settings.warehouse_backend]).create_sink(settings)
