# F06.1: dbt Foundations (project, JSON macro, staging layer)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [06](../../../06-transformation.md) | T6.1, T6.2, T6.3 | infra-local-resources, ingest-consumer | 6 |

## 1. Goal
Turn the raw table `warehouse.raw.clickstream_events` (D11) into a clean, deduplicated, typed staging layer that every later model builds on: one view for all events plus one view per **event family**, with each family's `properties` flattened and an `action` column (D12). This is the first transformation step of journey 1 (`PLAN.md` §9).

### What it builds
- **A dbt project** in `dbt/`, run with `make dbt ARGS="..."`, which loads `.env.<ENV>` so the profile reads only contract keys.
- **The `json_get(column, path, type)` macro**, the only place with dialect-specific JSON syntax.
- **The `event_catalog` seed**: event type → family, action, default page type, funnel step, conversion flag. It's the single source of event semantics.
- **`staging.stg_clickstream`**: one row per `event_id`, with the hot columns typed, plus `page_type`, `family` and `action`.
- **`staging.stg_events__{navigation,cart,checkout}`**: three views, one per family, with that family's properties as typed columns.
- **Tests** on every model and the seed, plus a source freshness check on the raw table.

## 2. Scope
- **In:**
  - The dbt project, the `local` profile, `dbt_utils` and the source definition with freshness (T6.1)
  - The `json_get` macro: a Postgres implementation, plus a BigQuery implementation that isn't exercised until Phase 8 (T6.2)
  - The `event_catalog` seed, `stg_clickstream` and the three family models with their YAML tests (T6.3)
  - A portability guard: no dialect-specific SQL outside `dbt/macros/`
- **Out:**
  - Intermediate models, dimensions and facts (`dbt-sessions-funnel` T6.4–T6.5, `dbt-commerce-marts` T6.6)
  - The `page_types` seed and the `intermediate` schema (`dbt-sessions-funnel`)
  - Scheduling (`airflow-transform-dag`, T7.2)
  - The `bigquery` target (Phase 8, T8.5)

## 3. Implementation definition
- **Tooling:**
  - `dbt-core` and `dbt-postgres` live in the uv dependency group `dbt`, which is a default group. The versions are pinned in `versions.env`.
  - `dbt_utils` is pinned in `dbt/packages.yml`, and `package-lock.yml` is committed.
- **Run:**
  - `make dbt ARGS="<command>"`, which defaults to `build`. It loads `.env.<ENV>` and runs `uv run dbt <command> --profiles-dir .` from inside `dbt/`.
- **Profile** (`dbt/profiles.yml`):
  - The `local` target (postgres) parses `DBT_WAREHOUSE_DSN` into user, password, host, port and database. Terraform passwords are alphanumeric, so splitting the URL is safe.
  - The default schema is `staging`.
  - `DBT_TARGET` selects the target and defaults to `local`.
- **Schemas:** a `generate_schema_name` override puts models in the schema they name (`staging`, and later `intermediate` and `marts`), not in `<target>_<name>`. `staging` and `marts` already exist and are owned by `dbt_runner` (`infra-local-resources`).
- **Source:**
  - `raw.clickstream_events`; the schema comes from `WAREHOUSE_RAW_SCHEMA`.
  - Freshness is measured on `ingested_at`: it warns after 30 minutes and errors after 2 hours.
- **Macro:** `dbt/macros/json_get.sql`. `json_get(column, path, type)` takes a dotted path (`'properties.unit_price.amount_minor'`) and a portable type name (`string`, `integer`, `bigint`). It dispatches on `target.type`:
  - `postgres__json_get` uses `#>>` with a cast.
  - `bigquery__json_get` uses `JSON_VALUE` with `SAFE_CAST`.
- **Seed** `dbt/seeds/event_catalog.csv` (schema `staging`) with the columns and rows of spec 06 §5.1, and explicit column types in `dbt_project.yml`.
- **Models** (`dbt/models/staging/`, views, spec 06 §5.1):
  - `stg_clickstream`:
    - Selects the D11 columns from the source and keeps the row with the earliest `ingested_at` per `event_id` (`ROW_NUMBER()`).
    - Keeps only supported `schema_version`s (`'1'`, held in the project variable `supported_schema_versions`).
    - Adds `page_url` and `page_type` (`properties.page` for `page_view`, otherwise `default_page_type`), joins `event_catalog` for `family` and `action`, and keeps `payload` for the family views.
    - The join is a left join, so an unmapped event type still appears and fails the `relationships` test instead of silently disappearing.
  - `stg_events__navigation`, `stg_events__cart`, `stg_events__checkout`: select from `stg_clickstream` where `family = '<family>'`, with `event_id`, `event_ts`, `action` and the typed properties of spec 06 §5.1.
- **Tests** (`_staging.yml`, `_seeds.yml`), as spec 06 §7:
  - `event_catalog`: `unique` on `event_type`, `accepted_values` on `family`.
  - `stg_clickstream`: `unique` + `not_null` on `event_id`; `relationships` from `event_type` to `event_catalog`; `not_null` on `user_id`, `session_id`, `event_ts`, `family`, `action`, `page_type`.
  - Each family model: `unique` + `not_null` on `event_id`, `accepted_values` on `action`, and `not_null` on each required property for its action (`dbt_utils.expression_is_true`).
  - A `warn`-severity singular test that lists raw rows with an unsupported `schema_version`.
- **Portability guard:** E2E-2 scans `dbt/models/` for dialect-specific tokens (`::`, `#>>`, `->>`, `JSON_VALUE`, `SAFE_CAST`, and so on).

## 4. Interfaces
- **Consumes:**
  - `warehouse.raw.clickstream_events` (`ingest-consumer`)
  - The `dbt_runner` role, `DBT_WAREHOUSE_DSN` and `WAREHOUSE_RAW_SCHEMA` (`infra-local-resources`)
- **Produces:**
  - In `warehouse.staging`: the `event_catalog` seed table and the views `stg_clickstream` and `stg_events__{navigation,cart,checkout}`
  - Read by `dbt-sessions-funnel` and `dbt-commerce-marts`

## 5. E2E test flows
**E2E-1: staging from raw.**
1. Bring up the local environment.
2. Publish one journey-1 session (home, search, product view, add twice, remove, re-add, checkout start, purchase) through Kafka and run the ingest consumer until the events are in the raw table.
3. Run `make dbt ARGS=deps` and `make dbt ARGS="build --select +staging"` (the staging models plus their seed and source). The build passes, including every test.
4. `stg_clickstream` has each `event_id` exactly once, with the hot columns equal to the raw ones, and the right `family`, `action` and `page_type` for each event.
5. Each family view has exactly that family's events, with the expected `action` and typed values: money split into amount and currency, quantity, query, page and so on.

**E2E-2: rerun, unsupported version and portability.**
1. Run `dbt build` twice. The second run changes nothing and its tests stay green.
2. Insert a raw row with an unsupported `schema_version`. After the next build it doesn't appear in staging, and the `warn` test reports it without failing the build.
3. No dialect-specific SQL appears in `dbt/models/`.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=dbt-foundations`.

## 7. Open items
None. The staging data model was reviewed and settled as D12 (per-family staging).
