locals {
  labels = merge(var.labels, {
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  })

  platform  = data.terraform_remote_state.platform.outputs
  resources = data.terraform_remote_state.resources.outputs.service_credentials

  repo_root = abspath("${path.module}/../../../..")
}

module "airflow" {
  source               = "../../../modules/local/airflow"
  project_name         = var.project_name
  network_name         = local.platform.network_name
  repo_root            = local.repo_root
  base_image           = var.airflow_image
  dbt_core_version     = var.dbt_core_version
  dbt_postgres_version = var.dbt_postgres_version
  host_port            = local.platform.airflow_host_port
  metadata_db          = local.resources.roles["airflow"]
  warehouse_db         = local.resources.roles["dbt_runner"]
  warehouse_raw_schema = local.resources.warehouse_raw_schema
  admin_password       = local.resources.airflow_admin_password
  labels               = local.labels
}
