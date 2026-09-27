"""EventProducer: the cloud-agnostic publishing interface (spec 04 §5, §7)."""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from telemetry.schema import Event, serialize_event, validate_payload

log = logging.getLogger("telemetry")


class TelemetryConfigError(ValueError):
    """A required setting is missing or invalid."""


class NotProvisionedError(RuntimeError):
    """The selected streaming backend isn't available yet."""


@dataclass(frozen=True)
class DeliveryStats:
    sent: int  # accepted by send_event (valid events handed to the driver)
    delivered: int  # acknowledged by the broker
    failed: int  # rejected or timed out in the transport
    dropped: int  # never enqueued (local queue full)


def require_setting(env: Mapping[str, str], key: str) -> str:
    """A contract key from the environment, or TelemetryConfigError naming it."""
    value = env.get(key, "").strip()
    if not value:
        raise TelemetryConfigError(f"{key} is not set (see the environment contract, spec 01 §4.2)")
    return value


class EventProducer(ABC):
    """Publishes contract events. Transport problems are logged and counted, never raised."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts = {"sent": 0, "delivered": 0, "failed": 0, "dropped": 0}

    def send_event(self, event: Event) -> None:
        """Validate (raises EventValidationError), serialize and publish asynchronously."""
        payload = serialize_event(event)
        validate_payload(payload)  # the single producer-side check, on the exact wire bytes
        self._record("sent")
        self._publish(event, payload)

    @abstractmethod
    def _publish(self, event: Event, payload: bytes) -> None:
        """Hand the serialized event to the transport without blocking; never raise for transport errors."""

    @abstractmethod
    def flush(self, timeout: float = 10.0) -> int:
        """Block until pending events are delivered or the timeout expires; return how many are still pending."""

    def close(self) -> None:
        """Flush, then release resources."""
        pending = self.flush()
        if pending:
            log.error("telemetry: closing with %d undelivered events", pending)
        self._close()

    def _close(self) -> None:  # noqa: B027 - optional hook
        """Release driver resources."""

    def stats(self) -> DeliveryStats:
        with self._lock:
            return DeliveryStats(**self._counts)

    def _record(self, outcome: str) -> None:
        with self._lock:
            self._counts[outcome] += 1

    def __enter__(self) -> EventProducer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
