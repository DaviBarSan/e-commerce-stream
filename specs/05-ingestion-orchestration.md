# Spec 05: Data Ingestion & Orchestration

> Tasks: T5.1–T5.4, T7.1–T7.3, T8.4, T8.6 (see `PLAN.md`)

## 1. Purpose
- **Ingestion:** move events from the streaming backend into raw staging in the warehouse, reliably.
- **Orchestration:** schedule and monitor the transformation and quality jobs that run after ingestion.

## 2. Scope
- **In scope:**
  - The streaming consumer (micro-batch sink)
  - Raw staging tables
  - Dead-letter routing
  - Airflow deployment and DAGs
  - Freshness checks
- **Out of scope:** the model logic itself (spec 06).

---

## Part A: Ingestion

### 3. Local architecture
```
Kafka topic clickstream.events.v1
   │  (consumer group: clickstream-ingest)
   ▼
[ Ingest Consumer (Python, confluent-kafka) ]
   ├─ valid   → micro-batch INSERT → warehouse.raw.clickstream_events
   └─ invalid → clickstream.events.dlq
```

### 4. Consumer behavior
| Aspect | Rule |
|---|---|
| Batching | Flush every `INGEST_BATCH_SIZE` messages (default 500) or every `INGEST_FLUSH_SECONDS` (default 5 s), whichever comes first |
| Commit | Auto-commit is off. Offsets are committed **only after** the database transaction commits (at least once). |
| Idempotency | The insert uses `ON CONFLICT (event_id) DO NOTHING` (D11). `stg_clickstream` in spec 06 deduplicates as well. |
| Validation | Every message is checked against the event schema (spec 04). Failures go to the DLQ, and the batch carries on. |
| Shutdown | On SIGTERM: flush, commit, close |
| Observability | Structured logs: batch size, lag, DLQ count, write latency |
| Scaling | Up to one consumer instance per partition (3 locally) |

Layout:
```
services/ingest_consumer/
  ingest_consumer/  (consumer loop, dlq.py, sources/kafka.py, sinks/postgres.py, sinks/bigquery.py later)
  pyproject.toml    (uv workspace member)
  Dockerfile
```
The sink is pluggable, chosen by `WAREHOUSE_BACKEND` (`postgres` / `bigquery`), and follows the same interface pattern as `EventProducer`.

### 5. Raw staging table (D11)
The table `raw.clickstream_events` is in the `raw` schema of the `warehouse` database, is created and written by the `ingest_writer` role, and holds the frequently used fields as columns plus the **whole original payload** (so it can be replayed):

| Column | Type (Postgres / BigQuery) | Source |
|---|---|---|
| `event_id` | `uuid` / `STRING`, **primary key** | envelope |
| `schema_version`, `event_type` | `text` / `STRING` | envelope |
| `event_ts`, `produced_at` | `timestamptz` / `TIMESTAMP` | envelope |
| `ingested_at` | `timestamptz` / `TIMESTAMP` | set by the consumer |
| `session_id`, `user_id`, `anonymous_id` | `text` / `STRING` | envelope (`anonymous_id` nullable) |
| `product_id`, `cart_id`, `order_id` | `text` / `STRING`, nullable | envelope (D10) |
| `source_topic`, `source_partition`, `source_offset` | `text`, `int`, `bigint` / `STRING`, `INT64`, `INT64` | broker metadata |
| `payload` | `jsonb` / `JSON` | the full original event |

Inserts use `ON CONFLICT (event_id) DO NOTHING`, so broker redelivery and retried requests (D13) never create a second row.

### 6. GCP ingestion (Phase 8, to be decided)
| Option | Pros | Cons |
|---|---|---|
| A: the same consumer on Cloud Run, pulling from a Pub/Sub subscription | Same code as local | You run and pay for a service that's always on |
| B: Pub/Sub → BigQuery subscription (native) | No code, serverless | Differs from the local path, and the table schema is fixed by the subscription |

---

## Part B: Orchestration

### 7. Airflow deployment (local)
| Aspect | Choice |
|---|---|
| Provisioning | Terraform `modules/local/airflow` (docker provider), in the `30-services` stack (D16) |
| Image | Custom image built by Terraform from `services/airflow/Dockerfile`: `FROM` the pinned `AIRFLOW_IMAGE` (Airflow 3), plus dbt in its own virtualenv and the dbt project baked in (D17) |
| Executor | LocalExecutor |
| Metadata DB | The `airflow` database on the shared Postgres (spec 01) |
| Containers | `airflow-init` (one-shot `airflow db migrate`), `api-server` (UI and REST API) on port 8080, `scheduler`, `dag-processor` |
| Auth | Simple auth manager with one `admin` user; the password is `AIRFLOW_ADMIN_PASSWORD` from the contract |
| DAGs | `dags/` bind-mounted into the containers |
| dbt execution | **`BashOperator` running `/opt/dbt-venv/bin/dbt` inside the Airflow containers (D17).** The project is at `/opt/dbt` in the image, with its packages installed at build time; each run writes its artifacts to a per-run target path, never into the image's project folder. |

Portability rule: only core operators (Bash and Python). **No Composer- or MWAA-specific hooks, and no `DockerOperator`** (D17).

### 8. DAGs
| DAG | Schedule | Tasks |
|---|---|---|
| `clickstream_transform` | `TRANSFORM_SCHEDULE` (default `@hourly`; `none` for manual only) | `check_raw_freshness` → `dbt_seed` → `dbt_staging` → `dbt_intermediate` → `dbt_marts` (one `dbt build` per layer, with its tests) → `publish_run_summary`. Each run's dbt artifacts land in the host's `airflow-runs/` (F05.4). |
| `clickstream_maintenance` (optional) | Daily | Check DLQ volume, check raw retention and vacuum |

Freshness rule: `check_raw_freshness` runs `dbt source freshness` on `raw.clickstream_events` (`loaded_at_field: ingested_at`) and fails if there have been no new raw rows for longer than `RAW_FRESHNESS_MINUTES` (default 30). When it fails, `dbt_build` doesn't run. Using dbt's own freshness check keeps the rule identical on BigQuery.

### 9. GCP orchestration (Phase 8, to be decided)
Cloud Composer (managed, costly) or self-hosted Airflow (Cloud Run or a VM). The DAG code must stay the same whichever is chosen.

## 10. Configuration
| Env var | Purpose |
|---|---|
| `STREAMING_BACKEND`, `KAFKA_BOOTSTRAP_SERVERS`, `EVENTS_TOPIC`, `EVENTS_DLQ_TOPIC` | Source |
| `WAREHOUSE_BACKEND`, `WAREHOUSE_DSN` / `WAREHOUSE_DATASET` | Sink |
| `INGEST_BATCH_SIZE`, `INGEST_FLUSH_SECONDS`, `INGEST_GROUP_ID` | Consumer tuning |
| `RAW_FRESHNESS_MINUTES` | DAG freshness check |
| `TRANSFORM_SCHEDULE` | Cron or preset for `clickstream_transform` (default `@hourly`) |
| `AIRFLOW_API_URL`, `AIRFLOW_ADMIN_PASSWORD` | Host access to the Airflow REST API (contract keys, spec 01 §4.2) |

## 11. Acceptance criteria
1. With the bot running, raw rows increase continuously, and consumer lag stays under 1 batch interval in steady state.
2. Killing the consumer in the middle of a batch and restarting it loses no events (duplicates are allowed).
3. A malformed message lands in the DLQ, and ingestion carries on.
4. The Airflow UI is reachable on `:8080`, and `clickstream_transform` runs green on schedule.
5. End to end (T7.3): events from bot actions show up in the marts within one DAG cycle.

## 12. Open items
- The GCP ingestion option (A or B) and the GCP orchestration host.

`BashOperator` or `DockerOperator` for dbt is settled by D17.

## 13. Features
| Feature | Tasks | Doc |
|---|---|---|
| F05.1 `ingest-consumer` | T5.1, T5.2, T5.4 | `features/05-ingestion-orchestration/feature-ingest-consumer` |
| F05.2 `ingest-deploy` | T5.3 | `features/05-ingestion-orchestration/feature-ingest-deploy` |
| F05.3 `airflow-local` | T7.1 | `features/05-ingestion-orchestration/feature-airflow-local` |
| F05.4 `airflow-transform-dag` | T7.2 | `features/05-ingestion-orchestration/feature-airflow-transform-dag` |
| F05.5 `local-e2e` | T7.3 | `features/05-ingestion-orchestration/feature-local-e2e` |
| F05.6 GCP ingestion | T8.4 | Phase 8, not written yet |
