# F05.1: Ingest Consumer (Kafka → raw table, with DLQ)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [05](../../../05-ingestion-orchestration.md) | T5.1, T5.2, T5.4 | infra-local-resources, event-contract | 5 |

## 1. Goal
Move every event from `clickstream.events.v1` into the raw table `warehouse.raw.clickstream_events` (D11) at least once, without losing data across crashes and restarts, while invalid messages go to the DLQ and never stop the pipeline. This is the ingestion step of journey 1 (`PLAN.md` §9).

### What it builds
- **The raw table** `raw.clickstream_events`: the D11 columns plus the full payload, with `event_id` as the primary key.
- **A consumer service** (`python -m ingest_consumer`) that reads `clickstream.events.v1` in micro-batches (500 messages or 5 seconds, whichever comes first), writes each batch to the database in one transaction, and **only then** commits the Kafka offsets. A crash never loses an event, and the primary key absorbs the re-read (`ON CONFLICT (event_id) DO NOTHING`).
- **Validation and a dead-letter queue:** every message is checked against the v1 JSON Schema; invalid ones go to `clickstream.events.dlq` with the reason, where they came from and the original bytes, and the batch carries on.
- **A pluggable sink** chosen by `WAREHOUSE_BACKEND`: Postgres now, BigQuery in Phase 8.
- **A clean shutdown** (flush, commit, close) and one structured log line per flush: batch size, rows inserted, duplicates, DLQ count, write time and lag.

## 2. Scope
- **In:**
  - The raw table (D11), created by the consumer
  - The consumer loop: micro-batches, offsets committed only after the database commit, graceful shutdown
  - Consumer-side validation and DLQ routing (spec 04 §9)
  - The pluggable sink interface with the Postgres sink
  - Structured logs
- **Out:**
  - The Docker image and Terraform module (`ingest-deploy`, T5.3)
  - The BigQuery sink and the GCP ingestion path (Phase 8)
  - dbt models (spec 06)

## 3. Implementation definition
- **Packaging:** `services/ingest_consumer` is a uv workspace member (package `ingest_consumer`) depending on `clickstream[kafka]` and psycopg 3.
- **Layout:** `services/ingest_consumer/ingest_consumer/{__main__.py, settings.py, consumer.py, dlq.py, sources/kafka.py, sinks/base.py, sinks/postgres.py}`. Cloud SDKs are imported only in `sources/` and `sinks/` (CLAUDE.md §5): `sources/kafka.py` holds the Kafka consumer and the DLQ producer, and `dlq.py` only builds the DLQ message.
- **Raw table** `raw.clickstream_events`, created by the Postgres sink at startup with `CREATE TABLE IF NOT EXISTS`, as `ingest_writer` (owner of `raw`, so the default privileges give `dbt_runner` `SELECT`):
  - Columns exactly as D11 / spec 05 §5; `event_id uuid PRIMARY KEY`.
  - Index on `event_ts`, for incremental dbt models.
  - No migration tool: local schema changes recreate the environment, like `store-api`.
- **Sink interface** (`sinks/base.py`): `EventSink.write(rows) -> int` inserts a batch in **one transaction** and returns how many rows were new; `close()`. `get_sink(env)` picks the sink from `WAREHOUSE_BACKEND` and imports only that module (`postgres` now; `bigquery` raises a clear "not provisioned" error until Phase 8).
- **Postgres sink:** `INSERT … ON CONFLICT (event_id) DO NOTHING` for the whole batch, then commit. Columns come from the validated payload; `ingested_at` is set by the consumer; `payload` is the original event as JSON.
- **Consumer loop** (`consumer.py`, spec 05 §4):
  - confluent-kafka consumer in group `INGEST_GROUP_ID` (default `clickstream-ingest`), `enable.auto.commit=false`, `auto.offset.reset=earliest`, `session.timeout.ms=10000` (a crashed consumer's partitions are reassigned after 10 s instead of the default 45 s).
  - Each message is decoded and checked with `validate_payload` (the single consumer-side check). Valid events are added to the batch; invalid ones are sent to the DLQ.
  - The batch is flushed every `INGEST_BATCH_SIZE` messages (default 500) or `INGEST_FLUSH_SECONDS` (default 5), whichever comes first. A flush: write the batch to the sink (one transaction) → flush the DLQ producer → **then** commit the offsets of every message in the flush, synchronously.
  - If the sink write fails, nothing is committed and the consumer stops with an error; after a restart it re-reads from the last committed offsets (at least once).
  - On partition revocation, and on SIGINT / SIGTERM / SIGBREAK (Windows), it flushes, commits and closes.
- **DLQ** (`dlq.py`, spec 04 §9): a JSON message on `EVENTS_DLQ_TOPIC`, keyed by the source message key:
  `{"error": "<validation message>", "source_topic", "source_partition", "source_offset", "failed_at", "consumer": "ingest_consumer", "original_payload_b64": "<base64 of the original bytes>"}`.
  Base64 keeps payloads that aren't valid UTF-8 or JSON intact.
- **Logs:** one JSON line per flush: `batch_size`, `inserted`, `duplicates`, `dlq_count`, `write_ms`, `commit_ms`, `lag_ms`, `lag` (sum over assigned partitions, from the high watermarks cached by fetch responses, so measuring lag costs no broker call).
- **Config:** contract keys `KAFKA_BOOTSTRAP_SERVERS`, `EVENTS_TOPIC`, `EVENTS_DLQ_TOPIC`, `WAREHOUSE_BACKEND`, `WAREHOUSE_DSN`, `WAREHOUSE_RAW_SCHEMA`; consumer tuning `INGEST_BATCH_SIZE`, `INGEST_FLUSH_SECONDS`, `INGEST_GROUP_ID` (spec 05 §10, with defaults).
- **Run:** `python -m ingest_consumer`.

## 4. Interfaces
- **Consumes:** `clickstream.events.v1` (produced by `store-api` / `telemetry-producer`); the `warehouse` database, the `raw` schema and the `ingest_writer` role (`infra-local-resources`); `validate_payload` (`event-contract`).
- **Produces:**
  - `warehouse.raw.clickstream_events` (D11), read by dbt (`dbt_runner`)
  - DLQ messages on `clickstream.events.dlq`

## 5. E2E test flows
The flows run the consumer on the host as a subprocess using `.env.local`, with a unique consumer group per run. Running it in a container comes later, in `ingest-deploy`.

**E2E-1: events land in the raw table.**
1. Ensure the local environment is up; publish 300 journey-1 events over 10 sessions with the telemetry producer.
2. Start the consumer.
3. Within 30 seconds, `raw.clickstream_events` has exactly those 300 `event_id`s: every D11 column matches its payload, `source_topic` / `source_partition` / `source_offset` are set, and `ingested_at` is not earlier than `produced_at`.
4. Publishing the same 300 events again (same `event_id`s) adds no rows.
5. `dbt_runner` can read the table (default privileges), and the flush logs report the batch counts.

**E2E-2: crashes, restarts and poison messages.**
1. Publish 2,000 events and start the consumer with a small batch size; **kill it hard** (no shutdown) while it is ingesting.
2. Restart it. All 2,000 `event_id`s end up in the table exactly once: nothing is lost, and duplicates from the re-read are absorbed by the primary key.
3. Publish a mix of valid events, one message that isn't JSON, and one JSON event that breaks the schema. The valid ones land in the table; the two bad ones land in the DLQ with the error, source topic, partition and offset, and the original bytes (base64); the consumer keeps running.
4. Stop it gracefully (SIGBREAK / SIGTERM): it exits cleanly and the committed offsets cover everything it wrote (a restart reads nothing new).

## 6. Definition of done
Both flows pass through `make e2e FEATURE=ingest-consumer`, and `scripts/check_sdk_imports.py` passes.

## 7. Open items
None.
