"""Kafka driver (spec 04 §6-§7): at least once, keyed by session_id, never raises for transport errors."""
from __future__ import annotations

from collections.abc import Mapping
from functools import partial

from confluent_kafka import KafkaException, Producer

from telemetry.base import EventProducer, log, require_setting
from telemetry.schema import Event

# Broker outages shorter than message.timeout.ms lose nothing; longer ones count as `failed`.
PRODUCER_CONFIG = {
    "acks": "all",
    "enable.idempotence": True,
    "compression.type": "zstd",
    "linger.ms": 5,
    "message.timeout.ms": 120_000,
}


def create_producer(env: Mapping[str, str]) -> KafkaEventProducer:
    return KafkaEventProducer(
        bootstrap_servers=require_setting(env, "KAFKA_BOOTSTRAP_SERVERS"),
        topic=require_setting(env, "EVENTS_TOPIC"),
    )


class KafkaEventProducer(EventProducer):
    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        super().__init__()
        self._topic = topic
        self._producer = Producer({"bootstrap.servers": bootstrap_servers, **PRODUCER_CONFIG})

    def _publish(self, event: Event, payload: bytes) -> None:
        headers = [
            ("schema_version", event.schema_version.encode()),
            ("event_type", event.event_type.encode()),
            ("content-type", b"application/json"),
        ]
        event_id = str(event.event_id)
        for attempt in (1, 2):
            try:
                self._producer.produce(
                    self._topic,
                    key=event.session_id.encode(),
                    value=payload,
                    headers=headers,
                    on_delivery=partial(self._on_delivery, event_id),
                )
                break
            except BufferError:
                if attempt == 1:
                    self._producer.poll(0.5)  # serve callbacks to free queue space, then retry once
                    continue
                self._record("dropped")
                log.error("telemetry: local queue full, dropped event_id=%s", event_id)
                return
            except KafkaException as exc:
                self._record("failed")
                log.error("telemetry: produce failed event_id=%s: %s", event_id, exc)
                return
        self._producer.poll(0)  # serve delivery callbacks without blocking

    def _on_delivery(self, event_id: str, err, _msg) -> None:
        if err is None:
            self._record("delivered")
        else:
            self._record("failed")
            log.error("telemetry: delivery failed event_id=%s: %s", event_id, err)

    def flush(self, timeout: float = 10.0) -> int:
        return self._producer.flush(timeout)
