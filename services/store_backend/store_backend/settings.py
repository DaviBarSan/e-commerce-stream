"""Settings come only from environment contract keys (spec 01 §4.2)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    store_db_dsn: str
    outbox_batch_size: int = 500  # OUTBOX_BATCH_SIZE (spec 02 §8)
    outbox_poll_seconds: float = 1.0  # OUTBOX_POLL_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        dsn = os.environ.get("STORE_DB_DSN", "").strip()
        if not dsn:
            raise RuntimeError("STORE_DB_DSN is not set (see the environment contract, spec 01 §4.2)")
        return cls(
            store_db_dsn=dsn,
            outbox_batch_size=int(os.environ.get("OUTBOX_BATCH_SIZE") or cls.outbox_batch_size),
            outbox_poll_seconds=float(os.environ.get("OUTBOX_POLL_SECONDS") or cls.outbox_poll_seconds),
        )
