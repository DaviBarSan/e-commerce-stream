# Clickstream Pipeline: Design Principles & Revised Execution Plan

This document outlines the core architecture design principles and a 5-phase actionable roadmap to implement a cloud-agnostic clickstream data pipeline.

---

## 1. Core Design Principles for Maximum Portability

1. **Interface-Driven Telemetry**:
   Implement an abstract `EventProducer` class in Python. Swap backend providers (Kafka, GCP Pub/Sub, AWS Kinesis) without altering frontend application code.

2. **Strict Payload Standardization**:
   Enforce a centralized JSON schema or Avro schema across all event emissions to guarantee schema compatibility across warehouses.

3. **ANSI SQL & Cross-Database dbt Macros**:
   Write all transformation logic using standard SQL and cross-database `dbt` packages (`dbt-utils`). Avoid database-specific syntax (e.g., Snowflake JSON vs BigQuery JSON) inside business logic models.

4. **Environment-Agnostic Containerization**:
   Package all services (E-Commerce Web App, Traffic Bot, Airflow Orchestrator) inside Docker containers to ensure identical behavior across local machines, AWS ECS, or GCP Cloud Run.

5. **Modular Infrastructure as Code (IaC)**:
   Structure Terraform configurations into independent environment modules (`/terraform/aws`, `/terraform/gcp`, `/terraform/local`) sharing identical variable inputs.

---

## 2. Phase-by-Phase Execution Plan

### Phase 1: Portable Frontend & Abstracted Telemetry
**Goal**: Build a functional web store that emits standardized clickstream telemetry.

* **Task 1.1: Build Application Interface**:
  * Develop catalog, product detail, cart, search, and checkout screens using **Streamlit** or **Reflex**.
* **Task 1.2: Define Standard Event Schema**:
  * Fields: `event_id`, `user_id`, `session_id`, `event_type` (e.g., `page_view`, `add_to_cart`, `checkout`), `timestamp`, `page_url`, `metadata_json`.
* **Task 1.3: Build Abstract Producer Module**:
  ```
  /telemetry
    ├── __init__.py
    ├── base.py          # Abstract Base Class: EventProducer
    ├── kafka_driver.py  # Confluent Kafka / Upstash implementation
    ├── gcp_driver.py    # GCP Pub/Sub implementation
    └── aws_driver.py    # AWS Kinesis / MSK implementation
  ```
* **Task 1.4: Containerize Application**:
  * Create a lightweight `Dockerfile` for the frontend service.

---

### Phase 2: Traffic Simulation Bot
**Goal**: Generate synthetic, realistic multi-user traffic patterns.

* **Task 2.1: Develop Simulation Suite**:
  * Write user interaction flows using **Locust** (for high-volume API/event generation) or **Playwright Python** (for browser-rendered automation).
* **Task 2.2: Define User Behavior Personas**:
  * *Casual Browser*: Visits home page, searches 1 item, leaves.
  * *High-Intent Buyer*: Searches, views details, adds to cart, completes purchase.
  * *Cart Abandoner*: Browses, adds items to cart, drops out at checkout.
* **Task 2.3: Parameterize Scenarios**:
  * Support configurable rates (e.g., peak hours simulation, promo spikes).

---

### Phase 3: Pluggable Streaming Ingestion & Warehouse Staging
**Goal**: Ingest streaming events and store raw payloads in the target data warehouse.

* **Task 3.1: Configure Stream Broker**:
  * Provision Upstash Kafka (for zero-cost development) or native cloud queues (GCP Pub/Sub / AWS Kinesis).
* **Task 3.2: Implement Micro-Batch Sink / Consumer**:
  * *Option A*: Deploy a continuous Python consumer process that writes micro-batches to the target database.
  * *Option B*: Use native cloud integrations (e.g., GCP Pub/Sub Direct BigQuery Subscription or AWS Kinesis Data Firehose).
* **Task 3.3: Initialize Raw Staging Table**:
  * Create raw storage tables with columns: `event_id`, `ingested_at`, `raw_payload` (JSON format).

---

### Phase 4: Cloud-Agnostic Data Modeling with dbt
**Goal**: Transform unstructured event streams into clean dimensional data marts.

* **Task 4.1: Staging Models (`stg_clickstream`)**:
  * Parse JSON payloads into typed attributes (`user_id`, `session_id`, `product_id`, etc.).
  * Deduplicate events based on `event_id`.
* **Task 4.2: Sessionization Models (`int_sessions`)**:
  * Calculate user session windows using standard SQL window functions (`LAG`, `SUM OVER`) with a 30-minute inactivity threshold.
  * Derive session metrics: duration, pageviews count, total items added, checkout conversion status.
* **Task 4.3: Analytics Marts (`fct_events`, `fct_conversion_funnels`, `dim_users`)**:
  * Build conversion funnel tables (Search $\rightarrow$ Product View $\rightarrow$ Cart Add $\rightarrow$ Order Complete).
  * Implement dbt data quality tests (`unique`, `not_null`, `relationships`).

---

### Phase 5: Containerized Orchestration & IaC
**Goal**: Automate pipeline execution and infrastructure deployment.

* **Task 5.1: Local Orchestration with Airflow**:
  * Set up Apache Airflow locally using Docker Compose or Astronomer CLI.
  * Build a DAG to run data quality checks (`dbt test`) and execute transformations (`dbt run`).
* **Task 5.2: Infrastructure Provisioning with Terraform**:
  * Build modular Terraform code to provision topics, buckets, datasets, and permissions on GCP or AWS with single-command deployments (`terraform apply`).

---

## 3. Verification & End-to-End Testing

1. **Local Validation**: Run the app, bot, Kafka, Postgres/DuckDB, and Airflow inside Docker. Confirm that bot actions translate into updated dbt marts.
2. **Cloud Portability Test**: Switch environment flags to send events through GCP Pub/Sub to BigQuery, then execute `dbt run --target bigquery` without modifying model code.
3. **Data Quality Audit**: Validate dbt test results for schema consistency, event completeness, and sessionization accuracy.