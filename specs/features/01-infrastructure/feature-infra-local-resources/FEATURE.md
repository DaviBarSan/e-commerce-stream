# F01.3: Local Resources & Environment Contract

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [01](../../../01-infrastructure.md) | T1.5–T1.9 | infra-local-platform | 1 |

## 1. Goal
- Create the logical resources inside the platform: Kafka topics, Postgres databases, schemas and roles.
- Publish the **environment contract** as `.env.local`.
- Add the AWS placeholder module.
- Wire up `make up`, `make down` and `make smoke` for the whole local environment.

## 2. Scope
- **In:**
  - The root stack `envs/local/20-resources` (Mongey/kafka and cyrilgdn/postgresql providers)
  - Contract outputs and `.env.local` generation
  - `modules/aws` (variables and outputs only)
  - `scripts/smoke`
  - The Makefile `up`, `down`, `env` and `smoke` targets orchestrating both stacks
- **Out:** the raw staging table (F05.1) and application tables (F02.1).

## 3. Implementation definition
- **Remote state:** `terraform_remote_state` (local backend) reads the `10-platform` outputs. The kafka and postgresql providers are configured from them, including the Postgres host port (5433 on machines that override it).
- **Contract inputs:** `project_name`, `environment`, `labels`, `topics` and `warehouse_raw_schema` go in the committed `terraform.tfvars`. `topics` maps logical names (`events`, `events_dlq`) to partitions and retention; the stack derives the physical Kafka names.
- **Kafka topics:**
  - `clickstream.events.v1`: 3 partitions, retention 168 h
  - `clickstream.events.dlq`: 1 partition, retention 336 h
- **Postgres databases and schemas:** `store`, `warehouse` (schemas `raw`, `staging`, `marts`), `airflow`.
- **Roles and grants:**
  - `store_app`: owner of `store`
  - `ingest_writer`: owns the `raw` schema, so it can create the raw table in `raw` (the ingestion feature) and write to it. Default privileges give `dbt_runner` `SELECT` on every table `ingest_writer` creates in `raw`.
  - `dbt_runner`: `USAGE` on `raw` plus those `SELECT` grants, and owns `staging` and `marts`. It has no write access to `raw`.
  - `ingest_writer` has no access to `staging` or `marts`.
  - `airflow`: owner of `airflow`
  - Passwords come from `random_password`.
- **Contract:**
  - Outputs every key in spec 01 §4.2 (non-local keys are empty), including the per-role DSNs: `WAREHOUSE_DSN` (`ingest_writer`), `DBT_WAREHOUSE_DSN` (`dbt_runner`), `STORE_DB_DSN` (`store_app`) and `AIRFLOW_DB_DSN` (`airflow`).
  - `local_file` writes `.env.local` at the repo root with the host-facing values (file permission `0600`, gitignored).
- **Makefile:**
  - `make up` applies `10-platform` then `20-resources` (which writes `.env.local`).
  - `make env` regenerates `.env.local` with a targeted apply of the `local_file` resource.
  - `make down` destroys `20-resources` then `10-platform`. It is always a full reset: dropping the databases removes the data, so `keep_data` only applies when `10-platform` is destroyed on its own.
  - `make validate` also validates `modules/aws`.
- **`modules/aws`:** declares the contract variables and outputs, with no resources.
- **`scripts/smoke`:** a Python script run with `uv run`, reading `.env.local`:
  1. Produce and consume one message on `clickstream.events.v1`.
  2. As `ingest_writer`, insert and read a row in a temporary table in `warehouse.raw`, then drop it.
  3. Exit non-zero on any failure.

## 4. Interfaces
- **Consumes:** the F01.2 outputs.
- **Produces:**
  - `.env.local`, used by every service feature
  - The topics used by F02.1, F04.2 and F05.2
  - The databases and roles used by F02.1, F05.1, F05.3 and F06.1

## 5. E2E test flows
**E2E-1: the whole local environment comes up.**
1. Run `make down && make up ENV=local`.
2. The topics exist with the right partitions and retention.
3. The databases, schemas and roles exist, and grants are enforced: `dbt_runner` can't write to `raw`, and `ingest_writer` can't read `marts`.
4. `.env.local` contains every contract key.
5. `make smoke` exits 0.

**E2E-2: idempotency and teardown.**
1. Run `make up` a second time. Both stacks plan **no changes**.
2. Run `make down`. The resources are destroyed in reverse order, and no project containers, networks or state resources remain.
3. `terraform validate` passes for `modules/aws`.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=infra-local-resources`. Phase 1 acceptance (spec 01 §10) is met.

## 7. Open items
- AWS free tier and account terms (parking lot, D7).
