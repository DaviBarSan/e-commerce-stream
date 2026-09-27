"""Clickstream telemetry: the event contract and the cloud-agnostic producer (spec 04)."""
from __future__ import annotations

import importlib
import os
from collections.abc import Mapping

from telemetry.base import (
    DeliveryStats,
    EventProducer,
    NotProvisionedError,
    TelemetryConfigError,
    require_setting,
)
from telemetry.schema import (
    Event,
    EventType,
    EventValidationError,
    build_event,
    derive_event_id,
    parse_event,
    serialize_event,
    validate_payload,
)

# STREAMING_BACKEND -> driver module. Only the selected one is imported, so no other cloud SDK loads.
_DRIVERS = {
    "kafka": "telemetry.kafka_driver",
    "pubsub": "telemetry.gcp_driver",
    "kinesis": "telemetry.aws_driver",
}


def get_producer(env: Mapping[str, str] | None = None) -> EventProducer:
    """The EventProducer for STREAMING_BACKEND, configured from contract keys (spec 01 §4.2)."""
    env = os.environ if env is None else env
    backend = require_setting(env, "STREAMING_BACKEND")
    if backend not in _DRIVERS:
        raise TelemetryConfigError(f"STREAMING_BACKEND={backend!r} is not one of {sorted(_DRIVERS)}")
    return importlib.import_module(_DRIVERS[backend]).create_producer(env)


__all__ = [
    "DeliveryStats",
    "Event",
    "EventProducer",
    "EventType",
    "EventValidationError",
    "NotProvisionedError",
    "TelemetryConfigError",
    "build_event",
    "derive_event_id",
    "get_producer",
    "parse_event",
    "serialize_event",
    "validate_payload",
]
