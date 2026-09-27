# Spec 06: Data Transformation (dbt)

> Tasks: T6.1–T6.5, T7.2, T8.5 (see `PLAN.md`)

## 1. Purpose
Turn raw clickstream payloads into clean, tested and analytics-ready models. The **model code must be the same** on Postgres (local) and BigQuery (GCP).

## 2. Scope
- **In scope:**
  - The dbt project and profiles
  - Cross-database macros
  - Staging, intermediate and mart models
  - Tests and documentation
- **Out of scope:** scheduling (spec 05) and BI/dashboards (future).

## 3. Project layout
```
dbt/
  dbt_project.yml
  packages.yml          dbt-utils (cross-db helpers)
  profiles.yml          targets: local (postgres), bigquery (Phase 8); secrets from env vars
  macros/
    json_get.sql        json_get(column, path, type): cross-db JSON access (D12)
  models/
    staging/      stg_clickstream.sql, stg_events__<event_type>.sql (one per event type), _staging.yml
    intermediate/ int_sessions.sql, _intermediate.yml
    marts/        fct_events.sql, fct_conversion_funnels.sql, dim_users.sql, _marts.yml
  tests/          singular tests (e.g. session boundary assertions)
  seeds/          small fixtures for session/funnel tests
```

| Target | Adapter | Schemas / datasets |
|---|---|---|
| `local` (default) | `dbt-postgres` | `staging`, `marts` in the `warehouse` database, run by the `dbt_runner` role |
| `bigquery` | `dbt-bigquery` | `staging`, `marts` datasets |

## 4. Portability rules
1. Models use ANSI SQL, plus `dbt_utils` / `dbt.*` cross-database macros (for example `dbt.datediff` and `dbt.dateadd`).
2. **Dialect-specific syntax lives only in `macros/`.** JSON access is the main case: `json_get(column, path, type)` dispatches on `target.type` (`postgres__json_get` uses `#>>` with a cast, `bigquery__json_get` uses `JSON_VALUE` with `SAFE_CAST`).
3. Type casts use `{{ dbt.type_timestamp() }}` and similar macros.
4. Portability test: `dbt build --target bigquery` must pass with **no model changes** (T8.5).

**JSON strategy (D12):** the frequently used fields are real columns in the raw table (D11), so most models never touch JSON. Only the per-event-type staging models call `json_get`, to flatten `properties`; intermediate models and marts are pure ANSI SQL.

## 5. Models

### 5.1 `stg_clickstream` (view or incremental)
- Selects the typed columns of the raw table (D11): `event_id`, `event_type`, `event_ts`, `produced_at`, `ingested_at`, `user_id`, `anonymous_id`, `session_id`, `product_id`, `cart_id`, `order_id`, plus `page_url` via `json_get`.
- **Per-event-type models** `stg_events__<event_type>` (for example `stg_events__add_to_cart`) flatten that type's `properties` with `json_get`; money becomes `amount_minor` plus `currency` columns.
- **Deduplication:** keep one row per `event_id`, the one with the earliest `ingested_at`.
- Filters out rows whose `schema_version` isn't supported (kept visible through a test with severity `warn`).

### 5.2 `int_sessions` (incremental)
- A **30-minute inactivity window**, using ANSI window functions: `LAG(event_ts)` per `user_id` makes a new-session flag, and `SUM() OVER` makes a `derived_session_seq`.
- Grain: one row per derived session.
- **Why sessions are derived from inactivity:** it's analytically sound. The client's `session_id` is kept for comparison, since bot idle gaps (spec 03 §5) should split sessions.
- Metrics:
  - `session_start`, `session_end`, `duration_seconds`
  - `pageviews`, `product_views`, `items_added`
  - `reached_checkout`, `converted` (bool), `order_total`

### 5.3 Marts
| Model | Grain | Purpose |
|---|---|---|
| `fct_events` | One event | Clean event fact, with the derived session key attached |
| `fct_conversion_funnels` | Session (plus a daily rollup) | Steps: search → product_view → add_to_cart → purchase, with step flags and drop-off |
| `dim_users` | One user | First and last seen, session count, lifetime orders and revenue, and a returning-user flag |

## 6. Materialization & incrementality
| Layer | Materialization | Incremental strategy |
|---|---|---|
| Staging | view in dev, incremental in larger runs | `event_ts`, with a lookback of at least 30 minutes so late events and session edges are handled |
| Intermediate | incremental | Re-computes the affected sessions within the lookback window |
| Marts | table | none |

The incremental predicates must use cross-database macros (`dbt.dateadd`).

## 7. Tests
| Model | Tests |
|---|---|
| `stg_clickstream` | `unique` + `not_null` on `event_id`; `accepted_values` on `event_type`; `not_null` on `user_id`, `session_id`, `event_ts` |
| `int_sessions` | `unique` on the session key; `duration_seconds >= 0`; a singular test that a gap of 31 minutes splits a session and a gap of 29 minutes doesn't (seed fixture) |
| `fct_events` | `relationships` to `int_sessions` and `dim_users` |
| `fct_conversion_funnels` | Step counts never increase down the funnel |
| `dim_users` | `unique` + `not_null` on `user_id` |
| Sources | `dbt source freshness` on the raw table (warns at 30 minutes and errors at 2 hours) |

## 8. Execution
- **Locally, by hand:** `dbt build --target local`.
- **Scheduled:** the `clickstream_transform` DAG (spec 05 §8).
- **Docs:** `dbt docs generate` (optional artifact).

## 9. Acceptance criteria
1. `dbt debug` and `dbt build --target local` pass on a clean warehouse that has only raw data.
2. The sessionization fixtures give the expected session boundaries.
3. The funnel counts reconcile with the raw event counts per step (after deduplication).
4. There's no dialect-specific SQL outside `macros/`. A lint or grep check enforces this.
5. Phase 8: the `bigquery` target builds with no model changes.

## 10. Open items
- Whether sessions use the derived inactivity sessions only, or also the client `session_id`, for reporting.
