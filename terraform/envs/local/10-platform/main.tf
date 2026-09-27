locals {
  labels = merge(var.labels, {
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  })
}

module "network" {
  source       = "../../../modules/local/network"
  project_name = var.project_name
  labels       = local.labels
}

module "kafka" {
  source       = "../../../modules/local/kafka"
  project_name = var.project_name
  network_name = module.network.name
  image        = var.kafka_image
  ui_image     = var.kafka_ui_image
  labels       = local.labels
}

module "postgres" {
  source       = "../../../modules/local/postgres"
  project_name = var.project_name
  network_name = module.network.name
  image        = var.postgres_image
  host_port    = var.postgres_host_port
  keep_data    = var.keep_data
  labels       = local.labels
}
