"""Kinesis driver: standby stub (D7, Phase 9). Importing it loads no SDK."""
from __future__ import annotations

from collections.abc import Mapping

from telemetry.base import EventProducer, NotProvisionedError


def create_producer(env: Mapping[str, str]) -> EventProducer:
    raise NotProvisionedError(
        "STREAMING_BACKEND=kinesis is not provisioned: AWS is on standby (D7) until Phase 9. "
        "Use STREAMING_BACKEND=kafka locally."
    )
