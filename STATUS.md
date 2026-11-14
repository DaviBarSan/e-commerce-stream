# Development Status

Living snapshot of where development stands and what comes next. Update it in the same change that moves a feature's status. `PLAN.md` and the `FEATURE.md` files stay the source of truth (`CLAUDE.md` §1); this file only summarizes them.

**Last updated:** 2026-11-14

## 1. Summary

Phases 0–2 are complete. Phase 3 has the API and frontend done; Phases 5 and 6 are partly done. The MVP gate (T7.3, the local end-to-end run) is still several features away. Priority for the remaining local work: **orchestration (Airflow) first, traffic bots last** before T7.3.

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
| F06.2 dbt-sessions-funnel | T6.4, T6.5 | Done on `feature/dbt-sessions-funnel`, flows green; **PR to merge** | n/a |
| F05.x airflow-local | T7.1 | No feature doc yet | yes (needs T1.5 only) |
| F02.4 store-outbox | T3.7 | Not started | yes |
| F06.3 dbt-commerce-marts | T6.6 | Not started | no: F06.2 merged + F02.4 |
| F05.x airflow-transform-dag | T7.2 | No feature doc yet | no: T7.1 + T6.6 |
| F02.3 store-deploy | T3.5, T3.6 | Not started | yes |
| F05.x consumer-deploy | T5.3 | No feature doc yet | yes |
| F03.1 bot-simulation | T4.1, T4.2 | Not started (lowered priority) | yes |
| F03.2 bot-deploy | T4.3 | Not started (lowered priority) | no: F03.1 + F02.3 |
| F05.x local-e2e | T7.3 | No feature doc yet | no: T7.2 + T4.3 + T5.3 |
| Phase 8 (F01.4 gcp-platform, telemetry-pubsub, F05.6, F06.4) | T8.* | Not scheduled | no: local end-to-end green (D5) |

## 3. Loose ends

- [ ] Merge `feature/dbt-sessions-funnel` (commit `c5d062e`) into `main`.
- [x] Rerun `make e2e FEATURE=infra-local-platform` and `make e2e FEATURE=infra-local-resources` on `feature/dbt-sessions-funnel`: both 9/9 passed (2026-11-14). F06.2 touches `terraform/envs/local/20-resources/postgres.tf` and the `infra-local-platform` E2E-1 flow, and the reruns were also skipped when telemetry-producer closed (its §7).
- [x] Fix the cold-broker race in the shared E2E helper and rerun the features that use it. The first F06.2 run on a fresh broker failed its E2E-1 setup with `NOT_COORDINATOR` on the first offset commit while `__consumer_offsets` was being created (E2E-2 passed). `start_group_at_end` in `tests/e2e/e2e_support.py` now retries coordinator errors by code for up to 30 s (librdkafka doesn't flag them retriable on a manual commit). From a fresh `make down`: `dbt-sessions-funnel` 9/9, `ingest-consumer` 6/6, `dbt-foundations` 8/8 (2026-11-14).
- [ ] Remove the stale worktrees `.claude/worktrees/dbt-foundations` (merged as #9) and `.claude/worktrees/dbt-sessions-funnel` (after the merge).

## 4. Next steps (priority order)

1. **Merge F06.2 dbt-sessions-funnel**, after the regression reruns above; then clean up the worktrees.
2. **Write the spec 05 orchestration feature docs**: `airflow-local` (T7.1) and `airflow-transform-dag` (T7.2) first; `consumer-deploy` (T5.3) and `local-e2e` (T7.3) in the same pass. The `airflow-local` doc settles:
   - dbt execution: `BashOperator` (dbt in the Airflow image) or `DockerOperator` (spec 05 §7).
   - Where service containers live: `10-platform` or a new `30-services` stack. Airflow is now the first service container, so this decision moves here from F02.3; record it in spec 01.
3. **F05.x airflow-local (T7.1).** Done when the Airflow UI opens on `:8080` with metadata in the `airflow` database.
4. **F02.4 store-outbox (T3.7).** Gates the commerce marts.
5. **F06.3 dbt-commerce-marts (T6.6).**
6. **F05.x airflow-transform-dag (T7.2).** Freshness check, `dbt build`, `dbt test`; needs T7.1 and T6.6.
7. **F02.3 store-deploy (T3.5, T3.6)**, following the stack layout chosen in step 2.
8. **F05.x consumer-deploy (T5.3).**
9. **F03.1 bot-simulation (T4.1, T4.2)**, then **F03.2 bot-deploy (T4.3)**. Suggested default for spec 03 §10: API mode only.
10. **F05.x local-e2e (T7.3).** The MVP gate; opens Phase 8 (D5).

### Notes on the order

- **Bots are deferred, not dropped.** T7.3 depends on T4.3, so the bots must land before the local end-to-end run.
- **The DAG still waits on the commerce marts.** `PLAN.md` has T7.2 depend on T6.6. Starting the DAG against the F06.2 session marts and adding the commerce models later would need that dependency changed in `PLAN.md` (open, owner's call).

## 5. Parking lot

Nothing blocks local work. Open `PLAN.md` §8 entries gate Phase 8 and later only: GCP orchestration, GCP ingestion, AWS terms, stream processor, derived-events contract, journey 10 scope, bot ground-truth labels.

## 6. Log

| Date | Change |
|---|---|
| 2026-11-14 | Status file created. Airflow raised to steps 2–3; bot simulation lowered to step 9. |
| 2026-11-14 | Step 1: regression reruns green (infra-local-platform, infra-local-resources, ingest-consumer, dbt-foundations); E2E helper cold-broker race fixed; dbt-sessions-funnel 9/9. Branch pushed, PR pending. |
