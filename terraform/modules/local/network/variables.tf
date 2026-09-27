variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
}

variable "labels" {
  description = "Labels applied to the network."
  type        = map(string)
  default     = {}
}
