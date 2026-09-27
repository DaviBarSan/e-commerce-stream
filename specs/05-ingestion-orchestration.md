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
   ├─ valid   → micro-batch INSERT → warehouse.raw.<events table>
   └─ invalid → clickstream.events.dlq
```

### 4. Consumer behavior
| Aspect | Rule |
|---|---|
| Batching | Flush every `INGEST_BATCH_SIZE` messages (default 500) or every `INGEST_FLUSH_SECONDS` (default 5 s), whichever comes first |
| Commit | Auto-commit is off. Offsets are committed **only after** the database transaction commits (at least once). |
| Idempotency | The insert tolerates rows that already exist, for example `ON CONFLICT DO NOTHING` on the chosen key (depends on T5.1). `stg_clickstream` in spec 06 deduplicates as well. |
| Validation | Every message is checked against the event schema (spec 04). Failures go to the DLQ, and the batch carries on. |
| Shutdown | On SIGTERM: flush, commit, close |
| Observability | Structured logs: batch size, lag, DLQ count, write latency |
| Scaling | Up to one consumer instance per partition (3 locally) |

Layout:
```
services/ingest_consumer/
  app/  (consumer loop, sinks/postgres.py, sinks/bigquery.py later)
  tests/
  Dockerfile
```
The sink is pluggable, chosen by `WAREHOUSE_BACKEND` (`postgres` / `bigquery`), and follows the same interface pattern as `EventProducer`.

### 5. Raw staging table
**Deferred (T5.1):** the exact columns. What's already fixed:
- The table is in the `raw` schema of the `warehouse` database, and is written by the `ingest_writer` role.
- It stores the **whole original payload** so it can be replayed.
- It includes ingestion metadata (at least an ingestion timestamp).
- The design must let dbt deduplicate and parse it the same way on Postgres and BigQuery.

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
| Provisioning | Terraform `modules/local/airflow` (docker provider) |
| Executor | LocalExecutor |
| Metadata DB | The `airflow` database on the shared Postgres (spec 01) |
| Containers | `airflow-init` (one-shot DB migration and admin user), `scheduler`, `webserver` (or `api-server`, depending on the pinned version) on port 8080 |
| DAGs | `dags/` bind-mounted into the containers |
| dbt execution | `BashOperator` running `dbt`, installed in the Airflow image. The alternative is `DockerOperator` running a dbt image. To be decided in T7.1. |

Portability rule: only core operators (Bash, Python and possibly Docker). **No Composer- or MWAA-specific hooks.**

### 8. DAGs
| DAG | Schedule | Tasks |
|---|---|---|
| `clickstream_transform` | Hourly (can be changed) | `check_raw_freshness` → `dbt_build` (staging → intermediate → marts, with tests) → `publish_run_summary` |
| `clickstream_maintenance` (optional) | Daily | Check DLQ volume, check raw retention and vacuum |

Freshness rule: `check_raw_freshness` fails if there have been no new raw rows for longer than `RAW_FRESHNESS_MINUTES` (default 30) while the bot is expected to be running.

### 9. GCP orchestration (Phase 8, to be decided)
Cloud Composer (managed, costly) or self-hosted Airflow (Cloud Run or a VM). The DAG code must stay the same whichever is chosen.

## 10. Configuration
| Env var | Purpose |
|---|---|
| `STREAMING_BACKEND`, `KAFKA_BOOTSTRAP_SERVERS`, `EVENTS_TOPIC`, `EVENTS_DLQ_TOPIC` | Source |
| `WAREHOUSE_BACKEND`, `WAREHOUSE_DSN` / `WAREHOUSE_DATASET` | Sink |
| `INGEST_BATCH_SIZE`, `INGEST_FLUSH_SECONDS`, `INGEST_GROUP_ID` | Consumer tuning |
| `RAW_FRESHNESS_MINUTES` | DAG freshness check |

## 11. Acceptance criteria
1. With the bot running, raw rows increase continuously, and consumer lag stays under 1 batch interval in steady state.
2. Killing the consumer in the middle of a batch and restarting it loses no events (duplicates are allowed).
3. A malformed message lands in the DLQ, and ingestion carries on.
4. The Airflow UI is reachable on `:8080`, and `clickstream_transform` runs green on schedule.
5. End to end (T7.3): events from bot actions show up in the marts within one DAG cycle.

## 12. Open items
- The raw table columns (T5.1).
- `BashOperator` or `DockerOperator` for dbt.
- The GCP ingestion option (A or B) and the GCP orchestration host.
