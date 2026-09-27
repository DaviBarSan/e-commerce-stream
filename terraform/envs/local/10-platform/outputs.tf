output "network_name" {
  description = "Platform Docker network."
  value       = module.network.name
}

output "kafka_bootstrap_host" {
  description = "Kafka bootstrap servers for the host."
  value       = module.kafka.bootstrap_host
}

output "kafka_bootstrap_internal" {
  description = "Kafka bootstrap servers for containers on the platform network."
  value       = module.kafka.bootstrap_internal
}

output "kafka_ui_url" {
  description = "Kafka UI on the host."
  value       = module.kafka.ui_url
}

output "postgres_host" {
  description = "Postgres host for the host."
  value       = module.postgres.host
}

output "postgres_port" {
  description = "Postgres port on the host."
  value       = module.postgres.port
}

output "postgres_admin_user" {
  description = "Postgres superuser."
  value       = module.postgres.admin_user
}

output "postgres_admin_password" {
  description = "Postgres superuser password."
  value       = module.postgres.admin_password
  sensitive   = true
}
