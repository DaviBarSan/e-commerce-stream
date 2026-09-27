"""Pub/Sub driver: stub until Phase 8 (feature telemetry-pubsub). Importing it loads no SDK."""
from __future__ import annotations

from collections.abc import Mapping

from telemetry.base import EventProducer, NotProvisionedError


def create_producer(env: Mapping[str, str]) -> EventProducer:
    raise NotProvisionedError(
        "STREAMING_BACKEND=pubsub is not provisioned yet: the Pub/Sub driver arrives with the "
        "telemetry-pubsub feature in Phase 8 (PLAN.md T8.3). Use STREAMING_BACKEND=kafka locally."
    )
