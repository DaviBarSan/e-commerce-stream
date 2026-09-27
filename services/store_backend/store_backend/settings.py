"""Settings come only from environment contract keys (spec 01 §4.2)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    store_db_dsn: str

    @classmethod
    def from_env(cls) -> "Settings":
        dsn = os.environ.get("STORE_DB_DSN", "").strip()
        if not dsn:
            raise RuntimeError("STORE_DB_DSN is not set (see the environment contract, spec 01 §4.2)")
        return cls(store_db_dsn=dsn)
