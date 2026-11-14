# F05.5: Local End-to-End Run (bots → Kafka → raw → marts)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [05](../../../05-ingestion-orchestration.md) | T7.3 | airflow-transform-dag, ingest-deploy, bot-deploy, store-deploy, store-outbox | 7 |

## 1. Goal
Prove journey 1 works end to end on the local environment with every service in a container: bot traffic goes through the store, the events reach the marts within one DAG cycle, and the marts agree with the store database. Passing this feature is the gate for Phase 8 (D5).

## 2. Scope
- **In:**
  - The two E2E flows in `tests/e2e/local-e2e/`
  - Any small fix needed to make the deployed pieces work together, recorded in the owning feature's doc
- **Out:**
  - New services, models or DAGs
  - Bot ground-truth labels (`context.traffic`, parking lot): the flows identify the run's traffic by its time window and the run's users, not by a label
  - GCP (Phase 8)

## 3. Implementation definition
- **No new production code.** The flows only use what the dependencies provide:
  - `make up` (store app, consumer, Airflow in `30-services`)
  - `make bot` with a fixed `BOT_SEED`, profile and duration (F03.2)
  - The Airflow REST API (`AIRFLOW_API_URL`, `AIRFLOW_ADMIN_PASSWORD`)
  - Read-only queries on `store`, `warehouse` and the Kafka topics
- **Settings for the run:** `TF_VAR_transform_schedule="*/5 * * * *"` so "one DAG cycle" fits in a test; `RAW_FRESHNESS_MINUTES` keeps its default.
- **Run window:** the flows record the start and end of the bot run and compare the systems only inside that window, so leftover data from earlier runs doesn't affect the result.
- **Reconciliations** (the checks the flows share, in `tests/e2e/local-e2e/`):
  - Kafka vs raw: every event produced during the window (from the topic's offsets) is in `raw.clickstream_events` exactly once, except the ones routed to the DLQ, and the DLQ count is zero for bot traffic.
  - Store vs marts: every `store.orders` row created in the window appears in `fct_orders` with the same total, currency and line count (`fct_order_lines`).
  - Funnel sanity: `agg_funnel_daily` step counts never increase, and the number of sessions with a purchase equals the number of orders in the window.

## 4. Interfaces
- **Consumes:** every local service and the marts (F02.3, F02.4, F03.2, F05.2, F05.4, F06.1–F06.3).
- **Produces:** the green local run that unblocks Phase 8 (`infra-gcp-platform`, D5).

## 5. E2E test flows
**E2E-1: bot traffic reaches the marts within one DAG cycle.**
1. Run `make up` and unpause `clickstream_transform`.
2. Run `make bot BOT_PROFILE=steady BOT_DURATION=3m BOT_SEED=<fixed>`; it exits 0.
3. Within one scheduled cycle after the bot finishes (plus the consumer's flush interval), a scheduled DAG run that started after the bot run ended finishes `success`.
4. All three reconciliations pass for the run window.
5. Consumer lag on `clickstream-ingest` is zero at the end.

**E2E-2: the pipeline recovers from a consumer crash and a broker outage.**
1. Start a bot run (`BOT_DURATION=4m`). During the run, `docker kill` the consumer container, and separately stop the Kafka container for 30 seconds and start it again.
2. Cart and purchase requests made while Kafka is down still succeed (outbox, D15); browsing events from that gap may be missing (accepted by D15).
3. After the bot finishes and the outbox relay drains, one scheduled DAG run later:
   - Store vs marts passes for the whole window: no order is lost or doubled.
   - `raw.clickstream_events` has no duplicate `event_id`, and every outbox event in the window is in raw exactly once.
4. `make down` leaves no project container, network, volume or built image.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=local-e2e`. `STATUS.md` and `PLAN.md` mark T7.3 done, which opens Phase 8.

## 7. Open items
- Bot ground-truth labels stay parked (`PLAN.md` §8); these flows don't need them.
