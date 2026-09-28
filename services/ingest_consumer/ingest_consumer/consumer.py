"""The ingest loop (spec 05 §4): validate → batch → write in one transaction → then commit offsets."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from ingest_consumer.dlq import dlq_envelope
from ingest_consumer.settings import Settings
from ingest_consumer.sinks.base import EventSink, RawRow, get_sink
from ingest_consumer.sources.kafka import KafkaDlq, KafkaSource, Message
from telemetry import EventValidationError, validate_payload

log = logging.getLogger("ingest_consumer")


class IngestConsumer:
    def __init__(self, settings: Settings, sink: EventSink | None = None) -> None:
        self._settings = settings
        self._sink = sink or get_sink(settings)
        self._dlq = KafkaDlq(settings)
        self._source = KafkaSource(settings, on_revoke=self.flush)
        self._rows: list[RawRow] = []
        self._next_offsets: dict[tuple[str, int], int] = {}  # everything read since the last commit
        self._dlq_count = 0
        self._last_flush = time.monotonic()

    def run(self, stop: threading.Event) -> None:
        log.info(json.dumps({"event": "start", "group_id": self._settings.group_id,
                             "topic": self._settings.events_topic}))
        try:
            while not stop.is_set():
                msg = self._source.poll(0.5)
                if msg is not None:
                    self._handle(msg)
                pending = len(self._next_offsets) > 0
                due = time.monotonic() - self._last_flush >= self._settings.flush_seconds
                if len(self._rows) >= self._settings.batch_size or (pending and due):
                    self.flush()
            self.flush()  # graceful shutdown: flush and commit what was read
        finally:
            self._source.close()
            self._sink.close()
            log.info(json.dumps({"event": "stop"}))

    def _handle(self, msg: Message) -> None:
        self._next_offsets[(msg.topic, msg.partition)] = msg.offset + 1
        try:
            payload = validate_payload(msg.value or b"")  # the single consumer-side check (spec 04 §9)
        except EventValidationError as exc:
            self._dlq.send(msg.key, dlq_envelope(error=str(exc), topic=msg.topic, partition=msg.partition,
                                                 offset=msg.offset, original=msg.value))
            self._dlq_count += 1
            return
        self._rows.append(RawRow.from_payload(payload, ingested_at=datetime.now(timezone.utc), topic=msg.topic,
                                              partition=msg.partition, offset=msg.offset))

    def flush(self) -> None:
        """Write the batch, make sure the DLQ has everything, and only then commit the offsets."""
        if not self._next_offsets:
            self._last_flush = time.monotonic()
            return
        began = time.monotonic()
        inserted = self._sink.write(self._rows)  # one transaction; raises -> nothing is committed
        written = time.monotonic()
        self._dlq.flush()
        self._source.commit(self._next_offsets)
        committed = time.monotonic()
        lag = self._source.lag()
        log.info(json.dumps({
            "event": "flush",
            "batch_size": len(self._rows),
            "inserted": inserted,
            "duplicates": len(self._rows) - inserted,
            "dlq_count": self._dlq_count,
            "write_ms": round((written - began) * 1000, 1),
            "commit_ms": round((committed - written) * 1000, 1),
            "lag_ms": round((time.monotonic() - committed) * 1000, 1),
            "lag": lag,
        }))
        self._rows, self._next_offsets, self._dlq_count = [], {}, 0
        self._last_flush = time.monotonic()
