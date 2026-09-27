output "host" {
  # 127.0.0.1, not localhost: the port is bound to IPv4 only, and "localhost" resolves to ::1 first,
  # which hangs (instead of being refused) on Windows hosts until the client's connect timeout.
  description = "Postgres host for clients on the host."
  value       = "127.0.0.1"
  depends_on  = [terraform_data.admin_password]
}

output "port" {
  description = "Postgres port on the host."
  value       = var.host_port
  depends_on  = [terraform_data.admin_password]
}

output "admin_user" {
  description = "Superuser name."
  value       = var.admin_user
}

output "admin_password" {
  description = "Superuser password."
  value       = random_password.admin.result
  sensitive   = true
  depends_on  = [terraform_data.admin_password]
}
