output "airflow_api_url" {
  description = "Airflow UI and REST API on the host (also the contract's AIRFLOW_API_URL)."
  value       = module.airflow.api_url
}

output "airflow_image" {
  description = "The locally built Airflow image."
  value       = module.airflow.image
}

output "airflow_containers" {
  description = "Names of the long-running Airflow containers."
  value       = module.airflow.containers
}
