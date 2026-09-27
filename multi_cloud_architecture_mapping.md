# Clickstream Pipeline: Multi-Cloud Architecture Mapping

This document details the architectural blueprints, technology stack mappings, and cost-optimization strategies for building a cloud-agnostic clickstream analytics pipeline. The design allows seamless swapping between **Google Cloud Platform (GCP)**, **Amazon Web Services (AWS)**, and a **Local/Zero-Cost Environment**.

---

## 1. High-Level System Flow

```
[ E-Commerce App ] (Streamlit/Reflex)  --->  [ User Bot ] (Locust/Playwright)
        │
        ▼ (HTTP / Producer SDK Interface)
[ Abstract Event Producer ] (Python Driver)
        │
        ├──> [ Upstash Kafka / Redpanda ] (Local / Multi-Cloud)
        ├──> [ GCP Pub/Sub ]              (GCP Option)
        └──> [ AWS Kinesis / MSK ]         (AWS Option)
        │
        ▼ (Streaming Consumer / Micro-Batch Sink)
[ Raw Staging Storage ]
        │
        ├──> [ GCP BigQuery Raw Dataset ] (GCP)
        ├──> [ AWS S3 / Redshift Staging ] (AWS)
        └──> [ DuckDB / Local Postgres ]  (Local)
        │
        ▼
[ dbt Transformations ] <--- [ Apache Airflow Orchestrator ]
        │
        ▼
[ Analytics Marts ] (Star Schema / Funnels / Sessions)
```

---

## 2. Component Mapping Across Clouds

| Architecture Layer | Standard Interface / Abstraction | GCP Implementation | AWS Implementation | Local / Zero-Cost Option |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend Application** | Containerized App (Docker) | Cloud Run | Elastic Container Service (ECS) | Local Docker / Streamlit Community Cloud |
| **Traffic Bot Generator** | Headless Browser / Load Testing | Cloud Run Job | ECS Task / Lambda | Local Python / Locust Script |
| **Event Streaming Broker** | Apache Kafka Protocol / HTTP API | Cloud Pub/Sub (w/ Kafka Shim) | Amazon Kinesis / Amazon MSK | Upstash Kafka (Serverless Free Tier) / Redpanda |
| **Data Lake / Landing** | Object Storage | Google Cloud Storage (GCS) | Amazon Simple Storage Service (S3) | MinIO / Direct Warehouse Stream |
| **Data Warehouse (OLAP)** | SQL Engine / Columnar Store | BigQuery | Amazon Redshift Serverless / Snowflake | DuckDB / PostgreSQL |
| **Data Transformations** | SQL / Jinja (`dbt-core`) | `dbt-bigquery` | `dbt-redshift` / `dbt-snowflake` | `dbt-duckdb` / `dbt-postgres` |
| **Orchestration Engine** | Apache Airflow DAGs | Cloud Composer | Managed Workflows for Airflow (MWAA) | Local Airflow (Astronomer CLI / Docker Compose) |
| **Infrastructure as Code** | HashiCorp Terraform | `hashicorp/google` Provider | `hashicorp/aws` Provider | Terraform + LocalStack / Docker |

---

## 3. Cost Strategy & Free Tier Optimization

To develop and test this project with near-zero cloud expenses, leverage the following free tier limits across ecosystems:

### GCP Free Tier
* **BigQuery**: 10 GB storage and 1 TB query processing free per month.
* **Pub/Sub**: 10 GB of messages free per month.
* **Cloud Run**: 2 million requests free per month.
* **Cloud Storage**: 5 GB-months of regional storage.

### AWS Free Tier / Trial
* **S3**: 5 GB of standard storage (12 months free).
* **Kinesis / Redshift**: Minimal free tier; recommended to use serverless configurations with tight auto-pause settings or local alternatives during development.

### Third-Party / Local Alternatives ($0 Cost)
* **Upstash Kafka**: Serverless Kafka with up to 10,000 messages/day for free.
* **Astronomer CLI**: Run full-featured local Airflow environments using standard Docker configurations.
* **DuckDB**: Embedded analytical engine requiring zero cloud infrastructure.

---

## 4. Layer Deep-Dives

### 4.1 Ingestion & Transport Layer
* **Unified Event API**: The event producer exposes a single `send_event(EventPayload)` interface.
* **Decoupled Transport**: Cloud-specific SDKs (Google Cloud Pub/Sub SDK, AWS Boto3 Kinesis, Confluent Kafka Client) are dynamically loaded based on the `STREAMING_BACKEND` environment variable.

### 4.2 Storage & Transformation Layer
* **Raw Staging**: Events land as semi-structured JSON objects into raw tables with ingestion metadata (`ingested_at`, `source_ip`, `payload_json`).
* **dbt Abstraction**: All transformations are written in generic ANSI SQL. Provider-specific extensions (e.g., JSON extraction syntax) are wrapped using `dbt_utils` or custom macros.

### 4.3 Orchestration Layer
* **Portable DAGs**: Airflow DAGs use standard Python operators, `DockerOperator`, or `BashOperator` to execute dbt tasks, avoiding vendor-locked Cloud Composer or MWAA hooks.