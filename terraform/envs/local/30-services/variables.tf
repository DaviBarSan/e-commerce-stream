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
