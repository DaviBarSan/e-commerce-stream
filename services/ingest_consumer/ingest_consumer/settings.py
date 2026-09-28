"""Settings: contract keys (spec 01 §4.2) plus consumer tuning with defaults (spec 05 §10)."""
import os
from collections.abc import Mapping
from dataclasses import dataclass


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is not set (see the environment contract, spec 01 §4.2)")
    return value


@dataclass(frozen=True)
class Settings:
    bootstrap_servers: str
    events_topic: str
    dlq_topic: str
    warehouse_backend: str
    warehouse_dsn: str
    raw_schema: str
    batch_size: int = 500
    flush_seconds: float = 5.0
    group_id: str = "clickstream-ingest"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            bootstrap_servers=_require(env, "KAFKA_BOOTSTRAP_SERVERS"),
            events_topic=_require(env, "EVENTS_TOPIC"),
            dlq_topic=_require(env, "EVENTS_DLQ_TOPIC"),
            warehouse_backend=_require(env, "WAREHOUSE_BACKEND"),
            warehouse_dsn=_require(env, "WAREHOUSE_DSN"),
            raw_schema=_require(env, "WAREHOUSE_RAW_SCHEMA"),
            batch_size=int(env.get("INGEST_BATCH_SIZE") or 500),
            flush_seconds=float(env.get("INGEST_FLUSH_SECONDS") or 5.0),
            group_id=env.get("INGEST_GROUP_ID") or "clickstream-ingest",
        )
