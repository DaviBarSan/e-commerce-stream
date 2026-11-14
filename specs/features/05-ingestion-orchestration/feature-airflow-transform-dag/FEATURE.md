# F05.4: Airflow Transform DAG (`clickstream_transform`)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [05](../../../05-ingestion-orchestration.md) | T7.2 | airflow-local, dbt-commerce-marts | 7 |

## 1. Goal
Schedule the transformation: on every cycle, check that raw data is fresh, build every dbt model with its tests, and record a run summary. This is the step that turns ingested events into marts without anyone running dbt by hand.

### What it builds
- **The DAG `clickstream_transform`:** `check_raw_freshness` → `dbt_build` → `publish_run_summary`, on a configurable schedule (default hourly), never overlapping itself.
- **A configurable freshness threshold** for the raw source, shared by dbt and the DAG.

## 2. Scope
- **In:**
  - `dags/clickstream_transform.py`
  - The raw source's freshness threshold reading `RAW_FRESHNESS_MINUTES` (`dbt/models/staging/_sources.yml`)
  - The `transform_schedule` and `raw_freshness_minutes` variables of `modules/local/airflow`, passed to the containers as `TRANSFORM_SCHEDULE` and `RAW_FRESHNESS_MINUTES`
- **Out:**
  - The model logic (spec 06)
  - The optional `clickstream_maintenance` DAG (spec 05 §8)
  - Alerting beyond the Airflow UI

## 3. Implementation definition
- **DAG settings:**
  - `schedule` from `TRANSFORM_SCHEDULE` (default `@hourly`), `catchup=False`, `max_active_runs=1` (incremental models such as `int_sessions` never build twice at once).
  - `retries=1` with a 2-minute delay on `dbt_build` only; the freshness check doesn't retry.
  - A DAG param `raw_freshness_minutes`, defaulting to `RAW_FRESHNESS_MINUTES` (default 30), so a manual run can override it.
  - Only core operators (spec 05 §7): `BashOperator` and `PythonOperator`.
- **Per-run dbt paths:** every dbt command runs in `/opt/dbt` with `DBT_TARGET_PATH` and `DBT_LOG_PATH` set to `/tmp/dbt/<run_id>` (templated), so concurrent tasks and reruns never share artifacts and the image's project folder stays read-only.
- **Tasks:**
  - `check_raw_freshness`: `BashOperator` running `/opt/dbt-venv/bin/dbt source freshness --select source:raw.clickstream_events`, with `RAW_FRESHNESS_MINUTES={{ params.raw_freshness_minutes }}`. A non-zero exit (stale or empty raw table) fails the task, and `dbt_build` is skipped as `upstream_failed`.
  - `dbt_build`: `BashOperator` running `/opt/dbt-venv/bin/dbt build` (seeds, models and tests: staging → intermediate → marts). A failing test fails the task. No separate `dbt test` step: `dbt build` already runs the tests.
  - `publish_run_summary`: `PythonOperator` that reads `run_results.json` from the run's target path and logs one JSON line with the invocation ID, elapsed time and counts by status (success, error, fail, warn, skip), and pushes the same dict to XCom. It runs only when `dbt_build` succeeds.
- **Freshness threshold** in `_sources.yml`: `error_after: {count: "{{ env_var('RAW_FRESHNESS_MINUTES', '30') | int }}", period: minute}`; `warn_after` is dropped (a single threshold, as in spec 05 §8). This changes a `dbt-foundations` file, so that feature's flows are rerun.
- **Configuration:** `transform_schedule` (default `@hourly`) and `raw_freshness_minutes` (default 30) are `30-services` variables, overridable through `TF_VAR_*`. A change replaces only the Airflow containers.

## 4. Interfaces
- **Consumes:**
  - Airflow, dbt and the dbt project in the image (`airflow-local`).
  - `warehouse.raw.clickstream_events` (`ingest-consumer`).
  - Every dbt model, through `dbt build` (F06.1–F06.3).
- **Produces:**
  - Fresh `staging`, `intermediate` and `marts` schemas on every successful cycle.
  - DAG runs and their summaries in Airflow (UI, `/api/v2`, XCom), used by `local-e2e` (F05.5).

## 5. E2E test flows
The flows use the Airflow REST API from the host (`AIRFLOW_API_URL`, `AIRFLOW_ADMIN_PASSWORD`) and ingest test events with the host-side consumer helper (`ingest_events`), so they don't depend on the consumer container (F05.2).

**E2E-1: a scheduled run builds the marts.**
1. Run `make up` with `TF_VAR_transform_schedule="*/2 * * * *"`.
2. Ingest a set of journey-1 events for unique users (a buyer who completes a purchase and a browser who stops at add-to-cart).
3. Unpause `clickstream_transform`. Within 5 minutes, a run with `run_type = scheduled` finishes `success`, with all three tasks `success`.
4. The marts contain the run's users: `fct_sessions` has their sessions with the right funnel flags, and `fct_orders` has the buyer's order.
5. The `publish_run_summary` XCom shows zero errors and zero test failures, and its counts match the `run_results.json` totals.

**E2E-2: stale data, failures and reruns.**
1. With no new events for more than one minute, trigger a run with conf `{"raw_freshness_minutes": 1}`. `check_raw_freshness` fails, `dbt_build` is `upstream_failed`, and the mart row counts are unchanged.
2. Ingest new events and trigger two runs one after the other. Both succeed, they never run at the same time (`max_active_runs=1`), and the second run changes no mart counts or checksums.
3. Insert a raw row (as `ingest_writer`, bypassing the consumer) that breaks an error-severity dbt test, for example a v1 event whose `event_type` isn't in the `event_catalog` seed. Trigger a run: `dbt_build` fails after its retry and `publish_run_summary` doesn't run. Delete the planted row; the next run succeeds.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=airflow-transform-dag`. The flows of `dbt-foundations` are rerun and pass (its `_sources.yml` changes).

## 7. Open items
- Depends on `dbt-commerce-marts` (T6.6), per `PLAN.md`. The DAG itself doesn't need the commerce models (it runs `dbt build` on whatever exists), so it could be built against the session marts and gain the commerce models later; that needs the T7.2 dependency changed in `PLAN.md` (owner's call). E2E-1 step 4's `fct_orders` check assumes F06.3 is done.
