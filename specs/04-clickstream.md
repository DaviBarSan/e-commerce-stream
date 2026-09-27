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
The schema is JSON Schema (draft 2020-12), stored in `telemetry/schemas/event.v1.json`. It is the source of truth. The Python model in `telemetry/schema.py` mirrors it, and a parity test keeps them in agreement.

### 3.1 Envelope
| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | `"1"` |
| `event_id` | string (UUID) | yes | Deterministic (D13): UUIDv5 of the request's idempotency key plus `event_type`, see §3.4. The deduplication key. |
| `event_type` | enum | yes | See §4 |
| `event_ts` | string (RFC 3339, UTC, `Z` suffix) | yes | When the action happened (server time, since the backend emits) |
| `produced_at` | string (RFC 3339, UTC, `Z` suffix) | yes | When the producer serialized the event |
| `user_id` | string | yes | `anon-<uuid>` for anonymous users |
| `anonymous_id` | string or null | no | Reserved for identity stitching (journey 5, `PLAN.md` §9) |
| `session_id` | string | yes | Supplied by the client (spec 02 §6) |
| `page_url` | string | yes | |
| `product_id` | string or null | per type | Top-level join key (D10), required for product events (§4) |
| `cart_id` | string or null | per type | Top-level join key (D10), required for cart events (§4) |
| `order_id` | string or null | per type | Top-level join key (D10), required for `purchase` |
| `properties` | object | yes | Details for the event type; required keys per type (§4). Extra keys are allowed (additive). |
| `context` | object | no | Reserved for the future journeys (`request_id`, UTM, referrer, traffic labels). Free-form in v1. |

Unknown top-level fields are allowed, so a producer on a newer v1 (additive) doesn't break an older consumer.

### 3.2 Money
Amounts are never floats. A money value is `{ "amount_minor": <integer >= 0>, "currency": "<ISO 4217, 3 upper-case letters>" }`, for example `{ "amount_minor": 1999, "currency": "EUR" }` for 19.99 EUR.

### 3.3 Example
```json
{
  "schema_version": "1",
  "event_id": "2f1c9f0e-3c1a-5b8e-9d7a-6a2d8e4b1c11",
  "event_type": "add_to_cart",
  "event_ts": "2026-09-27T14:03:11.412Z",
  "produced_at": "2026-09-27T14:03:11.430Z",
  "user_id": "anon-7d9e…",
  "session_id": "s-51c0…",
  "page_url": "/products/42",
  "product_id": "42",
  "cart_id": "c-88a1…",
  "properties": { "quantity": 1, "unit_price": { "amount_minor": 1999, "currency": "EUR" } }
}
```

### 3.4 Deterministic `event_id` (D13)
`event_id = uuid5(NAMESPACE, f"{idempotency_key}:{event_type}")`, where `NAMESPACE` is a fixed UUID defined in `telemetry/schema.py`. The frontend and the bots send an `Idempotency-Key` header with every user action (spec 02 §6), and the backend derives `event_id` from it. A retried request gives the same `event_id`, which the raw table's primary key drops (D11). If a request has no key, the backend generates one, so the event is still unique.

## 4. Event types
| `event_type` | Required top-level keys | Required `properties` |
|---|---|---|
| `page_view` | none | `page`: `home` \| `catalog` \| `cart` |
| `search` | none | `query` (string), `results_count` (integer ≥ 0) |
| `product_view` | `product_id` | `category` (string), `price` (money) |
| `add_to_cart` | `product_id`, `cart_id` | `quantity` (integer ≥ 1), `unit_price` (money) |
| `remove_from_cart` | `product_id`, `cart_id` | none |
| `checkout_start` | `cart_id` | `items_count` (integer ≥ 1), `cart_total` (money) |
| `purchase` | `cart_id`, `order_id` | `total` (money) |

The analytics funnel (journey 1) is: `search → product_view → add_to_cart → purchase` (spec 06). New event types for journeys 2–10 (`PLAN.md` §9) are additive within v1.

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
- Whether to move to Avro or Protobuf with a schema registry later (not needed for v1).
- The derived-events contract for the stream processor (future iteration, `PLAN.md` §8).
