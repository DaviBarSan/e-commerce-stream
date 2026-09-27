# Environment contract outputs (spec 01 §4.2). Empty until AWS comes back into scope (D7).
output "contract" {
  description = "Environment contract, same keys as every other env."
  value = {
    STREAMING_BACKEND       = "kinesis"
    KAFKA_BOOTSTRAP_SERVERS = ""
    GCP_PROJECT_ID          = ""
    EVENTS_TOPIC            = ""
    EVENTS_DLQ_TOPIC        = ""
    WAREHOUSE_BACKEND       = "redshift"
    WAREHOUSE_DSN           = ""
    WAREHOUSE_DATASET       = ""
    WAREHOUSE_RAW_SCHEMA    = var.warehouse_raw_schema
    STORE_DB_DSN            = ""
    DBT_WAREHOUSE_DSN       = ""
    AIRFLOW_DB_DSN          = ""
  }
}
