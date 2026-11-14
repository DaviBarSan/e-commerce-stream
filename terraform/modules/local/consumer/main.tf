locals {
  # Python bytecode caches change on every host run; they must not trigger rebuilds.
  ignored = "__pycache__/"
  inputs = concat(["pyproject.toml", "uv.lock", ".dockerignore"], [
    for f in sort(tolist(setunion(fileset(var.repo_root, "services/ingest_consumer/**"), fileset(var.repo_root, "telemetry/**"))))
    : f if !can(regex(local.ignored, f))
  ])

  env = [
    "KAFKA_BOOTSTRAP_SERVERS=${var.kafka_bootstrap}",
    "EVENTS_TOPIC=${var.events_topic}",
    "EVENTS_DLQ_TOPIC=${var.events_dlq_topic}",
    "WAREHOUSE_BACKEND=postgres",
    "WAREHOUSE_DSN=postgresql://${var.warehouse_db.user}:${var.warehouse_db.password}@postgres:5432/${var.warehouse_db.database}",
    "WAREHOUSE_RAW_SCHEMA=${var.warehouse_raw_schema}",
    "INGEST_GROUP_ID=${var.group_id}",
  ]
}

resource "docker_image" "consumer" {
  name = "${var.project_name}-ingest-consumer:local"

  build {
    context    = var.repo_root
    dockerfile = "services/ingest_consumer/Dockerfile"
    build_args = {
      PYTHON_IMAGE = var.python_image
      UV_IMAGE     = var.uv_image
    }
    label = var.labels
  }

  triggers = {
    build_hash = sha1(join("", concat([for f in local.inputs : filesha1("${var.repo_root}/${f}")],
    [var.python_image, var.uv_image])))
  }
}

resource "docker_container" "consumer" {
  count   = var.replicas
  name    = "${var.project_name}-ingest-consumer-${count.index + 1}"
  image   = docker_image.consumer.image_id
  restart = "unless-stopped"
  env     = local.env
  # SIGTERM runs the flush-commit-close shutdown; a crash re-reads from the last committed offsets.
  stop_signal  = "SIGTERM"
  stop_timeout = 30
  # An init process as PID 1 forwards signals and lets the consumer itself crash (a killed child exits the
  # container, so the restart policy applies; `docker kill` counts as a manual stop and wouldn't).
  init = true

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
    precondition {
      condition     = var.replicas >= 1 && var.replicas <= var.events_partitions
      error_message = "consumer_replicas must be between 1 and the events topic's partition count (${var.events_partitions})."
    }
  }
}
