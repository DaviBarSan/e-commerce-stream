locals {
  # Single-node KRaft (combined broker + controller). Clients on the host use EXTERNAL,
  # containers on the platform network use INTERNAL.
  kafka_env = {
    CLUSTER_ID                                             = var.cluster_id
    KAFKA_NODE_ID                                          = "1"
    KAFKA_PROCESS_ROLES                                    = "broker,controller"
    KAFKA_LISTENERS                                        = "INTERNAL://:19092,EXTERNAL://:9092,CONTROLLER://:9093"
    KAFKA_ADVERTISED_LISTENERS                             = "INTERNAL://kafka:19092,EXTERNAL://localhost:${var.host_port}"
    KAFKA_LISTENER_SECURITY_PROTOCOL_MAP                   = "INTERNAL:PLAINTEXT,EXTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT"
    KAFKA_INTER_BROKER_LISTENER_NAME                       = "INTERNAL"
    KAFKA_CONTROLLER_LISTENER_NAMES                        = "CONTROLLER"
    KAFKA_CONTROLLER_QUORUM_VOTERS                         = "1@kafka:9093"
    KAFKA_AUTO_CREATE_TOPICS_ENABLE                        = "false"
    KAFKA_DEFAULT_REPLICATION_FACTOR                       = "1"
    KAFKA_MIN_INSYNC_REPLICAS                              = "1"
    KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR                 = "1"
    KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR         = "1"
    KAFKA_TRANSACTION_STATE_LOG_MIN_ISR                    = "1"
    KAFKA_SHARE_COORDINATOR_STATE_TOPIC_REPLICATION_FACTOR = "1"
    KAFKA_SHARE_COORDINATOR_STATE_TOPIC_MIN_ISR            = "1"
    KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS                 = "0"
    KAFKA_LOG_DIRS                                         = "/var/lib/kafka/data"
  }

  ui_env = {
    KAFKA_CLUSTERS_0_NAME             = var.project_name
    KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS = "kafka:19092"
    DYNAMIC_CONFIG_ENABLED            = "false"
  }
}

resource "docker_image" "kafka" {
  name         = var.image
  keep_locally = true
}

resource "docker_image" "ui" {
  name         = var.ui_image
  keep_locally = true
}

resource "docker_container" "kafka" {
  name     = "${var.project_name}-kafka"
  image    = docker_image.kafka.image_id
  hostname = "kafka"
  restart  = "unless-stopped"
  env      = [for k, v in local.kafka_env : "${k}=${v}"]

  networks_advanced {
    name    = var.network_name
    aliases = ["kafka"]
  }

  ports {
    internal = 9092
    external = var.host_port
    ip       = "127.0.0.1"
  }

  healthcheck {
    test         = ["CMD-SHELL", "/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:19092 > /dev/null 2>&1"]
    interval     = "10s"
    timeout      = "15s"
    retries      = 12
    start_period = "10s"
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

resource "docker_container" "ui" {
  name    = "${var.project_name}-kafka-ui"
  image   = docker_image.ui.image_id
  restart = "unless-stopped"
  env     = [for k, v in local.ui_env : "${k}=${v}"]

  networks_advanced {
    name    = var.network_name
    aliases = ["kafka-ui"]
  }

  ports {
    internal = 8080
    external = var.ui_host_port
    ip       = "127.0.0.1"
  }

  healthcheck {
    test         = ["CMD-SHELL", "wget -q -O /dev/null http://localhost:8080/actuator/health || exit 1"]
    interval     = "10s"
    timeout      = "5s"
    retries      = 18
    start_period = "15s"
  }

  wait         = true
  wait_timeout = 240

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }

  depends_on = [docker_container.kafka]
}
