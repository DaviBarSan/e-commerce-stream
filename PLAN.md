# Clickstream Pipeline: Master Plan

> **Status:** In progress. Phase 0 done (`infra-foundations`); Phase 1 done (`infra-local-platform`, `infra-local-resources`); Phase 2 done (`event-contract`, `telemetry-producer`); T3.1–T3.3 done (`store-api`); T5.1, T5.2, T5.4 done (`ingest-consumer`). ✅ marks finished tasks.
> **Supersedes:** `design_principles_revised_execution_plan.md` and `multi_cloud_architecture_mapping.md`. Those files are kept for history.
> **Specs:** each architecture layer is defined in `specs/`. This file is the task breakdown and the order the tasks run in.

---

## 1. Goal

A cloud-agnostic clickstream analytics pipeline. An e-commerce store and traffic bots produce events. The events go through a streaming broker, land raw in a warehouse, and dbt turns them into sessions, funnels and a star schema. Airflow orchestrates the jobs.

**All infrastructure is provisioned with Terraform in every environment.** Development runs locally at no cost first. GCP comes after the local stack works end to end. AWS stays in the design but on standby.

## 2. Decisions

| # | Decision |
|---|---|
| D1 | Local streaming uses the **official `apache/kafka` image** (KRaft mode, one node). |
| D2 | The cloud streaming option is **GCP Pub/Sub, native** (no Kafka shim). AWS Kinesis/MSK is on standby. |
| D3 | The local warehouse is **PostgreSQL** (Docker). The GCP warehouse is BigQuery. |
| D4 | **Terraform first:** every environment, local included, is created and destroyed with Terraform. There's no hand-written docker-compose. |
| D5 | Local is built and validated end to end **before** any GCP work. |
| D6 | Developer commands go through a **Makefile** (run with Git Bash on Windows). |
| D7 | AWS free tier and account terms are on standby until a later iteration. |
| D8 | Upstash is dropped. |
| D9 | The store app is **Reflex (frontend) + FastAPI (store backend API)**. |
| D10 | **`product_id` is a top-level event field** (v1), required for product event types. The other journey join keys, `cart_id` and `order_id`, are top-level too. Event-type details stay in the typed `properties`. Closes the parking-lot item (spec 04). |
| D11 | **Raw staging table = hot fields as columns + the full payload.** Columns: `event_id` (primary key, inserts use `ON CONFLICT DO NOTHING`), `schema_version`, `event_type`, `event_ts`, `produced_at`, `ingested_at`, `session_id`, `user_id`, `anonymous_id`, `product_id`, `cart_id`, `order_id`, `source_topic`, `source_partition`, `source_offset`, and `payload` (JSONB on Postgres, JSON on BigQuery). Closes the T5.1 decision (spec 05). |
| D12 | **Cross-database JSON: one small `json_get(column, path, type)` macro + one staging model per event type.** The macro dispatches on `target.type` (Postgres `#>>` with a cast, BigQuery `JSON_VALUE` with `SAFE_CAST`). Each event type gets a staging model that flattens its `properties` (for example `stg_events__add_to_cart`), so intermediate models and marts stay ANSI SQL. Closes the T6.2 decision (spec 06). |
| D13 | **Deterministic `event_id`:** a UUIDv5 of the request's idempotency key plus the `event_type`. The frontend sends an `Idempotency-Key` header with each user action, and the backend derives `event_id` from it, so a retried request yields the same `event_id` and is dropped by the raw table's primary key (and by `stg_clickstream`). Closes the frontend duplicate-events item (spec 02, spec 04). |

## 3. Environments

| Layer | Local (build first) | GCP (after local) | AWS (standby) |
|---|---|---|---|
| Streaming | `apache/kafka` (KRaft) | Pub/Sub | Kinesis / MSK |
| Warehouse | Postgres | BigQuery | Redshift / S3 |
| Object storage | none | GCS | S3 |
| App / bot / consumer runtime | Docker containers | Cloud Run / Cloud Run Jobs | ECS |
| Orchestration | Airflow in Docker | To be decided (Composer or self-hosted) | MWAA |
| Terraform providers | `kreuzwerker/docker`, `Mongey/kafka`, `cyrilgdn/postgresql` | `hashicorp/google` | `hashicorp/aws` |

## 4. Design principles

1. **Terraform first.** Every environment comes up with `make up ENV=<env>` and goes away with `make down ENV=<env>`.
2. **One environment contract.** Every environment stack takes the same inputs and gives the same outputs, and writes them to a `.env` file. Application code never knows which cloud it's on. See `specs/01-infrastructure.md` §4.
3. **Telemetry through interfaces.** An abstract `EventProducer` sits in front of the backend drivers, which are chosen by `STREAMING_BACKEND`. See `specs/04-clickstream.md`.
4. **One event contract.** A single versioned event schema is used by every producer and consumer.
5. **Every service in a container.** Terraform runs the images locally and deploys the same images to the cloud.
6. **SQL that works on any warehouse.** Business logic is written in ANSI SQL, and the dialect-specific parts go in dbt macros.
7. **Each phase adds its own infrastructure.** A phase adds the Terraform resources it needs; there's no big infrastructure phase at the end.

## 5. Spec index

| Spec | Layer |
|---|---|
| [`specs/01-infrastructure.md`](specs/01-infrastructure.md) | Base infrastructure and cloud components |
| [`specs/02-store-app.md`](specs/02-store-app.md) | Store app: frontend and backend |
| [`specs/03-traffic-bots.md`](specs/03-traffic-bots.md) | Traffic bots |
| [`specs/04-clickstream.md`](specs/04-clickstream.md) | Clickstream: event contract and telemetry |
| [`specs/05-ingestion-orchestration.md`](specs/05-ingestion-orchestration.md) | Data ingestion and orchestration |
| [`specs/06-transformation.md`](specs/06-transformation.md) | Data transformation (dbt) |

---

## 6. Task breakdown

How to read the tables:
- **Deps** lists the tasks that must finish first. Tasks whose dependencies are all done can run in parallel.
- **Done when** is the acceptance check a task needs to pass before it's closed.

### Phase 0: Foundations

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T0.1 ✅ | Create the repo skeleton (`terraform/`, `services/`, `telemetry/`, `dbt/`, `dags/`, `specs/`, `scripts/`) | 01 | none | The directory tree matches spec 01 §3 and spec 02–06 layouts |
| T0.2 ✅ | Pin tool versions: Terraform, Docker, Python with `uv`, `apache/kafka` tag, `postgres` tag | 01 | T0.1 | A versions file is committed, and `make doctor` reports every tool |
| T0.3 ✅ | Makefile skeleton: `doctor`, `init`, `plan`, `up`, `down`, `smoke`, `fmt`, `validate`, `env` | 01 | T0.1 | `make help` lists all targets, and `ENV` defaults to `local` |
| T0.4 ✅ | `.gitignore` for Terraform state, `.terraform/`, `.env*` and Python caches | 01 | T0.1 | `git status` is clean after a local apply |
| T0.5 ✅ | Document the Windows prerequisites (Docker Desktop, Git Bash, `make`) in the README | 01 | T0.3 | A fresh machine can follow the README to `make doctor` |

### Phase 1: Local base infrastructure

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T1.1 ✅ | `modules/local/network`: Docker network | 01 | T0.* | `terraform apply` creates the network |
| T1.2 ✅ | `modules/local/kafka`: `apache/kafka` KRaft container with internal and external listeners, plus a Kafka UI container | 01 | T1.1 | The broker can be reached from the host (`localhost:9092`) and the network (`kafka:19092`), and the UI loads on `:8085` |
| T1.3 ✅ | `modules/local/postgres`: Postgres container with a persistent volume | 01 | T1.1 | `psql` connects from the host on `:5432` |
| T1.4 ✅ | `envs/local/10-platform` root stack wiring T1.1–T1.3 | 01 | T1.1–T1.3 | `make up ENV=local` brings up the platform stack |
| T1.5 ✅ | `envs/local/20-resources`: Kafka topics (Mongey/kafka), plus Postgres databases, schemas and roles (cyrilgdn/postgresql) | 01, 04, 05 | T1.4 | The topics exist with the configured partitions and retention, and the `store`, `warehouse` and `airflow` databases exist |
| T1.6 ✅ | Environment contract outputs and `.env` generation (`local_file`) | 01 | T1.5 | `make env ENV=local` writes `.env.local` with every contract key |
| T1.7 ✅ | `modules/aws` placeholder (variables and outputs only) | 01 | T1.6 | `terraform validate` passes and no resources are declared |
| T1.8 ✅ | Smoke test: produce and consume one event, and run a round-trip query on Postgres | 01 | T1.6 | `make smoke ENV=local` exits 0 |
| T1.9 ✅ | Teardown check | 01 | T1.8 | `make down ENV=local` leaves no containers, networks or volumes (unless kept on purpose) |

### Phase 2: Clickstream contract and telemetry library

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T2.1 ✅ | Event schema v1 (JSON Schema) and Python model | 04 | T0.1 | The schema file exists, and the model round-trips valid samples and rejects invalid ones |
| T2.2 ✅ | `telemetry/base.py`: the `EventProducer` abstract base class and factory | 04 | T2.1 | Unit tests pass using an in-memory fake driver |
| T2.3 ✅ | `telemetry/kafka_driver.py` | 04 | T2.2, T1.6 | An integration test publishes to local Kafka and the event is consumed |
| T2.4 ✅ | `telemetry/gcp_driver.py` (stub that fails with a clear error until Phase 8) | 04 | T2.2 | Selecting `pubsub` raises a clear "not provisioned" error |
| T2.5 ✅ | `telemetry/aws_driver.py` (standby stub) | 04 | T2.2 | Same as T2.4 |

### Phase 3: Store app

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T3.1 ✅ | Store schema and seed data (catalog, users) in the `store` database | 02 | T1.5 | Seed script loads the products, idempotently |
| T3.2 ✅ | Backend API: catalog, search, product, cart and checkout endpoints | 02 | T3.1 | API tests pass, and the OpenAPI docs are served |
| T3.3 ✅ | Backend telemetry hooks: every user-facing action emits an event through `EventProducer` | 02, 04 | T3.2, T2.3 | Each endpoint emits the expected `event_type` to Kafka |
| T3.4 | Frontend screens: home, search, product detail, cart and checkout | 02 | T3.2 | You can complete a purchase flow manually in the browser |
| T3.5 | Dockerfiles for the backend and frontend | 02 | T3.3, T3.4 | The images build |
| T3.6 | `modules/local/app`: Terraform runs the backend and frontend containers | 01, 02 | T3.5 | After `make up`, the store opens on `:3000` and the API on `:8000` |

### Phase 4: Traffic bots

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T4.1 | Personas: casual browser, high-intent buyer, cart abandoner | 03 | T3.2 | Each persona runs its flow against the API |
| T4.2 | Traffic profiles (steady, peak hours, promo spike) set through environment variables | 03 | T4.1 | Profiles change the measured event rate as expected |
| T4.3 | Bot Docker image and `modules/local/bot` | 01, 03 | T4.2, T3.6 | `make bot` generates traffic that shows up in the Kafka UI |

### Phase 5: Ingestion

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T5.1 ✅ | Raw staging table per D11 | 05 | T2.1 | The table exists with the D11 columns, and D11 is reflected in spec 05 |
| T5.2 ✅ | Streaming consumer: Kafka to Postgres micro-batches, committing offsets only after a successful write | 05 | T5.1, T2.3 | Events show up in raw staging, with no data loss after a restart |
| T5.3 | Consumer Docker image and `modules/local/consumer` | 01, 05 | T5.2 | The consumer runs under `make up` |
| T5.4 ✅ | Dead-letter handling for invalid events | 05, 04 | T5.2 | Invalid events go to the DLQ topic, and the pipeline keeps running |

### Phase 6: Transformation

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T6.1 | dbt project and `local` profile (`dbt-postgres`) | 06 | T1.5 | `dbt debug` passes |
| T6.2 | Cross-database `json_get` macro per D12 | 06 | T6.1, T5.1 | The macro compiles on Postgres |
| T6.3 | `stg_clickstream`: parse and deduplicate on `event_id` | 06 | T6.2, T5.2 | `unique` and `not_null` tests pass |
| T6.4 | `int_sessions`: sessionization with a 30-minute inactivity window | 06 | T6.3 | The session tests pass on fixture data |
| T6.5 | Marts: `fct_events`, `fct_conversion_funnels`, `dim_users` | 06 | T6.4 | `dbt build` passes |

### Phase 7: Orchestration

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T7.1 | `modules/local/airflow`: Airflow containers (LocalExecutor, metadata in the `airflow` database) | 01, 05 | T1.5 | The Airflow UI opens on `:8080` |
| T7.2 | DAG `clickstream_transform`: freshness check, `dbt build`, then `dbt test` | 05, 06 | T7.1, T6.5 | The DAG runs green on schedule |
| T7.3 | Local end-to-end test | all | T7.2, T4.3, T5.3 | Bot traffic shows up in the marts within one DAG cycle |

### Phase 8: GCP rollout (starts after T7.3)

| ID | Task | Spec | Deps | Done when |
|---|---|---|---|---|
| T8.1 | Bootstrap the state bucket and enable the APIs | 01 | T7.3 | The GCS backend is configured |
| T8.2 | `modules/gcp/*`: Pub/Sub, BigQuery, GCS, Artifact Registry, IAM | 01 | T8.1 | `make up ENV=gcp` succeeds and `make smoke ENV=gcp` passes |
| T8.3 | Implement `gcp_driver.py` | 04 | T8.2 | Events publish to Pub/Sub |
| T8.4 | GCP ingestion path (Cloud Run consumer or BigQuery subscription, to be decided) | 05 | T8.2 | Events land in the BigQuery raw dataset |
| T8.5 | `dbt` `bigquery` target | 06 | T8.4 | `dbt build --target bigquery` passes with no model changes |
| T8.6 | Cloud Run deployment of the app and bot, and the orchestration choice | 01, 02, 03, 05 | T8.2 | The GCP end-to-end run matches the local results |

### Phase 9: AWS (standby, not scheduled)

The tasks will follow Phase 8's pattern once AWS comes back into scope (D7).

---

## 7. Critical path

`T0 → T1.1–T1.6 → T2.1–T2.3 → T3.2–T3.3 → T5.1–T5.2 → T6.3–T6.5 → T7.2 → T7.3 → Phase 8`

Tasks that can run in parallel once their dependencies are met:
- T2.1 alongside Phase 1
- T3.4 alongside T3.3
- T4.* alongside T5.*
- T6.1 and T7.1 alongside Phase 3–5 work

## 8. Parking lot (deferred decisions)

| Item | Where it will be decided | Blocks |
|---|---|---|
| AWS free tier and account terms | spec 01 | Phase 9 |
| GCP orchestration: Composer or self-hosted Airflow | spec 05 | T8.6 |
| GCP ingestion: Cloud Run consumer or BigQuery subscription | spec 05 | T8.4 |
| Stream processor technology (Bytewax / Quix Streams, Kafka Streams / ksqlDB, Flink; Dataflow on GCP) | new spec, future iteration | Journeys 3 and 9 (§9) |
| Derived-events contract and topic `clickstream.derived.v1` | spec 04, future iteration | Journeys 3 and 9 (§9) |
| Scope of journey 10: order status events vs CDC from `store` | spec 02 / 05, future iteration | Journey 10 (§9) |
| Bot ground-truth labels: `context.traffic {synthetic, persona}` in events, or a separate bot run log | spec 03 / 04, future iteration | Journeys 2–9 validation (§9) |

## 9. User journeys

The MVP delivers **journey 1** end to end: the events, API, bots, ingestion and marts in Phases 2–7. Journeys 2–10 are a **future iteration**. They are recorded here so the v1 event contract stays open to them: new event types, the `context` block and new `properties` keys are additive changes within v1 (spec 04 §8).

| # | Journey | Status | What it teaches | Needs (by layer) |
|---|---|---|---|---|
| 1 | Discovery to purchase: search → product view → add to cart → purchase | **MVP** | Ordered funnels, conversion, drop-off | Covered by Phases 2–7 |
| 2 | Search quality: zero results, reworded search, click on result #N | Future | Sequences within a session, click-through by position | Event `search_result_click {query, position}`; API passes the click's source and position; bot persona with zero-result and reworded searches; dbt click-through model |
| 3 | Cart abandonment and recovery | Future | Stateful timers, inactivity gaps, derived events | Stream processor; derived-events topic `clickstream.derived.v1` (`cart_abandoned`); bot persona that returns and recovers; batch version in dbt from `int_sessions` |
| 4 | Navigation paths | Future | Path analysis, per-key ordering | `page_view` for every page with `page_type` and `referrer_page`; API emits for home and category; less linear bot journeys; dbt path model |
| 5 | Anonymous to logged-in (identity stitching) | Future | Identity resolution, rewriting history, sessions across days | `anonymous_id` on every event; `login` / `sign_up` events and endpoints; bot persona that converts from anonymous; dbt identity map and stitched `dim_users` |
| 6 | Campaign attribution | Future | First-touch and last-touch attribution, attribution windows | `context.utm` and referrer; the API accepts them; the `promo_spike` profile tags its traffic with a campaign; dbt attribution model |
| 7 | Checkout friction | Future | Step funnel, time per step, retries, failure reasons | `checkout_step {step}`, `payment_failed {reason}`; checkout steps and simulated payment failures in the API; bot persona with planted failure rate; dbt step funnel |
| 8 | Comparison shopping | Future | Windowed aggregation per session and category | Events already sufficient; bot persona that compares; dbt comparison-set model |
| 9 | Live trends and anomalies | Future (stretch) | Window types, watermarks, late events, anomaly thresholds | Stream processor; derived-events topic; `context.traffic` bot label |
| 10 | Post-purchase (shipped, delivered, returned) | Future (out of scope for now) | Joining streams with order data, CDC | Order status events or CDC from the `store` database |

Principles for the future iteration:
- **Planted ground truth.** Each journey gets a bot persona with known parameters (for example a 30% recovery rate, or a 15% first-attempt payment failure rate). The marts must recover those numbers, and that check becomes the journey's E2E flow.
- **Additive contract.** Journey fields go into `context`, `properties` and new event types without breaking v1.

Future-iteration decisions are in the parking lot (§8).
