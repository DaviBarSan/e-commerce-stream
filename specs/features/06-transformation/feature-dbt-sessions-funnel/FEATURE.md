# F06.2: dbt Sessions and Funnel (conformed dimensions, sessionization, session marts)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [06](../../../06-transformation.md) | T6.4, T6.5 | dbt-foundations | 6 |

## 1. Goal
Build the conformed dimensions and the browsing and funnel side of the dimensional model (D14): derive sessions from 30 minutes of inactivity, then publish the event fact, the session fact (the funnel as an accumulating snapshot) and its daily rollup. This answers journey 1's funnel questions (`PLAN.md` §9).

### What it builds
- **The `intermediate` schema** (Terraform) and **`int_sessions`**.
- **Conformed dimensions:** `dim_date`, `dim_time_of_day`, `dim_page`, `dim_event_type`, `dim_users`, `dim_sessions`.
- **Facts and rollups:** `fct_events`, `fct_sessions`, `agg_funnel_daily`.

## 2. Scope
- **In:**
  - Adding `intermediate` to the `dbt_runner` schemas in `terraform/envs/local/20-resources/postgres.tf`
  - The `page_types` seed and the session fixtures under `dbt/seeds/fixtures/`
  - The models listed above, with the tests in spec 06 §7
- **Out:**
  - Carts, orders and products (`dbt-commerce-marts`)
  - Scheduling (T7.2)
  - The `bigquery` target (Phase 8)

## 3. Implementation definition
- **Terraform:** `postgresql_schema.dbt` `for_each` becomes `["staging", "intermediate", "marts"]`. Run `terraform fmt` and `validate`, then rerun the `infra-local-resources` flows.
- **`dbt_project.yml`:** `intermediate` models go in schema `intermediate` (incremental) and `marts` models go in schema `marts` (table).
- **The session rule** lives in the macro `dbt/macros/sessionize.sql`, so `int_sessions` and the boundary fixture test run the same SQL:
  - It partitions by `user_id` and orders by `event_ts, event_id`.
  - `is_new_session` is set when there's no previous event or the gap is over 30 minutes (`dbt.datediff`, in seconds).
  - `session_seq = SUM(is_new_session) OVER (…)`, and `session_key = dbt_utils.generate_surrogate_key(['user_id', 'session_seq'])`.
- **`int_sessions`** (incremental, `unique_key = event_id`):
  - Reads `stg_clickstream` and applies `sessionize()`.
  - An incremental run recomputes **every event of each user who has new events** (`ingested_at` after the table's latest). `session_seq` is then a deterministic running count over the user's whole history, so session keys never change for other users.
  - A late event that bridges two sessions merges them on the next run.
- **Dimensions** (tables, spec 06 §5.3):
  - `dim_date` comes from `dbt_utils.date_spine`, from `var('dim_date_start')` (`2026-01-01`) to a year ahead. `day_of_week` is ISO (Monday = 1), through the dispatched macro `day_of_week()`. Dates and hours are UTC.
  - `dim_time_of_day` has 24 rows.
  - `dim_page` comes from the `page_types` seed.
  - `dim_event_type` comes from `event_catalog`.
  - `dim_users` and `dim_sessions` are built from `int_sessions` and `stg_clickstream`.
- **Facts** (tables):
  - `fct_events`: `event_id`, `event_ts`, `date_day`, `hour_of_day`, `user_id`, `session_key`, `client_session_id`, `event_type`, `page_type`, `product_id`, `cart_id`, `order_id`.
  - `fct_sessions`: one row per `session_key`, with the first timestamp of each funnel step (from `event_catalog.funnel_step`), step flags, `event_count`, `search_count`, `zero_result_search_count` (from `stg_events__navigation`) and `duration_seconds`. The funnel is ordered: a step counts only at or after the previous one, so reached counts never increase.
  - `agg_funnel_daily`: sessions reaching each step per `date_day` × landing page type.
- **Tests:** spec 06 §7 rows for `int_sessions`, dimensions, facts and `fct_sessions`, including:
  - The singular 29/31-minute boundary test on `dbt/seeds/fixtures/session_gaps.csv`.
  - The `warn` drift check between derived sessions and `client_session_id`.

## 4. Interfaces
- **Consumes:** the `dbt-foundations` staging models and seed; the `dbt_runner` role (`infra-local-resources`).
- **Produces:**
  - `warehouse.intermediate.int_sessions`
  - In `warehouse.marts`: `dim_date`, `dim_time_of_day`, `dim_page`, `dim_event_type`, `dim_users`, `dim_sessions`, `fct_events`, `fct_sessions`, `agg_funnel_daily`
  - Read by `dbt-commerce-marts`, the transform DAG (T7.2) and future BI

## 5. E2E test flows
**E2E-1: sessions and funnel from real events.**
1. Publish three journey-1 sessions through Kafka:
   - one that converts;
   - one that stops after add to cart;
   - one from a returning user who comes back after a 40-minute gap on the same client `session_id`.
2. Ingest them, then run `make dbt ARGS=build`. Everything passes.
3. `fct_sessions` has 4 sessions (the 40-minute gap splits one client session).
4. The step flags and milestone timestamps match the journeys, and `agg_funnel_daily` counts never increase down the funnel.
5. `fct_events` joins to every dimension in the bus matrix with no orphans, and `dim_users` marks the returning user.

**E2E-2: boundaries, late events and idempotent reruns.**
1. Build with the session fixtures. A 31-minute gap splits a session and a 29-minute gap doesn't.
2. Ingest a late event that falls inside an existing session's window and rebuild incrementally. It joins that session, and no session keys change for other users.
3. Run `dbt build` twice more. Nothing changes and the tests stay green.
4. Rerun the `infra-local-resources` flows (Terraform changed).

## 6. Definition of done
Both flows pass through `make e2e FEATURE=dbt-sessions-funnel`, the `infra-local-resources` flows still pass, and `make fmt` / `make validate` are clean.

## 7. Open items
None.
