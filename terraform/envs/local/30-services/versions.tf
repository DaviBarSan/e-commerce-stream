terraform {
  # Keep in sync with versions.env (TERRAFORM_VERSION, TF_PROVIDER_*_VERSION).
  required_version = "1.16.2"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "4.6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }

  backend "local" {}
}

# Uses DOCKER_HOST when set, otherwise the provider's platform default (npipe on Windows).
provider "docker" {}

# Service containers join the 10-platform network and use the 20-resources credentials (D16, spec 01 §3).
data "terraform_remote_state" "platform" {
  backend = "local"
  config = {
    path = "${path.module}/../10-platform/terraform.tfstate"
  }
}

data "terraform_remote_state" "resources" {
  backend = "local"
  config = {
    path = "${path.module}/../20-resources/terraform.tfstate"
  }
}
