# F06.1: dbt Foundations (project, JSON macro, staging layer)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| In progress | [06](../../../06-transformation.md) | T6.1, T6.2, T6.3 | infra-local-resources, ingest-consumer | 6 |

## 1. Goal
Turn the raw table `warehouse.raw.clickstream_events` (D11) into a clean, deduplicated, typed staging layer that every later model builds on: one view for all events plus one view per event type with its `properties` flattened (D12). This is the first transformation step of journey 1 (`PLAN.md` §9).

### What it builds
- **A dbt project** in `dbt/`, run with `make dbt ARGS="..."`, which loads `.env.<ENV>` so the profile reads only contract keys.
- **The `json_get(column, path, type)` macro**, the only place with dialect-specific JSON syntax.
- **`staging.stg_clickstream`**: one row per `event_id`, with the hot columns typed.
- **`staging.stg_events__<event_type>`**: seven views, one per event type, with that type's properties as columns.
- **Tests** on every model, plus a source freshness check on the raw table.

## 2. Scope
- **In:**
  - The dbt project, the `local` profile, `dbt_utils` and the source definition with freshness (T6.1)
  - The `json_get` macro: a Postgres implementation, plus a BigQuery implementation that isn't exercised until Phase 8 (T6.2)
  - `stg_clickstream` and the seven `stg_events__<type>` models with their YAML tests (T6.3)
  - A portability guard: no dialect-specific SQL outside `dbt/macros/`
- **Out:**
  - `int_sessions` and the marts (`dbt-sessions-marts`, T6.4–T6.5)
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
- **Schemas:** a `generate_schema_name` override puts models in the schema they name (`staging`, and later `marts`), not in `<target>_<name>`. Both schemas already exist and are owned by `dbt_runner` (`infra-local-resources`).
- **Source:**
  - `raw.clickstream_events`; the schema comes from `WAREHOUSE_RAW_SCHEMA`.
  - Freshness is measured on `ingested_at`: it warns after 30 minutes and errors after 2 hours.
- **Macro:** `dbt/macros/json_get.sql`. `json_get(column, path, type)` dispatches on `target.type`:
  - `postgres__json_get` uses `#>>` with a cast.
  - `bigquery__json_get` uses `JSON_VALUE` with `SAFE_CAST`.
- **Models:** **pending the staging data-model review** (columns, naming, materialization, how unsupported versions are handled).
- **Portability guard:** E2E-2 scans `dbt/models/` for dialect-specific tokens (`::`, `#>>`, `->>`, `JSON_VALUE`, `SAFE_CAST`, and so on).

## 4. Interfaces
- **Consumes:**
  - `warehouse.raw.clickstream_events` (`ingest-consumer`)
  - The `dbt_runner` role, `DBT_WAREHOUSE_DSN` and `WAREHOUSE_RAW_SCHEMA` (`infra-local-resources`)
- **Produces:**
  - Views in `warehouse.staging`: `stg_clickstream` and `stg_events__{page_view,search,product_view,add_to_cart,remove_from_cart,checkout_start,purchase}`
  - Read by `dbt-sessions-marts`

## 5. E2E test flows
**E2E-1: staging from raw.**
1. Bring up the local environment.
2. Publish one journey-1 session through Kafka and run the ingest consumer until the events are in the raw table.
3. Run `make dbt ARGS=deps` and `make dbt ARGS="build --select staging"`. The build passes, including every test.
4. `stg_clickstream` has each `event_id` exactly once, with the hot columns equal to the raw ones.
5. Each `stg_events__<type>` model has the expected typed values: money split into amount and currency, quantity, query, page, and so on.

**E2E-2: rerun, unsupported version and portability.**
1. Run `dbt build` twice. The second run changes nothing and its tests stay green.
2. Insert a raw row with an unsupported `schema_version`. After the next build it doesn't appear in staging, and the `warn` test reports it without failing the build.
3. No dialect-specific SQL appears in `dbt/models/`.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=dbt-foundations`.

## 7. Open items
- The staging data-model review, which you asked for before any model SQL is written.
