# Spec 06: Data Transformation (dbt)

> Tasks: T6.1–T6.6, T7.2, T8.5 (see `PLAN.md`). Decisions: D11, D12, D14, D15.

## 1. Purpose
Turn raw clickstream payloads into clean, tested and analytics-ready models. The **model code must be the same** on Postgres (local) and BigQuery (GCP).

## 2. Scope
- **In scope:**
  - The dbt project and profiles
  - Cross-database macros
  - Staging, intermediate and mart models, organised as a Kimball dimensional model (D14)
  - Seeds that hold event semantics and small dimensions
  - Tests and documentation
- **Out of scope:** scheduling (spec 05) and BI/dashboards (future).

## 3. Project layout
```
dbt/
  dbt_project.yml
  packages.yml          dbt-utils (cross-db helpers, date spine, surrogate keys)
  profiles.yml          targets: local (postgres), bigquery (Phase 8); secrets from env vars
  macros/
    json_get.sql        json_get(column, path, type): cross-db JSON access (D12)
  seeds/
    event_catalog.csv   event_type → family, action, page type, funnel step (D12)
    page_types.csv      the dim_page rows
  models/
    staging/      stg_clickstream.sql, stg_events__<family>.sql (one per event family), _staging.yml
    intermediate/ int_sessions.sql, int_cart_lines.sql, _intermediate.yml
    marts/        dim_*.sql, fct_*.sql, agg_*.sql, _marts.yml
  tests/          singular tests (session boundaries, reconciliation, drift)
  seeds/fixtures/ small fixtures for session and funnel tests
```

| Target | Adapter | Schemas / datasets |
|---|---|---|
| `local` (default) | `dbt-postgres` | `staging`, `intermediate`, `marts` in the `warehouse` database, run by the `dbt_runner` role |
| `bigquery` | `dbt-bigquery` | `staging`, `intermediate`, `marts` datasets |

Seeds land in `staging`. The `intermediate` schema is added to Terraform by `dbt-sessions-funnel` (F06.2).

## 4. Portability rules
1. Models use ANSI SQL, plus `dbt_utils` / `dbt.*` cross-database macros (for example `dbt.datediff` and `dbt.dateadd`).
2. **Dialect-specific syntax lives only in `macros/`.** JSON access is the main case: `json_get(column, path, type)` dispatches on `target.type` (`postgres__json_get` uses `#>>` with a cast, `bigquery__json_get` uses `JSON_VALUE` with `SAFE_CAST`).
3. Type casts use `{{ dbt.type_timestamp() }}` and similar macros.
4. Portability test: `dbt build --target bigquery` must pass with **no model changes** (T8.5).

**JSON strategy (D12):** the frequently used fields are real columns in the raw table (D11), so most models never touch JSON. Only staging calls `json_get`: `stg_clickstream` for `properties.page`, and the family models to flatten `properties`. Intermediate models and marts are pure ANSI SQL.

## 5. Models

### 5.1 Staging

**Seed `event_catalog`** is the single source of event semantics. One row per event type:

| event_type | family | action | default_page_type | funnel_step | is_conversion |
|---|---|---|---|---|---|
| page_view | navigation | page_view | *(empty: taken from `properties.page`)* | | false |
| search | navigation | search | search | 1 | false |
| product_view | navigation | product_view | pdp | 2 | false |
| add_to_cart | cart | add | pdp | 3 | false |
| remove_from_cart | cart | remove | cart | | false |
| checkout_start | checkout | start | checkout | 4 | false |
| purchase | checkout | purchase | confirmation | 5 | true |

A new event type is a new row here, plus columns in its family model only if it brings new properties. A new family (for example `identity` for `login` and `sign_up`, journey 5) is a new staging model.

**`stg_clickstream`** (one row per `event_id`):
- The typed D11 columns: `event_id`, `schema_version`, `event_type`, `event_ts`, `produced_at`, `ingested_at`, `user_id`, `anonymous_id`, `session_id`, `product_id`, `cart_id`, `order_id`.
- `page_url` (from the payload), and `page_type`: `properties.page` for `page_view`, otherwise the seed's `default_page_type`.
- `family` and `action` from the seed.
- `payload`, kept only so the family models can read `properties`; marts don't use it.
- **Deduplication:** one row per `event_id`, the one with the earliest `ingested_at`.
- Filters out rows whose `schema_version` isn't supported (kept visible through a test with severity `warn`).

**Family models** `stg_events__<family>` select from `stg_clickstream` (so deduplication happens once) filtered on `family`. Each one has `event_id`, `event_ts` and `action`, plus its typed properties. Money becomes an amount in minor units plus a currency, and each amount keeps its own column:

| Model | Properties |
|---|---|
| `stg_events__navigation` | `page`, `search_query`, `search_results_count`, `product_category`, `product_price_minor`, `currency` |
| `stg_events__cart` | `quantity` (units added; NULL on `remove`, which removes the whole line), `unit_price_minor`, `currency` |
| `stg_events__checkout` | `items_count`, `cart_total_minor` (on `start`), `order_total_minor` (on `purchase`), `currency` |

Keys (`user_id`, `session_id`, `product_id`, `cart_id`, `order_id`) stay in `stg_clickstream`; consumers join on `event_id`.

### 5.2 Intermediate (incremental)

**`int_sessions`**: one row per event, giving its derived session.
- A **30-minute inactivity window**, using ANSI window functions: `LAG(event_ts)` per `user_id` makes a new-session flag, and `SUM() OVER` makes `session_seq`. `session_key = dbt_utils.generate_surrogate_key(['user_id', 'session_seq'])`.
- **Why sessions are derived instead of reusing the client `session_id`:**
  - The client ID is a technical tab identifier with no inactivity expiry (the storefront keeps it in `sessionStorage` for as long as the tab lives), so a tab left open all day is one "session".
  - The API mints a new ID per request when the `X-Session-Id` header is missing.
  - Bots keep it across idle gaps on purpose (spec 03 §5).
  - A rule in the warehouse applies to every client and can be recomputed over history when it changes; identity stitching (journey 5) needs that.

  The client ID is kept as `client_session_id` for comparison and debugging.

**`int_cart_lines`**: one row per (cart, product), giving the line's final state: the sum of `quantity` from the adds after the line's last `remove`, and the latest `unit_price_minor`. Lines whose last action is a `remove` have quantity 0 and are flagged `is_removed`.

### 5.3 Marts (D14)

**Conformed dimensions**

| Model | Grain | Content |
|---|---|---|
| `dim_date` | one calendar day | weekday, week, month, year, weekend flag (`dbt_utils.date_spine`) |
| `dim_time_of_day` | one hour (24 rows) | hour, day part |
| `dim_page` | one page type (7 rows) | home, catalog, search, pdp, cart, checkout, confirmation, with funnel stage (seed) |
| `dim_event_type` | one event type | the `event_catalog` seed |
| `dim_users` | one `user_id` | `is_anonymous`, first and last seen, session count, lifetime orders, `is_returning` |
| `dim_sessions` | one derived session | `client_session_id`, start and end, landing and exit page type |
| `dim_products` | one `product_id` | category and last seen price (names arrive only with store data, journey 10) |

**Facts**

| Model | Type | Grain | Measures |
|---|---|---|---|
| `fct_events` | transaction (factless) | one event | the row count. Shared columns and keys only; type-specific details stay in the family models |
| `fct_sessions` | accumulating snapshot | one session | milestone timestamps (first search, product view, add to cart, checkout start, purchase), step flags, event counts, duration |
| `fct_carts` | accumulating snapshot | one cart | created, checkout-started and purchased timestamps, minutes between them, line and unit counts, checkout total, status `open` / `abandoned` / `converted` |
| `fct_order_lines` | transaction | one product in one order | quantity, unit amount and line amount (minor units, with currency). `order_id` is a degenerate dimension |

A cart is `abandoned` when it has no purchase and its last activity is more than 30 minutes before the newest event in the warehouse; otherwise it's `open` until it converts. This is the warehouse's own definition (the store's `carts.status` is not used, per D15).

**Rollups:** `agg_funnel_daily` (one day × landing page type, from `fct_sessions`) and `fct_orders` (one order, from `fct_order_lines`).

### 5.4 Bus matrix

Rows are business processes; columns are the conformed dimensions. A cell names the role when a fact uses a dimension in a specific way.

| Fact | date | time of day | users | sessions | products | page | event type |
|---|---|---|---|---|---|---|---|
| `fct_events` | event | event | ✓ | ✓ | ✓ (when present) | ✓ | ✓ |
| `fct_sessions` | session start | session start | ✓ | grain | | landing, exit | |
| `fct_carts` | created, checkout, purchased | | ✓ | origin | | | |
| `fct_order_lines` | order | order | ✓ | ✓ | ✓ | | |

Rules:
- **Additivity:** money is additive only within a currency, so always group by currency before summing. Checkout totals on `fct_carts` are point-in-time values.
- **Rates are never stored.** Facts hold counts and flags; conversion and abandonment rates are divided at query time.
- **Keys:** natural keys and SCD Type 1. `session_key` is the only generated key.

## 6. Materialization & incrementality
| Layer | Materialization | Incremental strategy |
|---|---|---|
| Staging | view in dev, incremental in larger runs | `event_ts`, with a lookback of at least 30 minutes so late events and session edges are handled |
| Intermediate | incremental | Re-computes the affected sessions and carts within the lookback window |
| Marts | table | none |

The incremental predicates must use cross-database macros (`dbt.dateadd`).

## 7. Tests
| Model | Tests |
|---|---|
| `event_catalog` | `unique` on `event_type`; `accepted_values` on `family` |
| `stg_clickstream` | `unique` + `not_null` on `event_id`; `relationships` from `event_type` to `event_catalog` (an unmapped type fails); `not_null` on `user_id`, `session_id`, `event_ts`, `family`, `action`, `page_type`; a `warn` test on unsupported `schema_version` rows in raw |
| `stg_events__<family>` | `unique` + `not_null` on `event_id`; `accepted_values` on `action`; per-action `not_null` on required properties (for example `quantity` when `action = 'add'`) |
| `int_sessions` | `unique` on `event_id`; a singular test that a gap of 31 minutes splits a session and a gap of 29 minutes doesn't (seed fixture); a `warn` drift check that derived sessions per distinct `client_session_id` stay within 0.5–3 |
| Dimensions | `unique` + `not_null` on the grain key |
| Facts | `unique` + `not_null` on the grain key; `relationships` to every dimension in the bus matrix; `duration_seconds >= 0` |
| `fct_sessions` | funnel step counts never increase down the funnel |
| `fct_order_lines` | per order, `sum(line_total_minor)` equals the purchase event's `order_total_minor` |
| Sources | `dbt source freshness` on the raw table (warns at 30 minutes and errors at 2 hours) |

## 8. Execution
- **Locally, by hand:** `make dbt ARGS="build"` (loads `.env.local`).
- **Scheduled:** the `clickstream_transform` DAG (spec 05 §8).
- **Docs:** `dbt docs generate` (optional artifact).

## 9. Acceptance criteria
1. `dbt debug` and `dbt build --target local` pass on a clean warehouse that has only raw data.
2. Every event type in raw maps to a family; an unmapped type fails the build.
3. The sessionization fixtures give the expected session boundaries.
4. The funnel counts reconcile with the raw event counts per step (after deduplication).
5. Every fact joins to the dimensions the bus matrix lists for it.
6. Order totals in the marts reconcile with `store.orders` (made possible by D15).
7. There's no dialect-specific SQL outside `macros/`. A lint or grep check enforces this.
8. Phase 8: the `bigquery` target builds with no model changes.

## 10. Open items
- None for the model. The session key is settled: the derived `session_key` is used for reporting, and the client `session_id` is kept as `client_session_id` (§5.2).
