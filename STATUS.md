# Development Status

Living snapshot of where development stands and what comes next. Update it in the same change that moves a feature's status. `PLAN.md` and the `FEATURE.md` files stay the source of truth (`CLAUDE.md` §1); this file only summarizes them.

**Last updated:** 2026-11-14

## 1. Summary

Phases 0–2 are complete. Phase 3 is done (the store runs as containers under `make up`, #14); Phase 5 is done (the consumer runs as a container, #15); Phase 6 is done (#13); Phase 7 has Airflow (T7.1, #11) and the transform DAG (T7.2, PR pending); only the local end-to-end run (T7.3) remains. The MVP gate (T7.3, the local end-to-end run) is still several features away. Priority for the remaining local work: **orchestration (Airflow) first, traffic bots last** before T7.3.

## 2. Feature board

| Feature | Tasks | Status | Unblocked? |
|---|---|---|---|
| F01.1 infra-foundations | T0.1–T0.5 | Done | n/a |
| F01.2 infra-local-platform | T1.1–T1.4 | Done (rerun green 2026-11-14) | n/a |
| F01.3 infra-local-resources | T1.5–T1.9 | Done (rerun green 2026-11-14) | n/a |
| F04.1 event-contract | T2.1 | Done | n/a |
| F04.2 telemetry-producer | T2.2–T2.5 | Done | n/a |
| F02.1 store-api | T3.1–T3.3 | Done | n/a |
| F02.2 store-frontend | T3.4 | Done | n/a |
| F05.1 ingest-consumer | T5.1, T5.2, T5.4 | Done | n/a |
| F06.1 dbt-foundations | T6.1–T6.3 | Done | n/a |
| F06.2 dbt-sessions-funnel | T6.4, T6.5 | Done (merged, #10) | n/a |
| F05.3 airflow-local | T7.1 | Done (merged, #11) | n/a |
| F02.4 store-outbox | T3.7 | Done (merged, #12) | n/a |
| F06.3 dbt-commerce-marts | T6.6 | Done (merged, #13) | n/a |
| F05.4 airflow-transform-dag | T7.2 | Done on `feature/airflow-transform-dag` (7/7), PR pending | n/a |
| F02.3 store-deploy | T3.5, T3.6 | Done (merged, #14) | n/a |
| F05.2 ingest-deploy | T5.3 | Done (merged, #15) | n/a |
| F03.1 bot-simulation | T4.1, T4.2 | Not started (lowered priority) | yes |
| F03.2 bot-deploy | T4.3 | Not started (lowered priority) | no: F03.1 + F02.3 |
| F05.5 local-e2e | T7.3 | Not started | no: F05.4 + F05.2 + F03.2 + F02.3 + F02.4 |
| Phase 8 (F01.4 gcp-platform, telemetry-pubsub, F05.6, F06.4) | T8.* | Not scheduled | no: local end-to-end green (D5) |

## 3. Loose ends

- [x] Merge `feature/dbt-sessions-funnel` into `main` (PR #10, squash `99604c5`).
- [x] Rerun `make e2e FEATURE=infra-local-platform` and `make e2e FEATURE=infra-local-resources` on `feature/dbt-sessions-funnel`: both 9/9 passed (2026-11-14). F06.2 touches `terraform/envs/local/20-resources/postgres.tf` and the `infra-local-platform` E2E-1 flow, and the reruns were also skipped when telemetry-producer closed (its §7).
- [x] Fix the cold-broker race in the shared E2E helper and rerun the features that use it. The first F06.2 run on a fresh broker failed its E2E-1 setup with `NOT_COORDINATOR` on the first offset commit while `__consumer_offsets` was being created (E2E-2 passed). `start_group_at_end` in `tests/e2e/e2e_support.py` now retries coordinator errors by code for up to 30 s (librdkafka doesn't flag them retriable on a manual commit). From a fresh `make down`: `dbt-sessions-funnel` 9/9, `ingest-consumer` 6/6, `dbt-foundations` 8/8 (2026-11-14).
- [x] Remove the stale worktrees and the merged local branches (`dbt-foundations`, `dbt-sessions-funnel`). The remote branches `origin/feature/dbt-foundations` and `origin/feature/dbt-sessions-funnel` are still on GitHub.
- [ ] Upgrading an environment created before `airflow-local`: its first `make down` fails in `20-resources` (missing `airflow_host_port` in the old `10-platform` state). Run `make up` once first; it refreshes `10-platform`. Seen once on this machine, now resolved.

## 4. Next steps (priority order)

1. ~~**Merge F06.2 dbt-sessions-funnel**~~ Done 2026-11-14 (#10).
2. ~~**Write the spec 05 orchestration feature docs.**~~ Done 2026-11-14 (approved, committed `3ff8adf`): F05.2 `ingest-deploy`, F05.3 `airflow-local`, F05.4 `airflow-transform-dag`, F05.5 `local-e2e`. Decisions recorded in `PLAN.md`:
   - **D16:** service containers live in a new `envs/local/30-services` stack (spec 01 §3; F02.3's open item closed).
   - **D17:** Airflow runs dbt with a `BashOperator`, using dbt in its own virtualenv inside the Airflow image, with the project baked in (spec 05 §7).
3. ~~**F05.3 airflow-local (T7.1).**~~ Done 2026-11-14 (#11). Airflow `3.3.2-python3.12`, `30-services` stack, dbt `1.12.5` in `/opt/dbt-venv`.
4. ~~**F02.4 store-outbox (T3.7).**~~ Done 2026-11-14 (#12).
5. ~~**F06.3 dbt-commerce-marts (T6.6).**~~ Done 2026-11-14 (#13).
6. ~~**F02.3 store-deploy (T3.5, T3.6).**~~ Done 2026-11-14 (#14). The storefront on `:3000` and the API on `:8000` under `make up`.
7. ~~**F05.2 ingest-deploy (T5.3).**~~ Done 2026-11-14 (#15). clicks reach `raw.clickstream_events` without a host process.
8. **(Current)** **F05.4 airflow-transform-dag (T7.2).** Implemented and green on `feature/airflow-transform-dag`; PR next. freshness check, one `dbt build` task per layer, run summary, and per-run dbt artifacts in `airflow-runs/` (owner's choice, for debugging).
9. **F03.1 bot-simulation (T4.1, T4.2)**, then **F03.2 bot-deploy (T4.3)**. Suggested default for spec 03 §10: API mode only.
10. **F05.5 local-e2e (T7.3).** The MVP gate; opens Phase 8 (D5).

### Notes on the order

- **Reordered 2026-11-14 for hands-on use:** store-deploy → ingest-deploy → transform DAG, so the owner can click through the storefront, see the events in raw, then run the DAG and debug it. No dependency changes.

- **Bots are deferred, not dropped.** T7.3 depends on T4.3, so the bots must land before the local end-to-end run.

## 5. Parking lot

Nothing blocks local work. Open `PLAN.md` §8 entries gate Phase 8 and later only: GCP orchestration, GCP ingestion, AWS terms, stream processor, derived-events contract, journey 10 scope, bot ground-truth labels.

## 6. Log

| Date | Change |
|---|---|
| 2026-11-14 | Status file created. Airflow raised to steps 2–3; bot simulation lowered to step 9. |
| 2026-11-14 | Step 1: regression reruns green (infra-local-platform, infra-local-resources, ingest-consumer, dbt-foundations); E2E helper cold-broker race fixed; dbt-sessions-funnel 9/9. Branch pushed, PR pending. |
| 2026-11-14 | Step 1 closed: PR #10 merged (`99604c5`), `main` in sync, worktrees and local branches cleaned. Step 2 started on `feature/airflow-local`. |
| 2026-11-14 | Step 2 drafted: D16 (`30-services`) and D17 (dbt via `BashOperator` in the Airflow image); specs 01 and 05 updated; feature docs F05.2–F05.5 written; F02.3 and F03.2 point at `30-services`. Awaiting review. |
| 2026-11-14 | Step 2 approved and pushed (`3ff8adf`). Step 3 (F05.3 airflow-local) implemented: `make e2e FEATURE=airflow-local` 9/9; regressions infra-local-platform 9/9, infra-local-resources 9/9, dbt-foundations 8/8. T7.1 ticked in `PLAN.md`. PR pending. |
| 2026-11-14 | PR #11 opened for `feature/airflow-local` (step 2 docs + F05.3). |
| 2026-11-14 | PR #11 merged (`cdf76c2`); `feature/airflow-local` deleted locally and on GitHub. Step 4 (F02.4 store-outbox) started on `feature/store-outbox`. |
| 2026-11-14 | Step 4 (F02.4 store-outbox) implemented: `store-outbox` 5/5; regressions telemetry-producer 11/11, store-api 7/7, store-frontend 6/6, ingest-consumer 6/6. Spec 04 §6 now states the D15 ordering consequence (order per delivery path; consumers order by `event_ts`), and the store-api flow checks order per path. T3.7 ticked. PR pending. |
| 2026-11-14 | PR #12 opened for `feature/store-outbox` (F02.4). |
| 2026-11-14 | PR #12 merged (`8c84efa`); `feature/store-outbox` deleted. Step 5 (F06.3 dbt-commerce-marts) started on `feature/dbt-commerce-marts`. |
| 2026-11-14 | Step 5 (F06.3 dbt-commerce-marts) implemented: `dbt-commerce-marts` 6/6. Fixes on the way: the outbox relay drains on shutdown; the `ingest-consumer` and `telemetry-producer` E2E-2 fixtures build coherent carts (local env reset once to drop the incoherent history); the line-total test reads only `fct_orders` (new `purchase_total_minor`). Regressions: dbt-sessions-funnel 9/9, dbt-foundations 8/8, store-outbox 5/5, ingest-consumer 6/6, telemetry-producer 11/11. T6.6 ticked. PR pending. |
| 2026-11-14 | PR #13 opened for `feature/dbt-commerce-marts` (F06.3). |
| 2026-11-14 | PR #13 merged (`5fa8a4a`); Phase 6 complete. Steps reordered for hands-on use (store-deploy → ingest-deploy → transform DAG). Step 6 (F02.3 store-deploy) started on `feature/store-deploy`. |
| 2026-11-14 | Step 6 (F02.3 store-deploy) implemented: `store-deploy` 6/6. Images pinned on `python:3.12.15-slim-bookworm` and `uv:0.13.4`; host-run test servers moved to :18000 / :13000. Fixes on the way: the API venv is built at its final path (`/opt/venv`); the storefront healthcheck's `start_period` is written as `1m0s`. An interrupted apply left an untracked `store-api` container, removed by hand. Regressions: store-api 7/7, store-frontend 6/6, store-outbox 5/5, dbt-commerce-marts 6/6, airflow-local 9/9, infra-local-resources 9/9, infra-local-platform 9/9. T3.5–T3.6 ticked. PR pending. |
| 2026-11-14 | PR #14 opened for `feature/store-deploy` (F02.3). |
| 2026-11-14 | PR #14 merged (`adce61f`); Phase 3 complete. Step 7 (F05.2 ingest-deploy) started on `feature/ingest-deploy`. Regression phases now rerun only the features a change affects (owner's request). |
| 2026-11-14 | Step 7 (F05.2 ingest-deploy) implemented: `ingest-deploy` 7/7 (one fix: the replicas test waits for a stable 3-member group before publishing). Regression scoped to the one affected feature: ingest-consumer 6/6 (its flush-log check counts inserts plus duplicates). T5.3 ticked; Phase 5 complete. PR pending. |
| 2026-11-14 | PR #15 opened for `feature/ingest-deploy` (F05.2). |
| 2026-11-14 | PR #15 merged (`da59922`); Phase 5 complete. Step 8 (F05.4) started on `feature/airflow-transform-dag`; its doc now has one task per dbt layer and a host artifacts folder (owner's choice). |
| 2026-11-14 | Step 8 (F05.4 airflow-transform-dag) implemented: `airflow-transform-dag` 7/7 (one test fix: XCom dict keys come back reordered). Regressions (affected only): dbt-foundations 8/8, airflow-local 9/9. T7.2 ticked. PR pending. |
