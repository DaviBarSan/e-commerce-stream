# --- Environment contract inputs (spec 01 §4.1) ---
variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "labels" {
  description = "Labels applied wherever the backend supports them."
  type        = map(string)
  default     = {}
}

# --- Pinned versions: set from versions.env via TF_VAR_* (Makefile / e2e helpers) ---
variable "airflow_image" {
  description = "versions.env AIRFLOW_IMAGE"
  type        = string
}

variable "dbt_core_version" {
  description = "versions.env DBT_CORE_VERSION"
  type        = string
}

variable "dbt_postgres_version" {
  description = "versions.env DBT_POSTGRES_VERSION"
  type        = string
}

variable "python_image" {
  description = "versions.env PYTHON_IMAGE"
  type        = string
}

variable "uv_image" {
  description = "versions.env UV_IMAGE"
  type        = string
}

# --- Service settings ---
variable "consumer_replicas" {
  description = "Ingest consumer containers (1 to the events topic's partition count)."
  type        = number
  default     = 1
}

variable "transform_schedule" {
  description = "Schedule of the clickstream_transform DAG: cron or preset, or `none` for manual runs only."
  type        = string
  default     = "@hourly"
}

variable "raw_freshness_minutes" {
  description = "Minutes without new raw rows after which the DAG's freshness check fails."
  type        = number
  default     = 30
}
