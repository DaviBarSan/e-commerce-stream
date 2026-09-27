locals {
  volume_name = "${var.project_name}-pgdata"
}

resource "random_password" "admin" {
  length  = 32
  special = false
}

resource "docker_image" "postgres" {
  name         = var.image
  keep_locally = true
}

# With keep_data = true the volume is not managed here: Docker creates it on first use
# and `terraform destroy` leaves it in place for the next apply.
resource "docker_volume" "pgdata" {
  count = var.keep_data ? 0 : 1
  name  = local.volume_name

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}

resource "docker_container" "postgres" {
  name    = "${var.project_name}-postgres"
  image   = docker_image.postgres.image_id
  restart = "unless-stopped"
  env = [
    "POSTGRES_USER=${var.admin_user}",
    "POSTGRES_PASSWORD=${random_password.admin.result}",
  ]

  networks_advanced {
    name    = var.network_name
    aliases = ["postgres"]
  }

  ports {
    internal = 5432
    external = var.host_port
    ip       = "127.0.0.1"
  }

  mounts {
    type   = "volume"
    source = var.keep_data ? local.volume_name : docker_volume.pgdata[0].name
    target = "/var/lib/postgresql"
  }

  # TCP check: the entrypoint's temporary init server only listens on the socket.
  healthcheck {
    test         = ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U ${var.admin_user}"]
    interval     = "5s"
    timeout      = "5s"
    retries      = 24
    start_period = "5s"
  }

  wait         = true
  wait_timeout = 180

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}

# POSTGRES_PASSWORD only applies when the data directory is initialized. Set the password
# explicitly so a reused volume (keep_data = true) matches the password in the current state.
resource "terraform_data" "admin_password" {
  triggers_replace = [docker_container.postgres.id, sha256(random_password.admin.result)]

  provisioner "local-exec" {
    interpreter = ["docker", "exec", docker_container.postgres.name, "psql", "-U", var.admin_user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-q", "-c"]
    command     = "ALTER USER \"${var.admin_user}\" PASSWORD '${random_password.admin.result}'"
  }
}
