output "api_url" {
  description = "Airflow UI and REST API on the host."
  value       = "http://127.0.0.1:${var.host_port}"
}

output "image" {
  description = "The locally built Airflow image."
  value       = docker_image.airflow.name
}

output "containers" {
  description = "Names of the long-running Airflow containers."
  value       = [docker_container.api_server.name, docker_container.scheduler.name, docker_container.dag_processor.name]
}
