# F01.4: GCP Platform

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not scheduled | [01](../../../01-infrastructure.md) | T8.1, T8.2, T8.6 (infrastructure part) | F05.5 (local end-to-end green, D5) | 8 |

## 1. Goal
Provision the GCP environment behind the same environment contract as local, so services run on GCP without code changes.

## 2. Scope
- **In:**
  - Bootstrap of the state bucket
  - Enabling the project APIs
  - `modules/gcp/{pubsub,bigquery,gcs,artifact_registry,iam,cloud_run}`
  - The `envs/gcp` stack and `.env.gcp`
  - `make smoke ENV=gcp`
- **Out:**
  - The Pub/Sub driver code (telemetry-pubsub)
  - The ingestion path (F05.6)
  - The dbt BigQuery target (F06.4)

## 3. Implementation definition
- **Bootstrap:** a one-time stack for the GCS state bucket, with versioning on.
- **Pub/Sub:**
  - Topics `clickstream-events-v1` and a dead-letter topic
  - A pull subscription with ordering on
- **BigQuery:**
  - Datasets `raw`, `staging` and `marts`
  - Default table expiration in dev
- **Artifact Registry:** a Docker repository.
- **IAM:** one service account per workload (app, bot, consumer, dbt), each with least-privilege bindings.
- **Cloud Run:**
  - Services for the app and consumer, with `min_instances = 0`
  - A Job for the bot
- **Contract:** `.env.gcp` has the same keys as `.env.local`.

## 4. Interfaces
- **Consumes:** the contract inputs and the GCP project ID.
- **Produces:** the contract outputs with GCP values, used by telemetry-pubsub, F05.6 and F06.4.

## 5. E2E test flows
**E2E-1: GCP comes up.**
1. Bootstrap the state bucket.
2. `make up ENV=gcp` succeeds.
3. `make smoke ENV=gcp` publishes and pulls one message on Pub/Sub, and writes and reads a row in the BigQuery `raw` dataset.

**E2E-2: contract parity and teardown.**
1. The key sets of `.env.gcp` and `.env.local` are identical.
2. `make down ENV=gcp` removes everything except the state bucket.

## 6. Definition of done
Both flows pass, and no resource falls outside the free-tier guardrails in spec 01 §6.

## 7. Open items
- The store DB on GCP (spec 01 §11).
- Where orchestration runs on GCP (spec 05).
