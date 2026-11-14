output "api_url" {
  description = "Store API on the host."
  value       = "http://127.0.0.1:${var.api_host_port}"
}

output "web_url" {
  description = "Storefront on the host."
  value       = "http://127.0.0.1:${var.web_host_port}"
}

output "containers" {
  description = "Names of the long-running store containers."
  value       = [docker_container.api.name, docker_container.web.name]
}
