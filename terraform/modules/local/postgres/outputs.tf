output "host" {
  description = "Postgres host for clients on the host."
  value       = "localhost"
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
