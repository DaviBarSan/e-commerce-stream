# F02.3: Store Containers & Terraform Deployment

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [02](../../../02-store-app.md) | T3.5, T3.6 | F02.1, F02.2, airflow-local (creates `30-services`) | 3 |

## 1. Goal
Package the store API and the Reflex frontend as images, and run them as part of `make up` with Terraform (`modules/local/app`).

## 2. Scope
- **In:**
  - The Dockerfiles
  - `modules/local/app` (image build and containers)
  - Wiring the module into `envs/local/30-services` (D16)
  - A seed step that runs when the environment comes up
- **Out:** the Cloud Run deployment (F01.4, Phase 8).

## 3. Implementation definition
- **Versions:** `PYTHON_IMAGE=python:3.12.15-slim-bookworm` and `UV_IMAGE=ghcr.io/astral-sh/uv:0.13.4` in `versions.env` (exported as `TF_VAR_python_image` / `TF_VAR_uv_image`); later service images (the consumer) reuse them.
- **Dockerfiles** (build context: repo root; `/.dockerignore` gains the uv workspace files: root `pyproject.toml`, `uv.lock`, `telemetry/`, both store services and the consumer's `pyproject.toml`):
  - `services/store_backend/Dockerfile`: multi-stage. The build stage runs `uv sync --frozen --no-default-groups --no-editable --package store-backend` into `/opt/venv` (the final path: console scripts such as `uvicorn` hard-code their interpreter); the runtime stage copies only the virtualenv and runs `uvicorn` as a non-root user.
  - `services/store_frontend/Dockerfile`: single stage (Reflex compiles the app from its source at start). Installs `curl` and `unzip` for Reflex's bun download, installs the dependencies with `--no-install-workspace`, and warms the build with `reflex export --frontend-only` so starts are quicker. Runs `reflex run --env prod` on port 3000 (UI and Reflex backend share it).
- **`modules/local/app`:**
  - `docker_image` builds from local context, with a source hash as a trigger so code changes rebuild the image. The hash skips `__pycache__/`, Reflex build output (`.web/`, `.states/`) and `reflex.lock/` (rewritten by every host `reflex run`), so host test runs don't cause rebuilds.
  - Containers: `store-api` on `:8000` and `store-web` on `:3000`, both on the platform network. Production mode serves the Reflex backend on the same port, so `:8001` stays unused. Host ports come from `10-platform` (`store_api_host_port`, `store_web_host_port`), like the other host ports.
- **In-network settings, passed straight to the containers:**
  - `KAFKA_BOOTSTRAP_SERVERS=kafka:19092`
  - `STORE_DB_DSN` in-network (`postgres:5432`, role `store_app`), built from the `service_credentials` output of `20-resources`
  - The frontend's `BACKEND_URL` is `http://store-api:8000`
- **Seed:** a one-shot `store-seed` container (idempotent), which runs before `store-api` starts; a `postcondition` on its exit code fails the apply if it fails.
- **Healthchecks:** `/health` for the API (with Python's `urllib`: the slim base has no curl), and `/ping` plus the root page for the frontend. Durations of a minute or more are written as Docker reports them (`1m0s`), or every plan shows a change.
- **Shutdown:** the API container stops with `SIGTERM` (30-second timeout), so the outbox relay drains and the producer flushes.
- **Host-run test servers move off the store ports:** `ApiServer` and `ReflexServer` in `tests/e2e/e2e_support.py` default to `:18000` and `:13000`, because the containers own `:8000` and `:3000` under `make up`. The container API's outbox relay works alongside a test-run API's relay (`SKIP LOCKED`), so the `store-outbox` relay-log check reads both logs.

## 4. Interfaces
- **Consumes:** the `10-platform` network, the `service_credentials` output of `20-resources`, and the `30-services` stack (D16, created by `airflow-local`).
- **Produces:** the running store on `:3000` and `:8000`; `30-services` outputs `store_api_url` and `store_web_url`.

## 5. E2E test flows
**E2E-1: store runs under `make up`.**
1. Run `make up`.
2. `GET :8000/health` returns 200, `:8000/docs` loads, and `:3000` loads.
3. The storefront, opened in a headless browser, renders products it fetched from `store-api` in-network (`BACKEND_URL=http://store-api:8000`).
4. An API purchase journey against the containers produces events in Kafka, published through the in-network `kafka:19092`.

**E2E-2: rebuild and data persistence.**
1. Change a source file and run `make up`. Only the affected image and container are replaced.
2. Recreate the seed, API and storefront containers (`terraform apply -replace=…`) without touching the database. The product count hasn't changed: the seed is idempotent and creates no duplicates. (`make down` always drops the databases, so it can't show this.)

## 6. Definition of done
Both flows pass through `make e2e FEATURE=store-deploy`.

## 7. Open items
None. The service containers live in `30-services` (D16, spec 01 §3).
