terraform {
  # Keep in sync with versions.env (TERRAFORM_VERSION, TF_PROVIDER_*_VERSION).
  required_version = "1.16.2"

  required_providers {
    kafka = {
      source  = "Mongey/kafka"
      version = "0.13.1"
    }
    postgresql = {
      source  = "cyrilgdn/postgresql"
      version = "1.27.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
    local = {
      source  = "hashicorp/local"
      version = "2.9.1"
    }
  }

  backend "local" {}
}

# Both providers connect to the servers created by 10-platform (spec 01 §3).
data "terraform_remote_state" "platform" {
  backend = "local"
  config = {
    path = "${path.module}/../10-platform/terraform.tfstate"
  }
}

locals {
  platform = data.terraform_remote_state.platform.outputs
}

provider "kafka" {
  bootstrap_servers = [local.platform.kafka_bootstrap_host]
  tls_enabled       = false
}

provider "postgresql" {
  host            = local.platform.postgres_host
  port            = local.platform.postgres_port
  username        = local.platform.postgres_admin_user
  password        = local.platform.postgres_admin_password
  sslmode         = "disable"
  superuser       = true
  connect_timeout = 15
}
