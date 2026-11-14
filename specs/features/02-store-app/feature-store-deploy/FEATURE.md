# F02.3: Store Containers & Terraform Deployment

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [02](../../../02-store-app.md) | T3.5, T3.6 | F02.1, F02.2, airflow-local (creates `30-services`) | 3 |

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
- **Dockerfiles:** `services/store_backend/Dockerfile` and `services/store_frontend/Dockerfile`, both multi-stage and using `uv`.
- **`modules/local/app`:**
  - `docker_image` builds from local context, with a source hash as a trigger so code changes rebuild the image.
  - Containers: `store-api` on `:8000` and `store-web` on `:3000` / `:8001`, both on the platform network.
- **In-network settings, passed straight to the containers:**
  - `KAFKA_BOOTSTRAP_SERVERS=kafka:19092`
  - `STORE_DB_DSN` in-network (`postgres:5432`, role `store_app`), built from the `service_credentials` output of `20-resources`
  - The frontend's `BACKEND_URL` is `http://store-api:8000`
- **Seed:** a one-shot `store-seed` container (idempotent), which runs before `store-api` is reported healthy.
- **Healthchecks:** `/health` for the API, and the root page for the frontend.

## 4. Interfaces
- **Consumes:** the `10-platform` network, the `service_credentials` output of `20-resources`, and the `30-services` stack (D16, created by `airflow-local`).
- **Produces:** the running store on `:3000` and `:8000`.

## 5. E2E test flows
**E2E-1: store runs under `make up`.**
1. Run `make up`.
2. `GET :8000/health` returns 200, `:8000/docs` loads, and `:3000` loads.
3. An API purchase journey against the containers produces events in Kafka, published through the in-network `kafka:19092`.

**E2E-2: rebuild and data persistence.**
1. Change a source file and run `make up`. Only the affected image and container are replaced.
2. Run `make down` (keeping data) and then `make up`. The product count hasn't changed: the seed is idempotent and creates no duplicates.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=store-deploy`.

## 7. Open items
None. The service containers live in `30-services` (D16, spec 01 §3).
