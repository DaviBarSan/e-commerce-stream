"""Kafka source (consumer with manual commits) and DLQ producer."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition

from ingest_consumer.settings import Settings

log = logging.getLogger("ingest_consumer")


@dataclass(frozen=True)
class Message:
    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None


class KafkaSource:
    def __init__(self, settings: Settings, on_revoke: Callable[[], None]) -> None:
        self._topic = settings.events_topic
        self._consumer = Consumer({
            "bootstrap.servers": settings.bootstrap_servers,
            "group.id": settings.group_id,
            "enable.auto.commit": False,  # offsets are committed only after the database commit
            "auto.offset.reset": "earliest",
            # A crashed member keeps its partitions until the session expires (default 45 s); fail over faster.
            "session.timeout.ms": 10_000,
        })
        self._on_revoke = on_revoke
        self._consumer.subscribe([self._topic], on_revoke=lambda _c, _p: self._on_revoke())

    def poll(self, timeout: float) -> Message | None:
        msg = self._consumer.poll(timeout)
        if msg is None:
            return None
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                log.warning("kafka: %s", msg.error())
            return None
        return Message(msg.topic(), msg.partition(), msg.offset(), msg.key(), msg.value())

    def commit(self, next_offsets: dict[tuple[str, int], int]) -> None:
        """Synchronously commit the next offset to read for each partition."""
        if next_offsets:
            self._consumer.commit(offsets=[TopicPartition(t, p, o) for (t, p), o in next_offsets.items()],
                                  asynchronous=False)

    def lag(self) -> int:
        """Messages behind the high watermark, from the watermarks cached by fetch responses (no broker call;
        an uncached lookup costs a round-trip per partition and slowed every flush by ~1.5 s)."""
        total = 0
        for tp in self._consumer.position(self._consumer.assignment()):
            _low, high = self._consumer.get_watermark_offsets(tp, cached=True)
            if tp.offset >= 0 and high >= 0:
                total += max(high - tp.offset, 0)
        return total

    def close(self) -> None:
        self._consumer.close()


class KafkaDlq:
    def __init__(self, settings: Settings) -> None:
        self._topic = settings.dlq_topic
        self._producer = Producer({"bootstrap.servers": settings.bootstrap_servers, "acks": "all",
                                   "enable.idempotence": True})
        self._errors: list[str] = []

    def send(self, key: bytes | None, value: bytes) -> None:
        self._producer.produce(self._topic, key=key, value=value, on_delivery=self._on_delivery)
        self._producer.poll(0)

    def _on_delivery(self, err, _msg) -> None:
        if err is not None:
            self._errors.append(str(err))

    def flush(self, timeout: float = 30.0) -> None:
        """Block until every DLQ message is acknowledged; raise so offsets aren't committed otherwise."""
        pending = self._producer.flush(timeout)
        if pending or self._errors:
            errors, self._errors = self._errors, []
            raise RuntimeError(f"DLQ delivery failed: {pending} pending, errors={errors}")
