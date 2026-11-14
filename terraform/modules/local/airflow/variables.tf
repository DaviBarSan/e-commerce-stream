variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "network_name" {
  description = "Docker network the containers join."
  type        = string
}

variable "repo_root" {
  description = "Absolute path of the repository: the image build context, and the parent of dags/."
  type        = string
}

variable "base_image" {
  description = "Pinned Airflow image the local image builds FROM (versions.env AIRFLOW_IMAGE)."
  type        = string
}

variable "dbt_core_version" {
  description = "versions.env DBT_CORE_VERSION, installed in the image's dbt virtualenv (D17)."
  type        = string
}

variable "dbt_postgres_version" {
  description = "versions.env DBT_POSTGRES_VERSION, installed in the image's dbt virtualenv (D17)."
  type        = string
}

variable "host_port" {
  description = "Host port of the API server (UI and REST API)."
  type        = number
  default     = 8080
}

variable "metadata_db" {
  description = "Credentials of the airflow role and database (reached in-network at postgres:5432)."
  type = object({
    user     = string
    password = string
    database = string
  })
  sensitive = true
}

variable "warehouse_db" {
  description = "Credentials dbt uses from DAG tasks (the dbt_runner role on the warehouse database)."
  type = object({
    user     = string
    password = string
    database = string
  })
  sensitive = true
}

variable "warehouse_raw_schema" {
  description = "Raw schema name, read by the dbt sources."
  type        = string
}

variable "admin_password" {
  description = "Password of the simple auth manager's admin user (contract AIRFLOW_ADMIN_PASSWORD)."
  type        = string
  sensitive   = true
}

variable "labels" {
  description = "Labels applied to the image and containers."
  type        = map(string)
  default     = {}
}
