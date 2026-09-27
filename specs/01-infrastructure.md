# Spec 01: Base Infrastructure & Cloud Components

> Tasks: T0.*, T1.*, T3.6, T4.3, T5.3, T7.1, T8.1–T8.2, T8.6 (see `PLAN.md`)

## 1. Purpose
Provision every environment (local, GCP and later AWS) **only through Terraform**. Every environment exposes the same contract, so the application layers never change when the environment does.

## 2. Scope
- **In scope:** the Terraform module and stack layout, the local Docker platform (network, Kafka, Postgres, and later the app, bot, consumer and Airflow containers), GCP resources (Phase 8), the AWS placeholder, the environment contract, the Makefile, and state management.
- **Out of scope:** application code, dbt models and DAG logic (specs 02–06).

## 3. Repository layout
```
terraform/
  modules/
    local/
      network/       docker network
      kafka/         apache/kafka (KRaft) + kafka-ui
      postgres/      postgres + volume
      app/           backend + frontend containers      (Phase 3)
      bot/           traffic bot container               (Phase 4)
      consumer/      ingestion consumer container        (Phase 5)
      airflow/       airflow webserver/scheduler         (Phase 7)
    gcp/
      pubsub/  bigquery/  gcs/  artifact_registry/  iam/  cloud_run/   (Phase 8)
    aws/
      variables.tf  outputs.tf                           (standby placeholder)
  envs/
    local/
      10-platform/   containers, network, volumes         (local state)
      20-resources/  kafka topics, pg databases/schemas/roles (local state)
    gcp/             single stack                         (GCS backend)
    aws/             placeholder
scripts/
  smoke/             produce/consume + db round-trip checks
Makefile
versions.env         pinned tool/image versions
```

### Why local has two stacks
The `Mongey/kafka` and `cyrilgdn/postgresql` providers connect to live servers when Terraform configures them. Those servers are containers that the same Terraform run would create, and a provider can't reliably be configured against a resource created in the same apply. So:
- **`10-platform`** creates the containers, network and volumes, and outputs their host endpoints.
- **`20-resources`** reads those outputs through a `terraform_remote_state` data source on the local backend, then creates the topics, databases, schemas and roles.

`make up ENV=local` applies both in order, and `make down` destroys them in reverse order.

## 4. Environment contract

### 4.1 Inputs (identical variables in every env stack)
| Variable | Type | Example | Notes |
|---|---|---|---|
| `project_name` | string | `clickstream` | Prefix for every resource name |
| `environment` | string | `local` / `gcp` / `aws` | |
| `topics` | map(object) | `{ events = { partitions = 3, retention_hours = 168 }, events_dlq = {...} }` | Logical topic names; each backend maps them to its own native resource |
| `warehouse_raw_schema` | string | `raw` | |
| `labels` | map(string) | `{ owner = "davi" }` | Applied wherever the backend supports labels |

### 4.2 Outputs (identical keys in every env stack, written to `.env.<env>`)
| Key | Local value | GCP value |
|---|---|---|
| `STREAMING_BACKEND` | `kafka` | `pubsub` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` (host) / `kafka:19092` (in-network) | none |
| `GCP_PROJECT_ID` | none | project ID |
| `EVENTS_TOPIC` | `clickstream.events.v1` | Pub/Sub topic ID |
| `EVENTS_DLQ_TOPIC` | `clickstream.events.dlq` | Pub/Sub topic ID |
| `WAREHOUSE_BACKEND` | `postgres` | `bigquery` |
| `WAREHOUSE_DSN` / `WAREHOUSE_DATASET` | Postgres DSN for `warehouse` | BigQuery dataset |
| `WAREHOUSE_RAW_SCHEMA` | `raw` (from the `warehouse_raw_schema` input) | raw dataset name |
| `STORE_DB_DSN` | Postgres DSN for `store` (role `store_app`) | Cloud SQL (to be decided) |
| `DBT_WAREHOUSE_DSN` | Postgres DSN for `warehouse` (role `dbt_runner`) | empty (dbt uses its BigQuery profile) |
| `AIRFLOW_DB_DSN` | Postgres DSN for `airflow` (role `airflow`) | to be decided with GCP orchestration |

`WAREHOUSE_DSN` is the ingestion sink's DSN (role `ingest_writer`). Each role gets its own key, so every service only receives the credentials it needs. A key that doesn't apply to an environment is still written, with an empty value.

Values used inside containers (network hostnames) are passed to the containers directly through Terraform. The `.env` file holds the values to use from the host.

## 5. Local platform (Phase 1)

| Component | Image | Host port | Network alias | Notes |
|---|---|---|---|---|
| Kafka | `apache/kafka:<pinned>` | 9092 | `kafka:19092` | KRaft combined broker and controller, one node. Two listeners: `EXTERNAL://localhost:9092` for the host and `INTERNAL://kafka:19092` for the Docker network. Replication factor 1. |
| Kafka UI | `provectuslabs/kafka-ui:<pinned>` | 8085 | `kafka-ui` | Lets you watch topics during development |
| Postgres | `postgres:<pinned>` | 5432 | `postgres` | Named volume `pgdata`. Databases: `store`, `warehouse`, `airflow` |

Ports for later phases:

| Service | Host port |
|---|---|
| Backend | 8000 |
| Frontend (Reflex UI) | 3000 |
| Reflex backend (UI state and websocket) | 8001 |
| Airflow | 8080 |

### Resources in `20-resources`
- **Kafka topics:** `clickstream.events.v1` (3 partitions, 7-day retention) and `clickstream.events.dlq` (1 partition, 14-day retention).
- **Postgres databases and roles:**
  - `store` with role `store_app`
  - `warehouse` with schemas `raw`, `staging`, `marts` and roles `ingest_writer` and `dbt_runner`
  - `airflow` with role `airflow`
- **Credentials:** made with `random_password` and kept in local state. This is acceptable for local only.

## 6. GCP components (Phase 8, not started)
| Resource | Purpose |
|---|---|
| GCS bucket (bootstrap, created once) | Terraform state backend |
| Project services | Enable the Pub/Sub, BigQuery, Run, Artifact Registry and IAM APIs |
| Pub/Sub topic and subscription | Events, plus a dead-letter topic |
| BigQuery datasets | `raw`, `staging`, `marts` |
| GCS bucket | Landing zone and archive (optional) |
| Artifact Registry | Container images |
| Service accounts | One per workload (app, bot, consumer, dbt), with least-privilege role bindings |
| Cloud Run services and jobs | App, bot and consumer |

Free-tier guardrails:
- BigQuery dataset default table expiration in dev.
- Pub/Sub message retention kept to a minimum.
- Cloud Run `min_instances = 0`.

## 7. AWS (standby)
`modules/aws` declares the contract variables and outputs with no resources. It has to pass `terraform validate`. Target services for later: Kinesis or MSK, S3, Redshift Serverless, ECS and MWAA.

## 8. State management
| Env | Backend |
|---|---|
| local | `local` backend, with the state file in the stack directory (gitignored) |
| gcp | `gcs` backend, using the bootstrap bucket |
| aws | `s3` backend with a lock table (later) |

## 9. Makefile interface
| Target | Behavior |
|---|---|
| `make help` | Lists the targets |
| `make doctor` | Checks the Terraform (exact), Docker, `make`, `uv` and Python (minimum) versions against `versions.env` |
| `make init ENV=local` | Runs `terraform init` on every stack for that environment |
| `make plan ENV=local` | Runs `plan` on every stack |
| `make up ENV=local` | Applies `10-platform` then `20-resources`, then runs `make env` |
| `make down ENV=local` | Destroys in reverse order |
| `make env ENV=local` | Writes `.env.local` from the outputs |
| `make smoke ENV=local` | Runs `scripts/smoke` |
| `make fmt` / `make validate` | Runs `terraform fmt -recursive` / `validate` on every stack |
| `make e2e FEATURE=<id>` | Runs a feature's two E2E flows: `uv run pytest tests/e2e/<id>` |

`ENV` defaults to `local`. The Makefile runs through Git Bash on Windows.

## 10. Acceptance criteria (Phase 1)
1. On a clean machine, `make doctor && make up` works on the first try.
2. The Kafka broker can be reached from the host and from a container on the platform network.
3. The topics and databases exist exactly as described in §5.
4. `make smoke` produces and consumes one message and writes and reads one row in Postgres.
5. `make down` removes all resources. Running `make up` again is idempotent: the second apply shows no changes.
6. `terraform validate` passes for `modules/aws`.

## 11. Open items
- AWS free tier and account terms (D7).
- Store database on GCP: Cloud SQL, or reuse BigQuery for the catalog? To be decided in Phase 8.
