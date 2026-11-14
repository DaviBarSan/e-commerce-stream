"""Outbox relay (D15, spec 02 §6.1): publishes state-change events from store.outbox_events at least once.

Each cycle is one transaction: lock a batch (FOR UPDATE SKIP LOCKED, so several API replicas can share the
work), publish it, flush, and delete the rows only if the broker acknowledged every one. Otherwise the
transaction rolls back and the rows are retried next cycle; the duplicates a retry can cause are dropped by
the raw table's primary key (D11).
"""
import asyncio
import json
import logging
import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from store_backend.models import OutboxEvent
from telemetry import EventProducer

log = logging.getLogger("store_backend.outbox")

FLUSH_TIMEOUT_SECONDS = 10.0


class OutboxRelay:
    def __init__(self, sessions: sessionmaker[Session], producer: EventProducer, batch_size: int,
                 poll_seconds: float) -> None:
        self._sessions = sessions
        self._producer = producer
        self._batch_size = batch_size
        self._poll_seconds = poll_seconds
        self._stopping = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="outbox-relay")

    async def stop(self) -> None:
        """Let the current cycle finish (it runs in a worker thread), then stop."""
        self._stopping.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                published = await asyncio.to_thread(self.cycle)
            except Exception:  # a database hiccup must not kill the relay; the rows are still there
                log.exception("outbox: cycle failed")
                published = 0
            if published < self._batch_size:  # a full batch means more rows are waiting: re-poll at once
                try:
                    await asyncio.wait_for(self._stopping.wait(), self._poll_seconds)
                except TimeoutError:
                    pass

    def cycle(self) -> int:
        """Publish one batch in one transaction. Returns how many rows were published and deleted."""
        began = time.monotonic()
        with self._sessions() as db:
            rows = db.execute(
                select(OutboxEvent.seq, OutboxEvent.payload)
                .order_by(OutboxEvent.seq).limit(self._batch_size).with_for_update(skip_locked=True)
            ).all()
            if not rows:
                return 0

            # Stats are process-wide, so a direct (browsing) failure during the cycle also forces a retry:
            # that only costs duplicates, which the raw table absorbs.
            before = self._producer.stats()
            for row in rows:
                self._producer.send_payload(row.payload.encode("utf-8"))
            pending = self._producer.flush(FLUSH_TIMEOUT_SECONDS)
            after = self._producer.stats()
            delivered = pending == 0 and after.failed == before.failed and after.dropped == before.dropped

            if delivered:
                db.execute(delete(OutboxEvent).where(OutboxEvent.seq.in_([row.seq for row in rows])))
                db.commit()
            else:
                db.rollback()
            pending_after = db.scalar(select(func.count()).select_from(OutboxEvent))
            db.commit()

        log.info(json.dumps({
            "event": "outbox_cycle",
            "published": len(rows) if delivered else 0,
            "attempted": len(rows),
            "pending_after": pending_after,
            "cycle_ms": round((time.monotonic() - began) * 1000),
            "outcome": "committed" if delivered else "rolled_back",
        }))
        return len(rows) if delivered else 0
