# CLAUDE.md: Development Guidelines

These rules apply to every contributor (human or agent) working in this repository.

## 1. Sources of truth

Read in this order:
1. **`PLAN.md`**: decisions (D1–D9), phases, task IDs (T*), dependencies, the parking lot and the feature map.
2. **`specs/0X-*.md`**: one spec per architecture layer, defining what the layer must do.
3. **`specs/features/<spec>/<feature>/FEATURE.md`**: one feature doc per implementation block, defining exactly what gets built and how it is tested.

When they conflict, `PLAN.md` decisions win, then the layer spec, then the feature doc. Fix the conflict in the docs before writing code.

**Never settle parking-lot items yourself** (`PLAN.md` §8). If a feature is blocked by one, stop and ask.

## 2. How work is organized

**Spec → Features → Tasks.**
- **Spec:** each layer spec is broken into **features**, which are cohesive blocks you can deliver on their own.
- **Feature:** each feature maps to one or more `PLAN.md` tasks and owns its code, its Terraform module (if any) and its **two E2E test flows**.
- **Feature ID:** the feature's folder name without the `feature-` prefix (for example `infra-foundations`). Use it for `make e2e FEATURE=<id>`, `tests/e2e/<id>/` and the branch name `feature/<id>`.
- **Unit of work:** one feature. Don't start a feature until every feature it depends on is `Done`.

### Folder structure
```
specs/
  0X-<layer>.md                         layer spec
  features/
    0X-<layer>/
      feature-<name>/
        FEATURE.md                      the feature definition (required)
        (optional) diagrams, fixtures, notes referenced by FEATURE.md
```
Example: `specs/features/01-infrastructure/feature-infra-local-platform/FEATURE.md`.

### Feature doc template (every `FEATURE.md` must have these sections)
```
# F<spec>.<n>: <Title>
| Status | Spec | Tasks | Depends on | Phase |
## 1. Goal
## 2. Scope               (in / out)
## 3. Implementation definition   (files, components, config, Terraform resources)
## 4. Interfaces           (consumes / produces: env vars, topics, tables, APIs)
## 5. E2E test flows       (exactly two: E2E-1 and E2E-2)
## 6. Definition of done
## 7. Open items           (links to parking-lot entries, if any)
```
Status values: `Not started` → `In progress` → `Done` (or `Blocked: <reason>`, or `Not scheduled` for Phase 8 and later). Update the status in the same change that completes the work.

## 3. Validation policy: two E2E flows per feature

- **Each feature defines exactly two end-to-end test flows** in its `FEATURE.md`:
  - **E2E-1: main flow.** The feature works as intended, from its real inputs to its real outputs.
  - **E2E-2: resilience or lifecycle flow.** Failure, restart, idempotency, teardown or contract parity: whichever risk matters most for that feature.
- **They are the acceptance gate.** A feature is `Done` only when both flows pass through `make e2e FEATURE=<feature-id>`, which runs `uv run pytest tests/e2e/<feature-id>`.
- **Layout:** one pytest module per flow, `tests/e2e/<feature-id>/test_e2e_1_<slug>.py` and `test_e2e_2_<slug>.py`. Shell steps go through `subprocess`.
- **No scattered runtime checks during development.** Don't run many one-off commands or poke containers by hand to "see if it works". Automate the check as one of the two flows, then run it.
- **Unit tests are optional**, and only for pure logic (schema validation, session math, and so on). They don't replace the E2E flows.
- **Validate data once, at the boundary.**
  - Events are validated by the producer (spec 04) and again by the consumer before the DLQ, and nowhere else.
  - Internal code trusts validated data. Don't add the same check at several layers.
- **Rerun earlier features' flows when you change them.** If a change touches a feature marked `Done`, rerun that feature's two flows before closing the new work.

## 4. Development workflow (per feature)
1. Read `PLAN.md`, the layer spec and the `FEATURE.md`. Confirm the features it depends on are `Done` and no parking-lot item blocks it.
2. Set the status to `In progress`.
3. Implement exactly what §3 of the feature doc describes. If the scope has to change, update the doc first.
4. Write the two E2E flows as automated tests in `tests/e2e/<feature-id>/`.
5. Run `make e2e FEATURE=<feature-id>`. Both flows must pass.
6. Set the status to `Done`, and tick the matching tasks in `PLAN.md`.

## 5. Engineering conventions

### Infrastructure (Terraform first, D4)
- All infrastructure, local included, is Terraform. **No hand-written docker-compose, and no creating resources by hand.**
- Modules go in `terraform/modules/<env>/<component>`, and root stacks in `terraform/envs/<env>/`. Local uses two stacks, `10-platform` then `20-resources` (spec 01 §3).
- Every env stack uses the **environment contract** (spec 01 §4). A new setting means a new contract key, added to every env.
- Pin provider and image versions. Run `terraform fmt` and `validate` before finishing a feature.
- A feature that adds a service also adds its Terraform module (Principle 7).

### Application code (Python)
- Python is managed with `uv`, and versions are pinned in `versions.env`.
- Settings come only from environment variables defined by the contract. **No hard-coded endpoints, credentials or cloud names.**
- Cloud SDKs (`confluent_kafka`, `google.cloud`, `boto3`) are imported only inside driver, source or sink modules (`telemetry/*_driver.py`, `services/*/<package>/sources/*`, `services/*/<package>/sinks/*`), and loaded lazily based on `STREAMING_BACKEND` / `WAREHOUSE_BACKEND`. `scripts/check_sdk_imports.py` enforces it.
- **Telemetry is emitted only by the FastAPI store backend.** The Reflex frontend and the bots never publish events.

### Data (dbt)
- Models use ANSI SQL. Dialect-specific SQL lives only in `dbt/macros/`, which dispatch on `target.type`.
- Every model has a YAML entry with its tests.

### Secrets & git
- Never commit `.env*`, `*.tfstate*` or `.terraform/`.
- Local credentials come from Terraform `random_password` and are written only to gitignored `.env.local`.

## 6. Commands
| Command | Purpose |
|---|---|
| `make doctor` | Check the tool versions |
| `make up ENV=local` / `make down ENV=local` | Create or destroy an environment (both local stacks in order) |
| `make plan ENV=local` | Show planned infrastructure changes |
| `make env ENV=local` | Write `.env.local` from the Terraform outputs |
| `make smoke ENV=local` | Platform smoke test |
| `make e2e FEATURE=<id>` | Run a feature's two E2E flows (for example `FEATURE=infra-local-platform`) |
| `make fmt` / `make validate` | Terraform formatting and validation |

## 7. Environment notes
- **Windows host:** run `make` from Git Bash. Docker Desktop must be running.
- **Local ports:**

  | Port | Service |
  |---|---|
  | 9092 | Kafka |
  | 8085 | Kafka UI |
  | 5432 | Postgres (override with `postgres_host_port` in a gitignored `*.local.auto.tfvars`) |
  | 8000 | Store API |
  | 3000 | Reflex UI |
  | 8001 | Reflex backend (reserved; production mode serves it on 3000) |
  | 8080 | Airflow |

- **Rollout order:** local must pass its end-to-end run (F05.5) before any GCP feature starts (D5). AWS stays on standby (D7).
