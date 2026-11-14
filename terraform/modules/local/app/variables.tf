variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "network_name" {
  description = "Docker network the containers join."
  type        = string
}

variable "repo_root" {
  description = "Absolute path of the repository: the build context of both images."
  type        = string
}

variable "python_image" {
  description = "Pinned Python base image (versions.env PYTHON_IMAGE)."
  type        = string
}

variable "uv_image" {
  description = "Pinned uv image the builds copy uv from (versions.env UV_IMAGE)."
  type        = string
}

variable "api_host_port" {
  description = "Host port of the store API."
  type        = number
  default     = 8000
}

variable "web_host_port" {
  description = "Host port of the storefront (Reflex UI and its backend share it in production mode)."
  type        = number
  default     = 3000
}

variable "kafka_bootstrap" {
  description = "In-network Kafka bootstrap servers (kafka:19092)."
  type        = string
}

variable "events_topic" {
  description = "Events topic the API publishes to."
  type        = string
}

variable "store_db" {
  description = "Credentials of the store_app role and the store database (reached in-network at postgres:5432)."
  type = object({
    user     = string
    password = string
    database = string
  })
  sensitive = true
}

variable "labels" {
  description = "Labels applied to the images and containers."
  type        = map(string)
  default     = {}
}
