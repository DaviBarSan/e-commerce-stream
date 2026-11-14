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

# --- Pinned images: set from versions.env via TF_VAR_* (Makefile / e2e helpers) ---
variable "kafka_image" {
  description = "versions.env KAFKA_IMAGE"
  type        = string
}

variable "kafka_ui_image" {
  description = "versions.env KAFKA_UI_IMAGE"
  type        = string
}

variable "postgres_image" {
  description = "versions.env POSTGRES_IMAGE"
  type        = string
}

# --- Local platform settings ---
variable "postgres_host_port" {
  description = "Host port for Postgres. Override in a gitignored *.local.auto.tfvars if 5432 is taken."
  type        = number
  default     = 5432
}

variable "keep_data" {
  description = "Keep the Postgres volume on destroy and reuse it on the next apply."
  type        = bool
  default     = false
}

variable "airflow_host_port" {
  description = "Host port for the Airflow API server (30-services). Declared here so every host port lives in one stack."
  type        = number
  default     = 8080
}

variable "store_api_host_port" {
  description = "Host port for the store API container (30-services)."
  type        = number
  default     = 8000
}

variable "store_web_host_port" {
  description = "Host port for the storefront container (30-services); the Reflex UI and its backend share it."
  type        = number
  default     = 3000
}
