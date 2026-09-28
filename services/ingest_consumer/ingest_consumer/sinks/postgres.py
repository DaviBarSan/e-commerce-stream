"""Postgres sink: COPY the batch into a temp table, then INSERT … ON CONFLICT (event_id) DO NOTHING (D11)."""
from __future__ import annotations

import json

import psycopg
from psycopg import sql

from ingest_consumer.settings import Settings
from ingest_consumer.sinks.base import COLUMNS, RAW_TABLE, EventSink, RawRow

DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    event_id         uuid PRIMARY KEY,
    schema_version   text        NOT NULL,
    event_type       text        NOT NULL,
    event_ts         timestamptz NOT NULL,
    produced_at      timestamptz NOT NULL,
    ingested_at      timestamptz NOT NULL,
    session_id       text        NOT NULL,
    user_id          text        NOT NULL,
    anonymous_id     text,
    product_id       text,
    cart_id          text,
    order_id         text,
    source_topic     text        NOT NULL,
    source_partition integer     NOT NULL,
    source_offset    bigint      NOT NULL,
    payload          jsonb       NOT NULL
);
CREATE INDEX IF NOT EXISTS {index} ON {table} (event_ts);
"""


def create_sink(settings: Settings) -> PostgresSink:
    return PostgresSink(settings.warehouse_dsn, settings.raw_schema)


class PostgresSink(EventSink):
    def __init__(self, dsn: str, schema: str) -> None:
        self._table = sql.Identifier(schema, RAW_TABLE)
        self._conn = psycopg.connect(dsn, connect_timeout=10)
        cols = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
        with self._conn.transaction():
            self._conn.execute(sql.SQL(DDL).format(table=self._table,
                                                   index=sql.Identifier(f"{RAW_TABLE}_event_ts_idx")))
        # Session-local staging table, emptied at every commit.
        self._conn.execute(sql.SQL("CREATE TEMP TABLE _ingest_batch (LIKE {table}) ON COMMIT DELETE ROWS")
                           .format(table=self._table))
        self._conn.commit()
        self._copy = sql.SQL("COPY _ingest_batch ({cols}) FROM STDIN").format(cols=cols)
        self._insert = sql.SQL(
            "INSERT INTO {table} ({cols}) SELECT {cols} FROM _ingest_batch ON CONFLICT (event_id) DO NOTHING"
        ).format(table=self._table, cols=cols)

    def write(self, rows: list[RawRow]) -> int:
        if not rows:
            return 0
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                with cur.copy(self._copy) as copy:
                    for row in rows:
                        copy.write_row([json.dumps(row.payload) if c == "payload" else getattr(row, c)
                                        for c in COLUMNS])
                return cur.execute(self._insert).rowcount

    def close(self) -> None:
        self._conn.close()
