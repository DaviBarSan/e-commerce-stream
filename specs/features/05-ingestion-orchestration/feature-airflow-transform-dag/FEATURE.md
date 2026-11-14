# F05.4: Airflow Transform DAG (`clickstream_transform`)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [05](../../../05-ingestion-orchestration.md) | T7.2 | airflow-local, dbt-commerce-marts | 7 |

## 1. Goal
Schedule the transformation: on every cycle, check that raw data is fresh, build the dbt layers in order with their tests, and record a run summary. This is the step that turns ingested events into marts without anyone running dbt by hand, and it must be easy to debug: a failure points at one layer, its log and compiled SQL are at hand, and a fixed layer can be rerun alone.

### What it builds
- **The DAG `clickstream_transform`**, one task per dbt layer:
  `check_raw_freshness` → `dbt_seed` → `dbt_staging` → `dbt_intermediate` → `dbt_marts` → `publish_run_summary`.
  It runs on a configurable schedule (default hourly, or manual only) and never overlaps itself.
- **A per-run artifacts folder on the host**, `airflow-runs/<run>/<task>/`, holding each dbt invocation's `run_results.json`, `manifest.json`, compiled SQL and `dbt.log`.
- **A configurable freshness threshold** for the raw source, shared by dbt and the DAG.

## 2. Scope
- **In:**
  - `dags/clickstream_transform.py`
  - The raw source's freshness threshold reading `RAW_FRESHNESS_MINUTES` (`dbt/models/staging/_sources.yml`)
  - `modules/local/airflow`: the `transform_schedule` and `raw_freshness_minutes` variables (passed as `TRANSFORM_SCHEDULE` and `RAW_FRESHNESS_MINUTES`) and the `airflow-runs/` bind mount; the matching `30-services` variables
  - `airflow-runs/` in the repo root (`.gitkeep` committed, contents gitignored)
- **Out:**
  - The model logic (spec 06)
  - One task per model (for example `astronomer-cosmos`): a third-party provider, against spec 05's core-operators rule
  - The optional `clickstream_maintenance` DAG (spec 05 §8), including pruning `airflow-runs/`
  - Alerting beyond the Airflow UI

## 3. Implementation definition
- **DAG settings:**
  - `schedule` from `TRANSFORM_SCHEDULE`: a cron expression or preset (default `@hourly`), or `none` for manual runs only. `catchup=False`, `max_active_runs=1` (incremental models such as `int_sessions` never build twice at once).
  - The dbt layer tasks retry once after 30 seconds; the freshness check doesn't retry.
  - A DAG param `raw_freshness_minutes` (integer), defaulting to `RAW_FRESHNESS_MINUTES` (default 30), so a manual run can raise it after a quiet period.
  - Only core operators (spec 05 §7): `BashOperator` and `PythonOperator` from the standard provider.
- **Layers:** each layer task runs `/opt/dbt-venv/bin/dbt build --select <selector> --indirect-selection buildable`:

  | Task | Selector | Builds |
  |---|---|---|
  | `dbt_seed` | `resource_type:seed` | `event_catalog`, `page_types`, the test fixtures, and their tests |
  | `dbt_staging` | `path:models/staging` | `stg_clickstream`, the family models, and their tests |
  | `dbt_intermediate` | `path:models/intermediate` | `int_sessions`, `int_cart_lines`, and their tests |
  | `dbt_marts` | `path:models/marts` | dimensions, facts and rollups, and their tests |

  `buildable` runs a test in the first layer where everything it reads is selected or already built upstream, so a test that spans layers (for example the line-total check on `fct_orders`) runs with the marts and never against stale tables. A failing model or test fails its layer's task; the later layers are `upstream_failed`.
- **Artifacts:** every dbt command runs in `/opt/dbt` with `DBT_TARGET_PATH` and `DBT_LOG_PATH` set to `/opt/airflow/dbt-runs/<run>/<task>`, where `<run>` is the Airflow run ID with `:` and `+` removed (valid on a Windows host). `/opt/airflow/dbt-runs` is the bind-mounted `airflow-runs/` folder of the repo, so after a run the host has, per task, `run_results.json`, `manifest.json`, `compiled/` (the exact SQL of every model and test), `run/` and `dbt.log`. Folders accumulate until deleted by hand.
- **Tasks:**
  - `check_raw_freshness`: `BashOperator` running `dbt source freshness --select source:raw.clickstream_events` with `RAW_FRESHNESS_MINUTES={{ params.raw_freshness_minutes }}`. A stale or empty raw table fails it, and every dbt layer is skipped as `upstream_failed`.
  - `dbt_seed`, `dbt_staging`, `dbt_intermediate`, `dbt_marts`: `BashOperator`, as in the table above.
  - `publish_run_summary`: `PythonOperator` that reads each layer's `run_results.json`, writes `summary.json` in the run's folder, logs it as one JSON line, and returns it (XCom): per layer and in total, counts by status (`success`, `error`, `fail`, `warn`, `skipped`) and elapsed seconds. It runs only when every layer succeeds.
- **Freshness threshold** in `_sources.yml`: `error_after: {count: "{{ env_var('RAW_FRESHNESS_MINUTES', '30') | as_number }}", period: minute}`, with `warn_after` dropped (one threshold, as in spec 05 §8). This changes a `dbt-foundations` file, so that feature's flows are rerun.
- **Configuration:** `transform_schedule` (default `@hourly`) and `raw_freshness_minutes` (default 30) are `30-services` variables, overridable through `TF_VAR_*`. A change replaces only the Airflow containers.
- **Debugging a run** (the reason for the layer split and the artifacts folder):
  1. In the Airflow UI (`:8080`), the red task names the failing layer; its log holds dbt's output for that layer only.
  2. `airflow-runs/<run>/<task>/` holds that layer's `run_results.json`, the compiled SQL of the failing model or test (paste it into psql) and `dbt.log`.
  3. After a fix, clear that task with its downstream tasks: the run resumes from that layer.

## 4. Interfaces
- **Consumes:**
  - Airflow, dbt and the dbt project in the image (`airflow-local`).
  - `warehouse.raw.clickstream_events`, filled by the consumer container (`ingest-deploy`).
  - Every dbt model (F06.1–F06.3).
- **Produces:**
  - Fresh `staging`, `intermediate` and `marts` schemas on every successful cycle.
  - DAG runs, their task logs and summaries in Airflow (UI, `/api/v2`, XCom), and the artifacts in `airflow-runs/`. Used by `local-e2e` (F05.5).

## 5. E2E test flows
The flows drive Airflow through its REST API from the host (`AIRFLOW_API_URL`, `AIRFLOW_ADMIN_PASSWORD`) and create traffic through the store API container; the consumer container fills raw (`store-deploy`, `ingest-deploy`).

**E2E-1: a scheduled run builds every layer and leaves its artifacts on the host.**
1. Apply `30-services` with `TF_VAR_transform_schedule="*/2 * * * *"`.
2. Through the store API, a buyer completes a purchase and a browser stops at add-to-cart; wait until their events are in raw.
3. Unpause `clickstream_transform`. Within 6 minutes, a run with `run_type = scheduled` that started after the events landed finishes `success`, with all six tasks `success`, in order.
4. The marts contain the run's users: `fct_sessions` has their sessions, and `fct_orders` has the buyer's order with the total the API returned.
5. The `publish_run_summary` XCom lists all four layers (compared as a set: the API returns XCom dicts with reordered keys) with zero errors and failures, and its counts match the layers' `run_results.json` files.
6. On the host, `airflow-runs/<run>/` has a folder per dbt task with `run_results.json` and `manifest.json`, the compiled SQL of `fct_orders` under `dbt_marts/`, and `summary.json`.

**E2E-2: stale data, a failing layer and its rerun, and serial runs.** `30-services` is applied with `TF_VAR_transform_schedule=none`, so only triggered runs exist; the flow restores the default at the end.
1. With no new raw rows for more than one minute, trigger a run with conf `{"raw_freshness_minutes": 1}`. `check_raw_freshness` fails, the four layers are `upstream_failed`, and the mart row counts are unchanged.
2. Insert a raw row (as `ingest_writer`) that breaks a staging test: a v1 event whose `event_type` isn't in `event_catalog`. Trigger a run: `dbt_seed` succeeds, `dbt_staging` fails after its retry, and the later tasks are `upstream_failed`. Its `run_results.json` on the host names the failing test.
3. Delete the planted row and clear `dbt_staging` with its downstream tasks through the API: the same run resumes from staging and finishes `success`.
4. Trigger two runs at once. Both succeed, the second starts only after the first ends (`max_active_runs=1`), and the second changes no mart counts.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=airflow-transform-dag`. The flows of `dbt-foundations` are rerun and pass (its `_sources.yml` changes), and those of `airflow-local` (its module changes).

## 7. Open items
None. The per-layer split and the artifacts folder were chosen by the owner (2026-11-14) for debugging; one task per model stays out (spec 05 core-operators rule).
