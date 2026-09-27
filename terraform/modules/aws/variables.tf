# Environment contract inputs (spec 01 §4.1), identical to every other env.
variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "aws"
}

variable "topics" {
  description = "Logical topics (events, events_dlq) with partitions and retention."
  type = map(object({
    partitions      = number
    retention_hours = number
  }))
}

variable "warehouse_raw_schema" {
  description = "Schema that holds raw events in the warehouse."
  type        = string
}

variable "labels" {
  description = "Labels applied wherever the backend supports them."
  type        = map(string)
  default     = {}
}
