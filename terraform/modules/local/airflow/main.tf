locals {
  # In-network Postgres (spec 01 §4: containers get network hostnames directly).
  pg = "postgres:5432"

  # Files whose change must rebuild the image: the Dockerfile and the dbt project baked into it (D17).
  build_inputs = concat(
    ["services/airflow/Dockerfile", ".dockerignore"],
    [for f in ["dbt_project.yml", "packages.yml", "package-lock.yml", "profiles.yml"] : "dbt/${f}"],
    sort(tolist(fileset(var.repo_root, "dbt/{models,macros,seeds,tests}/**"))),
  )
  build_hash = sha1(join("", concat(
    [for f in local.build_inputs : filesha1("${var.repo_root}/${f}")],
    [var.base_image, var.dbt_core_version, var.dbt_postgres_version],
  )))

  passwords_file = "/opt/airflow/simple_auth_passwords.json"

  env = {
    AIRFLOW__CORE__EXECUTOR                           = "LocalExecutor"
    AIRFLOW__DATABASE__SQL_ALCHEMY_CONN               = "postgresql+psycopg2://${var.metadata_db.user}:${var.metadata_db.password}@${local.pg}/${var.metadata_db.database}"
    AIRFLOW__CORE__LOAD_EXAMPLES                      = "False"
    AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION        = "True"
    AIRFLOW__CORE__FERNET_KEY                         = "${random_id.fernet_key.b64_url}="
    AIRFLOW__CORE__EXECUTION_API_SERVER_URL           = "http://airflow-api-server:8080/execution/"
    AIRFLOW__API_AUTH__JWT_SECRET                     = random_password.jwt_secret.result
    AIRFLOW__API__SECRET_KEY                          = random_password.api_secret_key.result
    AIRFLOW__CORE__AUTH_MANAGER                       = "airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager"
    AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS          = "admin:admin"
    AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE = local.passwords_file
    # Local DAG edits show up within seconds (the default rescans dags/ every 5 minutes).
    AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL = "10"
    AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK  = "True"

    # dbt from DAG tasks (D17): the dbt_runner role in-network; artifacts and logs outside the read-only project.
    DBT_WAREHOUSE_DSN    = "postgresql://${var.warehouse_db.user}:${var.warehouse_db.password}@${local.pg}/${var.warehouse_db.database}"
    DBT_TARGET           = "local"
    WAREHOUSE_RAW_SCHEMA = var.warehouse_raw_schema
    DBT_TARGET_PATH      = "/tmp/dbt/target"
    DBT_LOG_PATH         = "/tmp/dbt/logs"
  }
  env_list = [for k, v in local.env : "${k}=${v}"]

  dags_dir = "${var.repo_root}/dags"
}

# Shared secrets: every Airflow component must see the same values.
resource "random_id" "fernet_key" {
  byte_length = 32
}

resource "random_password" "jwt_secret" {
  length  = 48
  special = false
}

resource "random_password" "api_secret_key" {
  length  = 48
  special = false
}

resource "docker_image" "airflow" {
  name = "${var.project_name}-airflow:local"

  build {
    context    = var.repo_root
    dockerfile = "services/airflow/Dockerfile"
    build_args = {
      AIRFLOW_IMAGE        = var.base_image
      DBT_CORE_VERSION     = var.dbt_core_version
      DBT_POSTGRES_VERSION = var.dbt_postgres_version
    }
    label = var.labels
  }

  triggers = {
    build_hash = local.build_hash
  }
}

# One-shot metadata migration; the apply waits for it and fails if it fails.
resource "docker_container" "init" {
  name     = "${var.project_name}-airflow-init"
  image    = docker_image.airflow.image_id
  command  = ["airflow", "db", "migrate"]
  env      = local.env_list
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
      error_message = "airflow db migrate failed; see the logs of the airflow-init container."
    }
  }
}

resource "docker_container" "api_server" {
  name     = "${var.project_name}-airflow-api-server"
  image    = docker_image.airflow.image_id
  hostname = "airflow-api-server"
  restart  = "unless-stopped"
  # The simple auth manager opens its passwords file read-write, so the file is written at start
  # from the admin password instead of being mounted.
  command = ["bash", "-c", "printf '{\"admin\": \"%s\"}' \"$AIRFLOW_ADMIN_PASSWORD\" > ${local.passwords_file} && exec airflow api-server"]
  env     = concat(local.env_list, ["AIRFLOW_ADMIN_PASSWORD=${var.admin_password}"])

  networks_advanced {
    name    = var.network_name
    aliases = ["airflow-api-server"]
  }

  ports {
    internal = 8080
    external = var.host_port
    ip       = "127.0.0.1"
  }

  healthcheck {
    test         = ["CMD-SHELL", "curl --fail --silent http://localhost:8080/api/v2/monitor/health > /dev/null"]
    interval     = "10s"
    timeout      = "10s"
    retries      = 18
    start_period = "20s"
  }

  wait         = true
  wait_timeout = 300

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }

  depends_on = [docker_container.init]
}

resource "docker_container" "scheduler" {
  name    = "${var.project_name}-airflow-scheduler"
  image   = docker_image.airflow.image_id
  restart = "unless-stopped"
  command = ["airflow", "scheduler"]
  env     = local.env_list

  networks_advanced {
    name = var.network_name
  }

  mounts {
    type      = "bind"
    source    = local.dags_dir
    target    = "/opt/airflow/dags"
    read_only = true
  }

  healthcheck {
    test         = ["CMD-SHELL", "curl --fail --silent http://localhost:8974/health > /dev/null"]
    interval     = "10s"
    timeout      = "10s"
    retries      = 18
    start_period = "20s"
  }

  wait         = true
  wait_timeout = 300

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }

  depends_on = [docker_container.api_server]
}

resource "docker_container" "dag_processor" {
  name    = "${var.project_name}-airflow-dag-processor"
  image   = docker_image.airflow.image_id
  restart = "unless-stopped"
  command = ["airflow", "dag-processor"]
  env     = local.env_list

  networks_advanced {
    name = var.network_name
  }

  mounts {
    type      = "bind"
    source    = local.dags_dir
    target    = "/opt/airflow/dags"
    read_only = true
  }

  healthcheck {
    test         = ["CMD-SHELL", "airflow jobs check --job-type DagProcessorJob --local > /dev/null"]
    interval     = "30s"
    timeout      = "30s"
    retries      = 10
    start_period = "30s"
  }

  wait         = true
  wait_timeout = 300

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }

  depends_on = [docker_container.init]
}
