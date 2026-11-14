locals {
  # Python bytecode caches and Reflex build output change on every host run; they must not trigger rebuilds.
  # reflex.lock is rewritten (line endings) by every host `reflex run`; its packages follow the reflex pin.
  ignored = "(__pycache__/|\\.web/|\\.states/|reflex\\.lock/)"

  workspace_inputs = ["pyproject.toml", "uv.lock", ".dockerignore"]
  api_inputs = concat(local.workspace_inputs, [
    for f in sort(tolist(setunion(fileset(var.repo_root, "services/store_backend/**"), fileset(var.repo_root, "telemetry/**"))))
    : f if !can(regex(local.ignored, f))
  ])
  web_inputs = concat(local.workspace_inputs, [
    for f in sort(tolist(fileset(var.repo_root, "services/store_frontend/**"))) : f if !can(regex(local.ignored, f))
  ])

  build_args = {
    PYTHON_IMAGE = var.python_image
    UV_IMAGE     = var.uv_image
  }

  store_db_dsn = "postgresql://${var.store_db.user}:${var.store_db.password}@postgres:5432/${var.store_db.database}"
  api_env = [
    "STORE_DB_DSN=${local.store_db_dsn}",
    "STREAMING_BACKEND=kafka",
    "KAFKA_BOOTSTRAP_SERVERS=${var.kafka_bootstrap}",
    "EVENTS_TOPIC=${var.events_topic}",
  ]
}

resource "docker_image" "api" {
  name = "${var.project_name}-store-api:local"

  build {
    context    = var.repo_root
    dockerfile = "services/store_backend/Dockerfile"
    build_args = local.build_args
    label      = var.labels
  }

  triggers = {
    build_hash = sha1(join("", concat([for f in local.api_inputs : filesha1("${var.repo_root}/${f}")],
    [var.python_image, var.uv_image])))
  }
}

resource "docker_image" "web" {
  name = "${var.project_name}-store-web:local"

  build {
    context    = var.repo_root
    dockerfile = "services/store_frontend/Dockerfile"
    build_args = local.build_args
    label      = var.labels
  }

  triggers = {
    build_hash = sha1(join("", concat([for f in local.web_inputs : filesha1("${var.repo_root}/${f}")],
    [var.python_image, var.uv_image])))
  }
}

# One-shot, idempotent seed (upserts on natural keys); the apply waits for it and fails if it fails.
resource "docker_container" "seed" {
  name     = "${var.project_name}-store-seed"
  image    = docker_image.api.image_id
  command  = ["python", "-m", "store_backend.seed"]
  env      = local.api_env
  must_run = false
  attach   = true

  networks_advanced {
    name = var.network_name
  }

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }

  lifecycle {
    postcondition {
      condition     = self.exit_code == 0
      error_message = "the store seed failed; see the logs of the store-seed container."
    }
  }
}

resource "docker_container" "api" {
  name     = "${var.project_name}-store-api"
  image    = docker_image.api.image_id
  hostname = "store-api"
  restart  = "unless-stopped"
  env      = local.api_env
  # SIGTERM runs the lifespan shutdown: the outbox relay drains and the producer flushes.
  stop_signal  = "SIGTERM"
  stop_timeout = 30

  networks_advanced {
    name    = var.network_name
    aliases = ["store-api"]
  }

  ports {
    internal = 8000
    external = var.api_host_port
    ip       = "127.0.0.1"
  }

  # The slim base has no curl.
  healthcheck {
    test         = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"]
    interval     = "5s"
    timeout      = "10s"
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

  depends_on = [docker_container.seed]
}

resource "docker_container" "web" {
  name     = "${var.project_name}-store-web"
  image    = docker_image.web.image_id
  hostname = "store-web"
  restart  = "unless-stopped"
  env      = ["BACKEND_URL=http://store-api:8000"]

  networks_advanced {
    name    = var.network_name
    aliases = ["store-web"]
  }

  ports {
    internal = 3000
    external = var.web_host_port
    ip       = "127.0.0.1"
  }

  # `reflex run --env prod` compiles and builds the frontend at start, which takes a while.
  healthcheck {
    test         = ["CMD-SHELL", "curl --fail --silent http://localhost:3000/ping > /dev/null && curl --fail --silent http://localhost:3000/ > /dev/null"]
    interval     = "10s"
    timeout      = "10s"
    retries      = 30
    start_period = "1m0s" # Docker reports durations in this form; "60s" would show as a change on every plan
  }

  wait         = true
  wait_timeout = 600

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }

  depends_on = [docker_container.api]
}
