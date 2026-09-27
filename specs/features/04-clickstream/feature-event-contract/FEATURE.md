# F04.1: Event Contract v1

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [04](../../../04-clickstream.md) | T2.1 | infra-foundations | 2 |

## 1. Goal
Define the one versioned event contract (spec 04 §3–§4) as a JSON Schema plus a matching Python model, so the producer (store API) and the consumer (ingestion) validate events identically. It covers every journey-1 event, and it is shaped so the future journeys (`PLAN.md` §9) are additive.

## 2. Scope
- **In:**
  - `telemetry/schemas/event.v1.json` (JSON Schema draft 2020-12)
  - `telemetry/schema.py`: the typed `Event` model, JSON Schema validation, parsing, serialization, and `derive_event_id` (D13)
  - An example corpus: one valid example per event type, plus invalid examples with the reason each must fail
  - Packaging `telemetry` as an installable package in the root `pyproject.toml`
- **Out:**
  - `EventProducer`, `get_producer()` and the drivers (`telemetry-producer`)
  - Publishing to Kafka, the DLQ and consumer-side routing (ingestion features)
  - Journey 2–10 event types and the `context` shapes (future iteration)

## 3. Implementation definition
- **`telemetry/schemas/event.v1.json`:**
  - The envelope of spec 04 §3.1: required fields, UUID `event_id`, UTC RFC 3339 timestamps with a `Z` suffix, nullable `anonymous_id` / `product_id` / `cart_id` / `order_id`, free-form `context`.
  - `event_type` enum of the seven v1 types, with `if`/`then` rules per type for the required top-level keys and the required, typed `properties` (spec 04 §4).
  - A shared `money` definition: `amount_minor` integer ≥ 0 and `currency` matching `^[A-Z]{3}$`.
  - Unknown top-level and `properties` keys are allowed (additive changes stay v1).
- **`telemetry/schema.py`:**
  - Pydantic v2 models: one class per event type, combined into a discriminated union on `event_type`. Strict mode, so no silent type coercion (`"3"` is not an integer).
  - `validate_payload(dict)`: validates against the JSON Schema (the authoritative check, used by the consumer). Raises `EventValidationError` with the failing JSON path.
  - `parse_event(bytes | str | dict) -> Event` and `serialize_event(Event) -> bytes`: UTF-8 JSON, timestamps rendered with `Z`, `None` fields omitted.
  - `derive_event_id(idempotency_key, event_type) -> UUID`: `uuid5(EVENT_ID_NAMESPACE, f"{idempotency_key}:{event_type}")` with a fixed namespace constant.
- **`telemetry/schemas/examples/`:** `valid/<event_type>.json` (seven files) and `invalid/<reason>.json`, where the file name states why it must fail (for example `money_as_float.json`).
- **`pyproject.toml`:** a hatchling build that packages `telemetry`, so `uv sync` installs it. Runtime dependencies: `pydantic`, `jsonschema[format-nongpl]`.

## 4. Interfaces
- **Produces:**
  - The `telemetry.schema` module (`Event`, `EventType`, `validate_payload`, `parse_event`, `serialize_event`, `derive_event_id`), used by `telemetry-producer`, the store API and the ingest consumer.
  - `event.v1.json`, the source of truth for every producer and consumer, and the reference for the raw table (D11).

## 5. E2E test flows
**E2E-1: a journey-1 session travels through the contract.**
1. Build the journey-1 sequence for one session with the model: `page_view → search → product_view → add_to_cart → checkout_start → purchase`, with `event_id`s from `derive_event_id`.
2. Serialize each event to bytes (the wire format), validate the bytes against the JSON Schema, and parse them back.
3. The parsed events equal the originals, carry the same `session_id`, and carry the top-level keys the type requires (D10).
4. Every file in `examples/valid/` passes both the JSON Schema and the model, and together they cover every `event_type`.

**E2E-2: contract parity and determinism.**
1. Every file in `examples/invalid/` is rejected by **both** the JSON Schema and the model.
2. The model's `event_type` values equal the schema's enum, and the model's required envelope fields equal the schema's `required` list.
3. `derive_event_id` returns the same UUID for the same key and type (a retried request), and different UUIDs when the key or the type changes.
4. Additive tolerance: a valid event plus an unknown top-level field and an unknown `properties` key still passes both.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=event-contract`, and the earlier features' flows still pass.

## 7. Open items
None. The v1 decisions are D10 (top-level keys) and D13 (deterministic `event_id`).
