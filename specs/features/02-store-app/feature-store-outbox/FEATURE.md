# F02.4: Store Outbox (transactional outbox for state-change events)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [02](../../../02-store-app.md) | T3.7 | store-api, ingest-consumer | 3 |

## 1. Goal
Make every database change in the store reach the event stream, even across broker outages and API crashes, so the warehouse never under-reports carts or sales (D15). Today the API commits and then publishes asynchronously, so an event can be lost after its change is committed. Only state-change events move to the outbox; browsing events keep the cheap direct path.

### What it builds
- **An outbox table** `store.outbox_events`, written in the same transaction as the cart or order change.
- **A relay** in the API process that publishes outbox rows through `EventProducer` and deletes them once the broker has acknowledged them.
- **Two emit paths** in the telemetry hooks: in-transaction (outbox) for `add_to_cart`, `remove_from_cart` and `purchase`, and direct for the rest.

## 2. Scope
- **In:**
  - The `OutboxEvent` model and table
  - `emit_in_tx()`, plus moving `db.commit()` after it in the three state-change endpoints
  - The relay: batching, `SKIP LOCKED`, delete on acknowledgment, adaptive polling, clean shutdown
  - Structured logs for the relay
- **Out:**
  - Browsing events (they stay on the direct path, spec 04 §7)
  - Order status events or CDC (journey 10, parked)
  - Running the API in a container (`store-deploy`)

## 3. Implementation definition
- **Model** (`services/store_backend/store_backend/models.py`): `OutboxEvent`, table `outbox_events`, with:
  - `seq` (identity primary key, the publish order)
  - `event_id` (unique)
  - `payload` (JSON: the serialized, validated event)
  - `created_at`

  It's created by the existing `create_schema(engine)`, and the store tables need no other change.
- **Hooks** (`store_backend/telemetry_hooks.py`):
  - `emit()` is unchanged: build the event with `telemetry.build_event` (D13 `event_id`), then publish directly.
  - New `emit_in_tx(db, request, event_type, default_page_url, **fields)`:
    - Builds the event the same way and validates it on its wire bytes (`serialize_event` + `validate_payload`, the single producer-side check).
    - Adds an `outbox_events` row to the request's session with `INSERT … ON CONFLICT (event_id) DO NOTHING`, so a retried request adds nothing.
    - Doesn't commit.
- **Routers:** `cart.add_item`, `cart.remove_item` and `checkout.checkout_complete` call `emit_in_tx` before `db.commit()`, so the change and its event commit together. Every other endpoint keeps `emit()`.
- **Relay** (`store_backend/outbox.py`): an asyncio task started and stopped by the FastAPI `lifespan` (`store_backend/main.py`). It works off the event loop in a worker thread and uses its own DB session. Each cycle is one transaction:
  1. Runs `SELECT … ORDER BY seq LIMIT :batch FOR UPDATE SKIP LOCKED`, with a batch size of 500. `SKIP LOCKED` means several API replicas can share the work safely.
  2. For each row, hands the stored payload to the producer, then calls `flush(timeout)`.
  3. If `flush()` returns 0 and the producer's `stats().failed` and `stats().dropped` didn't grow during the cycle, deletes the batch and commits. Otherwise it rolls back, so the rows stay for the next cycle.
  4. Re-polls immediately after a full batch, and otherwise sleeps `OUTBOX_POLL_SECONDS` (default 1).

  Duplicates caused by a retry (a batch partly delivered, then rolled back) are dropped by the raw table's primary key (D11).
- **Producer:** `EventProducer` gets a `send_payload(event_id, session_id, payload)` method that publishes already-validated bytes, with the Kafka key and headers from the payload, so the relay doesn't re-build events. No other driver change is needed.
- **Logs:** one JSON line per non-empty cycle: `published`, `pending_after`, `cycle_ms`, `outcome` (`committed` / `rolled_back`).
- **Config:** `OUTBOX_BATCH_SIZE` (default 500) and `OUTBOX_POLL_SECONDS` (default 1), both optional with defaults (spec 02 §8).

## 4. Interfaces
- **Consumes:**
  - The `store` database and the `store_app` role (`infra-local-resources`)
  - `EventProducer` (`telemetry-producer`)
- **Produces:**
  - The `store.outbox_events` table
  - State-change events on `clickstream.events.v1`, now delivered at least once across outages and crashes. They're read by `ingest-consumer` and, in the warehouse, by `dbt-commerce-marts`.

## 5. E2E test flows
The flows run the API on the host (`ApiServer` in `tests/e2e/e2e_support.py`) and read Kafka from the topic's end offsets at the start of each test.

**E2E-1: state changes go through the outbox, browsing doesn't.**
1. Run a journey-1 session through the API: home, product view, add twice, remove, purchase.
2. Within 10 seconds, Kafka has every event of the session exactly once, in per-session order.
3. `store.outbox_events` is empty afterwards.
4. The relay log shows the cart and purchase events published from the outbox. The `page_view` and `product_view` events never appear in the outbox; this is checked with a statement-level row counter on the table during the run.

**E2E-2: a crash during a broker outage loses nothing.**
1. Stop the Kafka container.
2. Add to cart and complete a purchase. Both requests succeed quickly, and `store.outbox_events` holds their two events.
3. Kill the API process hard (no shutdown), so any in-memory producer buffer is gone.
4. Start Kafka, start the API again, and run the ingest consumer.
5. Both events are in `raw.clickstream_events` exactly once, and the outbox is empty.
6. Rerun the flows of `store-api`, `store-frontend` and `ingest-consumer`; they all still pass.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=store-outbox`, the reruns in E2E-2 step 6 pass, and `scripts/check_sdk_imports.py` passes.

## 7. Open items
None. Journey 10 (order status events vs CDC) stays parked (`PLAN.md` §8).
