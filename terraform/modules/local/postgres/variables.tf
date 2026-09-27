variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "network_name" {
  description = "Docker network the container joins."
  type        = string
}

variable "image" {
  description = "Pinned postgres image (versions.env POSTGRES_IMAGE)."
  type        = string
}

variable "host_port" {
  description = "Host port for Postgres."
  type        = number
  default     = 5432
}

variable "admin_user" {
  description = "Superuser name."
  type        = string
  default     = "postgres"
}

variable "keep_data" {
  description = "Keep the data volume on destroy and reuse it on the next apply."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels applied to the container and volume."
  type        = map(string)
  default     = {}
}
