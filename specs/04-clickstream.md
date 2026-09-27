# Spec 04: Clickstream (Event Contract & Telemetry)

> Tasks: T2.1–T2.5, T3.3, T5.4, T8.3 (see `PLAN.md`)

## 1. Purpose
Define the **one event contract** and the **telemetry library** that publishes events to any streaming backend, without the calling code changing.

## 2. Scope
- **In scope:**
  - The event schema and its versioning
  - Event types
  - The `EventProducer` interface and drivers
  - Topics, partitioning and delivery semantics
  - Dead-letter rules
- **Out of scope:** consuming events and landing them in storage (spec 05).

## 3. Event schema v1
The schema is JSON Schema (draft 2020-12), stored in `telemetry/schemas/event.v1.json`. The Python model is generated from it or kept in sync with it.

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | `"1"` |
| `event_id` | string (UUIDv4) | yes | Created by the producer; the key used to deduplicate |
| `event_type` | enum | yes | See §4 |
| `event_ts` | string (RFC 3339, UTC) | yes | When the event happened |
| `user_id` | string | yes | `anon-<uuid>` for anonymous users |
| `session_id` | string | yes | Supplied by the client (spec 02 §6) |
| `page_url` | string | yes | |
| `metadata_json` | object | no | Details specific to the event type |

**Deferred:** whether `product_id` becomes a top-level field or stays in `metadata_json` (parking lot). Until that's decided, product-related events put `product_id` in `metadata_json`. Making it top-level later would be a v2 change, handled by the versioning rules in §8.

## 4. Event types
| `event_type` | Typical `metadata_json` |
|---|---|
| `page_view` | `{ "page": "home" \| "catalog" \| "cart" }` |
| `search` | `{ "query": "...", "results_count": n }` |
| `product_view` | `{ "product_id": "...", "category": "...", "price": x }` |
| `add_to_cart` | `{ "product_id": "...", "quantity": n, "unit_price": x }` |
| `remove_from_cart` | `{ "product_id": "..." }` |
| `checkout_start` | `{ "cart_id": "...", "items_count": n, "cart_total": x }` |
| `purchase` | `{ "order_id": "...", "cart_id": "...", "total": x }` |

The analytics funnel is: `search → product_view → add_to_cart → purchase` (spec 06).

## 5. Producer interface
```
telemetry/
  __init__.py        get_producer() factory, driven by STREAMING_BACKEND
  base.py            EventProducer (ABC)
  schema.py          Event model + validation
  kafka_driver.py    confluent-kafka
  gcp_driver.py      google-cloud-pubsub      (stub until Phase 8)
  aws_driver.py      boto3 kinesis            (standby stub)
  schemas/event.v1.json
```

`EventProducer` contract:
| Method | Behavior |
|---|---|
| `send_event(event: Event) -> None` | Validates, serializes and publishes asynchronously. Raises an error on validation failure. |
| `flush(timeout: float) -> int` | Blocks until pending messages are delivered, and returns how many are still undelivered |
| `close() -> None` | Flushes, then releases resources |

`get_producer()` reads `STREAMING_BACKEND` (`kafka` / `pubsub` / `kinesis`) and imports **only** the driver that's selected, so the SDKs for other clouds are optional dependencies.

## 6. Transport mapping
| Concept | Kafka (local) | Pub/Sub (GCP) | Kinesis (AWS, standby) |
|---|---|---|---|
| Events stream | topic `clickstream.events.v1` | topic `clickstream-events-v1` | stream `clickstream-events-v1` |
| Dead-letter queue | topic `clickstream.events.dlq` | dead-letter topic | separate stream |
| Ordering key | message key = `session_id` | `ordering_key` = `session_id` | partition key = `session_id` |
| Payload | UTF-8 JSON | UTF-8 JSON | UTF-8 JSON |
| Headers / attributes | `schema_version`, `event_type` | same attributes | not applicable |

Partitioning by `session_id` keeps each session in order, which the sessionization in spec 06 depends on.

## 7. Delivery semantics
- **At least once** from end to end:
  - The Kafka producer runs with `acks=all` and `enable.idempotence=true`.
  - Consumers commit only after the data is written (spec 05).
- Duplicates are expected and are removed downstream using `event_id` (spec 06 `stg_clickstream`).
- A failure to publish must **not** break the store's user request. The producer logs the error and counts it (metric or log), and the request still succeeds.

## 8. Schema versioning
- Additive, optional fields are allowed within v1.
- Any breaking change means a new version: `event.v2.json`, a new topic `clickstream.events.v2`, and running both versions side by side during migration.

## 9. Dead-letter rules
Events that fail validation at the **consumer** go to the DLQ topic along with:
- the original payload
- the error reason
- the source topic, partition and offset

Producer-side validation failures are bugs and raise an error in tests.

## 10. Acceptance criteria
1. Schema tests: valid samples of every event type pass, and invalid ones fail.
2. `get_producer()` returns the right driver for each `STREAMING_BACKEND`. Selecting `pubsub` or `kinesis` before they're provisioned raises a clear error.
3. Kafka integration: 1,000 events published → 1,000 or more consumed, with ordering preserved per `session_id`.
4. Business code can't import any cloud SDK except through `telemetry`.

## 11. Open items
- Where `product_id` goes (parking lot).
- Whether to move to Avro or Protobuf with a schema registry later (not needed for v1).
