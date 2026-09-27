variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "network_name" {
  description = "Docker network the containers join."
  type        = string
}

variable "image" {
  description = "Pinned apache/kafka image (versions.env KAFKA_IMAGE)."
  type        = string
}

variable "ui_image" {
  description = "Pinned Kafka UI image (versions.env KAFKA_UI_IMAGE)."
  type        = string
}

variable "host_port" {
  description = "Host port of the EXTERNAL listener."
  type        = number
  default     = 9092
}

variable "ui_host_port" {
  description = "Host port of the Kafka UI."
  type        = number
  default     = 8085
}

variable "cluster_id" {
  description = "KRaft cluster ID (base64 UUID). Fixed so re-creating the container doesn't need a new ID."
  type        = string
  default     = "MkU3OEVBNTcwNTJENDM2Qk"
}

variable "labels" {
  description = "Labels applied to the containers."
  type        = map(string)
  default     = {}
}
