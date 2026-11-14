variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "network_name" {
  description = "Docker network the containers join."
  type        = string
}

variable "repo_root" {
  description = "Absolute path of the repository: the image build context."
  type        = string
}

variable "python_image" {
  description = "Pinned Python base image (versions.env PYTHON_IMAGE)."
  type        = string
}

variable "uv_image" {
  description = "Pinned uv image the build copies uv from (versions.env UV_IMAGE)."
  type        = string
}

variable "replicas" {
  description = "Consumer containers in the group; at most one per partition of the events topic."
  type        = number
  default     = 1
}

variable "events_partitions" {
  description = "Partition count of the events topic: the upper bound for replicas."
  type        = number
}

variable "group_id" {
  description = "Kafka consumer group shared by the replicas (INGEST_GROUP_ID)."
  type        = string
  default     = "clickstream-ingest"
}

variable "kafka_bootstrap" {
  description = "In-network Kafka bootstrap servers (kafka:19092)."
  type        = string
}

variable "events_topic" {
  description = "Events topic to consume."
  type        = string
}

variable "events_dlq_topic" {
  description = "Dead-letter topic for invalid events."
  type        = string
}

variable "warehouse_db" {
  description = "Credentials of the ingest_writer role on the warehouse database (reached in-network at postgres:5432)."
  type = object({
    user     = string
    password = string
    database = string
  })
  sensitive = true
}

variable "warehouse_raw_schema" {
  description = "Schema of the raw table."
  type        = string
}

variable "labels" {
  description = "Labels applied to the image and containers."
  type        = map(string)
  default     = {}
}
