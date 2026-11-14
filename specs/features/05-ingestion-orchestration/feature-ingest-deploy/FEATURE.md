# F05.2: Ingest Consumer Container & Terraform Deployment

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [05](../../../05-ingestion-orchestration.md) | T5.3 | ingest-consumer, airflow-local (creates `30-services`) | 5 |

## 1. Goal
Run the ingest consumer (F05.1) as a container under `make up`, managed by Terraform, so events flow from Kafka into the raw table without a process on the host.

## 2. Scope
- **In:**
  - `services/ingest_consumer/Dockerfile`
  - `modules/local/consumer`, wired into `envs/local/30-services` (D16)
- **Out:**
  - Any change to the consumer's behavior (F05.1)
  - The Cloud Run consumer or the BigQuery subscription (Phase 8, parking lot)

## 3. Implementation definition
- **Dockerfile** (build context: repo root, because the consumer depends on the `telemetry` workspace package):
  - Multi-stage with `uv`: the build stage runs `uv sync --frozen --no-dev --package ingest-consumer`; the runtime stage copies the virtualenv and runs `python -m ingest_consumer` as a non-root user.
  - Python version from `versions.env` (`PYTHON_MIN_VERSION`).
- **`modules/local/consumer`:**
  - `docker_image` built from the Dockerfile, with a trigger on the hash of `services/ingest_consumer/`, `telemetry/` and `uv.lock`, so code changes rebuild it.
  - `consumer_replicas` variable (default 1, validated between 1 and the `events` topic's partition count, 3 locally): containers `ingest-consumer-<n>` on the platform network, all in group `INGEST_GROUP_ID` (default `clickstream-ingest`).
  - Environment passed directly (spec 01 §4): `KAFKA_BOOTSTRAP_SERVERS=kafka:19092`, `EVENTS_TOPIC`, `EVENTS_DLQ_TOPIC`, `WAREHOUSE_BACKEND=postgres`, `WAREHOUSE_DSN` (in-network, `ingest_writer`, from `service_credentials`), `WAREHOUSE_RAW_SCHEMA`, and the `INGEST_*` tuning variables with their spec defaults.
  - `stop_signal = SIGTERM` and a 30-second stop timeout, so `docker stop` and `terraform destroy` trigger the consumer's flush-commit-close shutdown.
  - Restart policy `unless-stopped`: a crashed consumer comes back and re-reads from its last committed offsets.
  - No healthcheck endpoint (the consumer has no HTTP server); liveness is the restart policy plus the per-flush log line.
- **Effect on other flows:** with the container running, the host-side consumers used by other features' flows (unique groups) run alongside it. Both write to the raw table, and `ON CONFLICT (event_id) DO NOTHING` keeps one row per event, so those flows stay valid.

## 4. Interfaces
- **Consumes:**
  - `clickstream.events.v1` and `clickstream.events.dlq` (`infra-local-resources`).
  - The `ingest_writer` credentials through `service_credentials` (`20-resources`) and the `30-services` stack (`airflow-local`).
- **Produces:** the always-on ingestion path: `warehouse.raw.clickstream_events` fills as events arrive. Used by `local-e2e` (F05.5).

## 5. E2E test flows
**E2E-1: events land in the raw table with no host consumer.**
1. Run `make up`. The `ingest-consumer-1` container is running, and its logs show it joined the group `clickstream-ingest`.
2. Publish 300 journey-1 events from the host with the telemetry producer.
3. Within 30 seconds, all 300 `event_id`s are in `raw.clickstream_events`, with no host-side consumer started by the test.
4. Publish one invalid message: it lands in the DLQ, and the container keeps running (same container ID, no restart).

**E2E-2: crashes, graceful stops and rebuilds.**
1. Publish 2,000 events and `docker kill` the consumer while it's ingesting. The restart policy brings it back, and all 2,000 `event_id`s end up in the raw table exactly once.
2. `docker stop` the container: its last log lines show a final flush and commit, and after `docker start` no event is written twice and none is missing.
3. With `TF_VAR_consumer_replicas=3`, `make up` runs three containers that split the three partitions between them, and events still land exactly once.
4. Changing a file in `services/ingest_consumer/` and running `make up` rebuilds only the consumer image and replaces only the consumer containers; a second `make up` plans no changes.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=ingest-deploy`, and `scripts/check_sdk_imports.py` passes.

## 7. Open items
None.
