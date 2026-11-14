# F05.3: Airflow Local (30-services stack, Airflow containers, dbt in the image)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [05](../../../05-ingestion-orchestration.md) | T7.1 | infra-local-resources | 7 |

## 1. Goal
Run Airflow locally under `make up`, managed by Terraform, with its metadata in the `airflow` database and a dbt that can reach the warehouse from inside the containers. This is the orchestration base for the transform DAG (F05.4) and the local end-to-end run (F05.5).

### What it builds
- **The `30-services` stack** (D16): the third local stack, applied after `20-resources`. It is where every service container lives: Airflow now, then the store app (F02.3), the consumer (F05.2) and the bot (F03.2).
- **An Airflow image** built by Terraform: the pinned Airflow 3 image, plus dbt in its own virtualenv and the dbt project baked in (D17).
- **Airflow containers:** a one-shot migration, the API server (UI and REST API on `:8080`), the scheduler and the DAG processor, with the LocalExecutor.
- **Two new contract keys**, `AIRFLOW_API_URL` and `AIRFLOW_ADMIN_PASSWORD`, so tests and developers can call the Airflow API from the host.

## 2. Scope
- **In:**
  - `terraform/envs/local/30-services` (root stack) and the Makefile changes for a third stack
  - `20-resources`: a sensitive `service_credentials` output, the Airflow admin `random_password`, and the two new contract keys
  - `10-platform`: an `airflow_host_port` input and output (default 8080), next to the other host ports
  - `services/airflow/Dockerfile` and `modules/local/airflow`
  - `AIRFLOW_IMAGE` pinned in `versions.env`
  - Spec 01 and `CLAUDE.md` already describe the three stacks (D16)
- **Out:**
  - Any DAG (`clickstream_transform` is F05.4)
  - The store, consumer and bot containers (F02.3, F05.2, F03.2)
  - GCP orchestration (Phase 8, parking lot)

## 3. Implementation definition
- **Versions:** `AIRFLOW_IMAGE=apache/airflow:3.3.2-python3.12` in `versions.env` (the newest release at least two weeks old on 2026-11-14), exported to Terraform as `TF_VAR_airflow_image`. It is the only Airflow version in the repo.
- **Makefile:**
  - `STACKS` for local becomes `10-platform 20-resources 30-services`; `down` walks them in reverse.
  - `ENV_STACK` (the stack that writes `.env.<ENV>`) is set explicitly to `20-resources` for local instead of "the last stack".
  - `DBT_CORE_VERSION` and `DBT_POSTGRES_VERSION` are exported as `TF_VAR_dbt_core_version` / `TF_VAR_dbt_postgres_version`.
- **`10-platform`:** a new `airflow_host_port` variable (default 8080) and output. No resource uses it there; it keeps every host port in one place (`ports.local.auto.tfvars`).
- **`20-resources`:**
  - `random_password.airflow_admin` (alphanumeric, like the role passwords).
  - Contract keys `AIRFLOW_API_URL = http://127.0.0.1:<airflow_host_port>` and `AIRFLOW_ADMIN_PASSWORD`.
  - A sensitive output `service_credentials`: per role (`ingest_writer`, `dbt_runner`, `store_app`, `airflow`), the user, password and database, plus the Airflow admin password, the raw schema and the topic names. `30-services` builds in-network DSNs from it (`postgresql://<role>:<password>@postgres:5432/<db>`). The role-to-database map is defined once (`local.role_database`) and shared with the contract DSNs.
  - The AWS placeholder (`modules/aws`) gains the two keys, empty.
- **`30-services` stack:**
  - Local backend; providers `kreuzwerker/docker` and `random` at the pinned versions; the same contract inputs as the other stacks (`project_name`, `environment`, `labels`).
  - Two `terraform_remote_state` data sources: `10-platform` (network name) and `20-resources` (`service_credentials`, topic names).
  - Calls `modules/local/airflow`. Later features add their modules here.
- **`services/airflow/Dockerfile`** (build context: repo root):
  - `FROM ${AIRFLOW_IMAGE}`.
  - `python -m venv /opt/dbt-venv` and `pip install dbt-core==${DBT_CORE_VERSION} dbt-postgres==${DBT_POSTGRES_VERSION}` into it, so no dbt dependency lands in Airflow's environment.
  - `COPY dbt/` to `/opt/dbt` (excluding `target/`, `logs/`, `dbt_packages/` via `.dockerignore`), then `dbt deps` at build time.
  - `ENV DBT_PROJECT_DIR=/opt/dbt DBT_PROFILES_DIR=/opt/dbt DBT_SEND_ANONYMOUS_USAGE_STATS=false`, so dbt finds the project from any working directory; `PATH` unchanged (DAGs call `/opt/dbt-venv/bin/dbt` explicitly).
- **`/.dockerignore`** (repo root, the build context): an allow-list (`*`, then `!dbt/` and `!services/airflow/`) minus dbt build output, so `.env*`, `.venv` and the rest of the repo never reach an image. Later services add their own exceptions.
- **`modules/local/airflow`:**
  - `docker_image` built from `services/airflow/Dockerfile`, with a trigger on the hash of the Dockerfile, `dbt/` (sources only) and the version inputs, so a dbt change rebuilds the image.
  - Shared container environment:
    - `AIRFLOW__CORE__EXECUTOR=LocalExecutor`
    - `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` from the `airflow` role, in-network (`postgresql+psycopg2://…@postgres:5432/airflow`)
    - `AIRFLOW__CORE__LOAD_EXAMPLES=False`, `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=True`
    - The execution API URL pointing at the `api-server` container, and a shared JWT secret / Fernet key from `random_password` / `random_id` in this stack
    - Simple auth manager with one `admin` user (role `admin`). Airflow opens its passwords file read-write, so the api-server's command writes the file from `AIRFLOW_ADMIN_PASSWORD` (passed only to that container) before starting `airflow api-server`
    - `AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=10`, so new DAG files show up in seconds instead of the default 5 minutes
    - dbt settings for DAG tasks: `DBT_WAREHOUSE_DSN` (in-network, `dbt_runner`), `DBT_TARGET=local`, `WAREHOUSE_RAW_SCHEMA`, and `DBT_TARGET_PATH` / `DBT_LOG_PATH` under `/tmp/dbt` (F05.4 makes them per run)
  - Containers on the platform network:
    - `airflow-init`: runs `airflow db migrate` once (`must_run = false`, `attach = true` so the apply waits for it; a `postcondition` on `exit_code == 0` fails the apply if the migration fails).
    - `airflow-api-server` on host `airflow_host_port` → 8080, with a healthcheck on `/api/v2/monitor/health`.
    - `airflow-scheduler` (healthcheck on its built-in health server, `:8974/health`) and `airflow-dag-processor` (`airflow jobs check --job-type DagProcessorJob --local`).
  - `dags/` bind-mounted read-only at `/opt/airflow/dags` in the scheduler and DAG processor.
  - Restart policy `unless-stopped` for the three long-running containers.
- **Teardown:** `make down` destroys `30-services` first; the containers and the built image are removed. Metadata lives in the `airflow` database, so it goes with `20-resources`.

## 4. Interfaces
- **Consumes:**
  - The platform network (`10-platform`) and the `airflow` and `dbt_runner` roles (`20-resources`).
  - The dbt project in `dbt/` (F06.1, F06.2, and later F06.3), baked into the image.
- **Produces:**
  - The `30-services` stack that F02.3, F05.2 and F03.2 add their modules to.
  - The `service_credentials` output of `20-resources`.
  - Airflow on `:8080` (UI and `/api/v2`), with `/opt/dbt-venv/bin/dbt` and the project at `/opt/dbt` available to DAG tasks.
  - Contract keys `AIRFLOW_API_URL` and `AIRFLOW_ADMIN_PASSWORD` in `.env.local`.

## 5. E2E test flows
**E2E-1: Airflow comes up and can run dbt.**
1. Run `make up`. All three stacks apply, and `.env.local` has every contract key, including the two new ones.
2. `GET $AIRFLOW_API_URL/api/v2/monitor/health` reports the metadatabase, scheduler and DAG processor as healthy.
3. A token from `POST /auth/token` with `admin` / `AIRFLOW_ADMIN_PASSWORD` is accepted by `/api/v2/dags`; a request without a token is rejected.
4. The metadata tables (for example `alembic_version`) exist in the `airflow` database and are owned by the `airflow` role, and the `warehouse` database has no Airflow tables.
5. `/opt/dbt-venv/bin/dbt debug` and `dbt parse` succeed inside the scheduler container (`docker exec`), connecting through `postgres:5432` as `dbt_runner`; Airflow's own Python environment can't import `dbt`.

**E2E-2: lifecycle, DAG discovery and rebuilds.**
1. A temporary DAG file written into `dags/` appears in `/api/v2/dags` within the DAG processor's refresh interval, paused by default; after it's deleted, it disappears. The test always removes it.
2. Restarting the scheduler container (`docker restart`) brings it back healthy, and the DAG's paused state set before the restart is kept (metadata persists in Postgres).
3. A second `make up` plans no changes in any stack.
4. Changing a file under `dbt/models/` and running `make up` rebuilds the Airflow image and replaces only the Airflow containers; `10-platform` and `20-resources` report no changes.
5. `make down` leaves no Airflow container or image, and then no project container, network or volume.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=airflow-local`. `make fmt` and `make validate` pass on all three stacks. The flows of `infra-local-platform` and `infra-local-resources` are rerun and pass (this feature changes both stacks and the Makefile).

## 7. Open items
None. The stack placement is D16 and the dbt runner is D17. GCP orchestration stays in the parking lot (`PLAN.md` §8).
