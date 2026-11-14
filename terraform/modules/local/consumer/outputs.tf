output "containers" {
  description = "Names of the consumer containers."
  value       = docker_container.consumer[*].name
}
