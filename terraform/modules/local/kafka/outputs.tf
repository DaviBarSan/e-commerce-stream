output "bootstrap_host" {
  description = "Bootstrap servers for clients on the host."
  value       = "127.0.0.1:${var.host_port}"
  depends_on  = [docker_container.kafka]
}

output "bootstrap_internal" {
  description = "Bootstrap servers for containers on the platform network."
  value       = "kafka:19092"
  depends_on  = [docker_container.kafka]
}

output "ui_url" {
  description = "Kafka UI URL on the host."
  value       = "http://localhost:${var.ui_host_port}"
  depends_on  = [docker_container.ui]
}
