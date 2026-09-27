# F04.2: Telemetry Producer (EventProducer + Kafka driver)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [04](../../../04-clickstream.md) | T2.2–T2.5 | event-contract, infra-local-resources | 2 |

## 1. Goal
Give the store backend one cloud-agnostic way to publish contract events: `get_producer()` returns an `EventProducer` for the backend named by `STREAMING_BACKEND`. The Kafka driver delivers at least once, keeps each session in order, and never breaks a user request when the broker is down.

## 2. Scope
- **In:**
  - `telemetry/base.py`: the `EventProducer` abstract base class, error types and delivery stats
  - `get_producer()` in `telemetry/__init__.py`, with lazy driver imports
  - `telemetry/kafka_driver.py` (confluent-kafka)
  - `telemetry/gcp_driver.py` and `telemetry/aws_driver.py`: stubs that raise a clear "not provisioned" error
  - The SDK-import boundary check (spec 04 §10.4)
- **Out:**
  - The real Pub/Sub driver (`telemetry-pubsub`, Phase 8) and the Kinesis driver (Phase 9)
  - Emitting events from the API (`store-api`), consuming and the DLQ (ingestion features)

## 3. Implementation definition
- **`telemetry/base.py`:**
  - `EventProducer` (ABC): `send_event(event) -> None`, `flush(timeout) -> int`, `close() -> None`, plus `stats() -> DeliveryStats` (`sent`, `delivered`, `failed`, `dropped`). It works as a context manager (`close()` on exit).
  - `send_event` serializes the event and checks the bytes against the JSON Schema (`validate_payload`, the single producer-side check), then hands them to the driver. It raises `EventValidationError` on invalid events, and **never raises for transport problems**: those are logged and counted (spec 04 §7).
  - Errors: `TelemetryConfigError` (missing or invalid settings), `NotProvisionedError` (backend not available yet).
- **`get_producer(env=os.environ)`:**
  - Reads only contract keys: `STREAMING_BACKEND`, `EVENTS_TOPIC`, and the backend's own keys (`KAFKA_BOOTSTRAP_SERVERS` for Kafka).
  - Imports only the selected driver module. `import telemetry` loads no cloud SDK.
  - An unknown backend or a missing key raises `TelemetryConfigError` naming the key.
- **`telemetry/kafka_driver.py`** (spec 04 §6–§7):
  - Producer settings: `acks=all`, `enable.idempotence=true`, `compression.type=zstd`, `linger.ms=5`, `message.timeout.ms=120000` (a broker outage shorter than two minutes loses nothing).
  - Message key `session_id`. Headers `schema_version`, `event_type`, `content-type: application/json`. Value: the serialized event.
  - Asynchronous: `send_event` enqueues and serves delivery callbacks with `poll(0)`. The callback counts `delivered` and `failed` and logs failures with `event_id`.
  - Local queue full (`BufferError`): serve callbacks and retry once, then drop the event, count it as `dropped` and log it.
- **`telemetry/gcp_driver.py`, `telemetry/aws_driver.py`:** importing them costs nothing. Creating a producer raises `NotProvisionedError` naming the phase that delivers it (`telemetry-pubsub`, Phase 8; Kinesis, Phase 9).
- **`scripts/check_sdk_imports.py`:** fails if `confluent_kafka`, `google.cloud` or `boto3` is imported anywhere outside `telemetry/*_driver.py`, `services/*/app/sources/*`, `services/*/app/sinks/*`, `scripts/` and `tests/`.
- **`pyproject.toml`:** optional extras `kafka = ["confluent-kafka"]` (services install `telemetry[kafka]`); the Pub/Sub and Kinesis extras arrive with their drivers.

## 4. Interfaces
- **Consumes:** `event-contract` (`Event`, `serialize_event`, `validate_payload`); the contract keys `STREAMING_BACKEND`, `KAFKA_BOOTSTRAP_SERVERS`, `EVENTS_TOPIC` (`.env.local`); the topic `clickstream.events.v1` (`infra-local-resources`).
- **Produces:** `telemetry.get_producer()` and `EventProducer`, used by `store-api` (T3.3).

## 5. E2E test flows
**E2E-1: a thousand journey-1 events reach Kafka in session order.**
1. Ensure the local environment is up (`make up`, idempotent) and build the producer with `get_producer()` from `.env.local`.
2. Publish 1,000 contract events: journey-1 sequences spread over 50 sessions, interleaved across sessions.
3. `flush()` returns 0, and `stats()` reports 1,000 delivered and 0 failed or dropped.
4. Reading the topic from the offsets recorded before step 2 returns at least 1,000 messages with our `event_id`s, all of them: each key equals the event's `session_id`, the headers match the payload, every payload passes `validate_payload`, and within each session the events arrive in the order they were sent.

**E2E-2: resilience and boundaries.**
1. **Broker outage:** stop the Kafka container, send 50 events. `send_event` doesn't raise and returns immediately, and `flush(2)` reports them pending. Start the container again: `flush()` reaches 0 and all 50 are readable from the topic.
2. **Validation:** an invalid event raises `EventValidationError`, and nothing is published.
3. **Factory:** `pubsub` and `kinesis` raise `NotProvisionedError` naming the delivering feature; an unknown backend or a missing `KAFKA_BOOTSTRAP_SERVERS` raises `TelemetryConfigError` naming the key.
4. **SDK isolation:** in a fresh interpreter, `import telemetry` loads no `confluent_kafka`, `google.cloud` or `boto3`, and `get_producer()` for Kafka loads only `confluent_kafka`. `scripts/check_sdk_imports.py` passes on the repository.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=telemetry-producer`, and the `event-contract` flows still pass.

## 7. Open items
- Marked `Done` with the regression reruns of `infra-local-platform` and `infra-local-resources` skipped, by decision (2026-09-27). Their flows are affected by the Makefile Terraform retry and the new `make down` at the start of the `infra-local-platform` flows; rerun them the next time either feature is touched.
