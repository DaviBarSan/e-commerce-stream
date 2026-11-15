# F01.5: Local Persistence (`make stop` / `make start`, Airflow task logs on the host)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [01](../../../01-infrastructure.md), [05](../../../05-ingestion-orchestration.md) | T7.4 | infra-local-resources, airflow-local | 7 |

## 1. Goal
Let a developer keep their local data between work sessions. Today the only way to "turn the environment off" is `make down`, which destroys every stack and so drops the `store`, `warehouse` and `airflow` databases. Airflow task logs are even more fragile: they live inside the scheduler container, so any `make up` that replaces it (an image rebuild after a `dbt/` change, a schedule change) loses every past log, although the run history itself is kept in Postgres.

After this feature:
- **`make stop` / `make start`** pause and resume the whole environment without destroying anything: Postgres data, Kafka messages, Airflow run history and logs all survive, and so does a PC shutdown.
- **Airflow task logs are written to the host** (`airflow-logs/`, next to `airflow-runs/`), so they survive container replacement and are browsable as files.
- **`make down` keeps its meaning, a full reset**, and its help text says plainly that it deletes all data.

### Where each kind of data lives, after this feature
| Data | Location | `make stop`/`start`, PC reboot | `make up` replacing a container | `make down` |
|---|---|---|---|---|
| `store`, `warehouse` (raw, staging, marts) | Docker volume `clickstream-pgdata` | kept | kept | deleted |
| Airflow history (DAG runs, task states, XCom) | `airflow` database, same volume | kept | kept | deleted |
| Airflow task logs | host `airflow-logs/` (new) | kept | kept (today: lost) | kept (host folder) |
| dbt run artifacts | host `airflow-runs/` (F05.4) | kept | kept | kept (host folder) |
| Kafka messages and consumer offsets | Kafka container filesystem | kept | lost if the Kafka container is replaced (raw already holds every consumed event) | deleted |

## 2. Scope
- **In:**
  - `Makefile`: `stop` and `start` targets; the `down` help text
  - `modules/local/airflow`: the `airflow-logs/` bind mount on the scheduler, API server and DAG processor
  - `airflow-logs/` in the repo root (`.gitkeep` committed, contents gitignored, like `airflow-runs/`)
  - Docs: spec 01 §9 (Makefile interface) and §10, spec 05 §7 (Airflow deployment), `CLAUDE.md` §6 and the README command tables, `PLAN.md` (T7.4)
  - **No E2E flow destroys anything** (owner's rule, 2026-11-15): the flows that ran `make down` or a stack destroy (`infra-local-platform`, `infra-local-resources`, `airflow-local`) start from `make up` instead and check teardown on `terraform plan -destroy`. `Stack.destroy()` is removed from `tests/e2e/e2e_support.py` and replaced by `Stack.destroy_plan()`; `CLAUDE.md` §3 states the rule. Their `FEATURE.md` flows change accordingly, and so does the not-scheduled `infra-gcp-platform` E2E-2.
  - `infra-foundations` E2E-1 expects the two new targets in `make help`.
  - The pending `.gitignore` entry for the personal `HOWTO.txt` (carried on this branch)
- **Out:**
  - **A data-keeping `make down`** (destroying the stacks but keeping the databases). It would need `keep_data = true`, skipping the `20-resources` destroy (which runs `DROP DATABASE`) and a stable Airflow Fernet key across destroys. `make stop` covers the need without making teardown ambiguous; `keep_data` (F01.2) stays available for platform-only rebuilds.
  - A volume for Kafka: raw is the durable copy of every consumed event, and the outbox (D15) keeps unpublished state changes in Postgres.
  - Backup and restore (`pg_dump`) of the local databases.
  - Pruning `airflow-logs/` or `airflow-runs/` (the optional `clickstream_maintenance` DAG, spec 05 §8).

## 3. Implementation definition
- **`make stop`** (`ENV=local` only; other envs fail with "not supported"): stops every running project container with `docker stop`, selected by the labels every local container already has (`project=<project_name>`, `managed_by=terraform`), **in two passes: the `30-services` containers first, then the platform** (Kafka UI, Kafka, Postgres). Services stop while their dependencies are still up: the store API's outbox relay drains on shutdown (F02.4) and the consumer commits its last batch. Containers and volumes are kept, and Terraform state is untouched. Running it twice is a no-op.
- **`make start`**: the reverse. Starts the platform containers first and waits for Postgres and Kafka to report healthy, then starts the long-running service containers. **One-shot containers (`airflow-init`, `store-seed`) are not restarted**: they are recognised by having no restart policy (every long-running container has `restart = unless-stopped`). It waits until every started container with a healthcheck is healthy, and fails, naming the container, if one isn't within 3 minutes. Running it with everything up is a no-op.
- **Consistency with Terraform:** after `make stop` then `make start`, `make plan` shows no changes in any stack (same containers, same IDs, same passwords; `.env.local` is unchanged). A `make up` instead of `make start` is also safe: it starts or recreates the stopped containers, and Postgres data is kept because it lives in the volume.
- **PC shutdown:** needs nothing from this feature beyond the log mount. Docker stops the containers, and those with `restart = unless-stopped` come back when Docker Desktop starts; containers paused with `make stop` stay stopped until `make start`.
- **Airflow task logs:** `modules/local/airflow` bind-mounts `${repo_root}/airflow-logs` at `/opt/airflow/logs` (Airflow's default `base_log_folder`) on the scheduler (LocalExecutor writes task logs there), the API server (it reads them directly from disk for the UI and `/api/v2`, instead of fetching them from the scheduler's log server) and the DAG processor (its own logs). No Airflow setting changes. `airflow-logs/.gitkeep` makes sure the bind source exists on a fresh clone.
- **`make down`**: unchanged behaviour. Help text: "Destroy every stack of ENV in reverse order (full reset: deletes all databases)". `airflow-logs/` and `airflow-runs/` are host folders and survive it.
- **Docs:**
  - Spec 01 §9: add `make stop` and `make start`, and state that `make down` deletes all data. §10 acceptance item 5 also notes the two host folders.
  - Spec 05 §7: a "Logs" row (task logs bind-mounted to the host's `airflow-logs/`).
  - `CLAUDE.md` §3 (E2E flows never destroy) and §6, and `README.md`: the two new commands.
- **Plan-based teardown checks** (`tests/e2e/e2e_support.py`): `Stack.plan_json(*args)` saves a plan and returns `terraform show -json`; `Stack.destroy_plan()` returns the resources `plan -destroy` would delete; `planned_docker_names(changes, kind)` lists the Docker names among them.
  - `PLAN.md`: task T7.4 in Phase 7 (deps T7.1) and the status line.

## 4. Interfaces
- **Consumes:** the local stacks and their container labels (F01.2, F01.3, D16); the Airflow containers (F05.3); the outbox relay's drain on shutdown (F02.4).
- **Produces:**
  - `make stop` and `make start`.
  - `airflow-logs/<dag_id=…>/<run_id=…>/<task_id=…>/attempt=<n>.log` on the host, and the DAG processor's logs under `airflow-logs/dag_processor/`.
  - No new contract key, topic, table or API.

## 5. E2E test flows
Neither flow runs `make down` (no E2E flow does, `CLAUDE.md` §3), so running them never wipes the developer's data. `make down`'s effect is covered by the destroy plans checked in the `infra-local-*` and `airflow-local` flows.

**E2E-1: data, run history and task logs survive a stop/start and an Airflow container replacement.**
1. With the environment up, a buyer completes a purchase through the store API; wait until its events are in raw. Trigger `clickstream_transform` (conf `raw_freshness_minutes` large enough) and wait for `success`.
2. Record: row counts of `store.orders`, `raw.clickstream_events` and the marts; the run's task states; the `dbt_marts` task log returned by the Airflow API; and the hash of `.env.local`.
3. `make stop`: no project container is running, every one still exists (`docker ps -a`), and the `pgdata` volume exists.
4. `make start`: every long-running container is running and healthy; `airflow-init` and `store-seed` were not started again (their `State.StartedAt` is unchanged). `terraform plan -detailed-exitcode` exits 0 in all three stacks, and `.env.local` is unchanged.
5. Every count from step 2 is the same; the run is still listed with the same task states; the `dbt_marts` log is returned unchanged; logging in as `admin` with `AIRFLOW_ADMIN_PASSWORD` still works.
6. Replace the scheduler and API server containers (`terraform apply -replace` on both in `30-services`). The `dbt_marts` log from step 1 is still returned by the API, and its file exists under the host's `airflow-logs/`.

**E2E-2: in-flight events across a stop, idempotent targets, and `make up` after a stop.**
1. Add an item to a cart through the store API and run `make stop` straight away. After `make start`, the `add_to_cart` event reaches raw exactly once (the relay drains on shutdown or publishes the leftover outbox row after the start).
2. `make stop` twice in a row succeeds, and so does `make start` with everything already running; neither changes any container ID.
3. After `make stop`, run `make up` instead of `make start`: it succeeds, every long-running container is running, no project container is left orphaned (every container with the project label is in Terraform state), and the Postgres counts from before the stop are unchanged.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=local-persistence`. `make fmt` and `make validate` pass. Rerun and passing, because their flows or modules change: `airflow-local` (module and flows), `infra-local-platform` and `infra-local-resources` (flows), `infra-foundations` (the target list). The other features aren't rerun: the logs mount doesn't change what the DAG or the services do.

## 7. Open items
None. A data-keeping `make down` was considered and left out (§2); it can be a later feature if `make stop` turns out not to be enough.
