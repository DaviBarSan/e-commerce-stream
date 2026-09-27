locals {
  roles = toset(["store_app", "ingest_writer", "dbt_runner", "airflow"])
}

resource "random_password" "role" {
  for_each = local.roles
  length   = 32
  special  = false
}

resource "postgresql_role" "this" {
  for_each = local.roles
  name     = each.key
  login    = true
  password = random_password.role[each.key].result
}

# --- store: owned by store_app ---
resource "postgresql_database" "store" {
  name  = "store"
  owner = postgresql_role.this["store_app"].name
}

# --- airflow: owned by airflow ---
resource "postgresql_database" "airflow" {
  name  = "airflow"
  owner = postgresql_role.this["airflow"].name
}

# --- warehouse: raw (ingest_writer), staging + marts (dbt_runner) ---
resource "postgresql_database" "warehouse" {
  name = "warehouse"
}

resource "postgresql_schema" "raw" {
  name         = var.warehouse_raw_schema
  database     = postgresql_database.warehouse.name
  owner        = postgresql_role.this["ingest_writer"].name
  drop_cascade = true
}

resource "postgresql_schema" "dbt" {
  for_each     = toset(["staging", "marts"])
  name         = each.key
  database     = postgresql_database.warehouse.name
  owner        = postgresql_role.this["dbt_runner"].name
  drop_cascade = true
}

# dbt_runner reads raw: USAGE on the schema, SELECT on every table ingest_writer creates there.
resource "postgresql_grant" "dbt_raw_usage" {
  database    = postgresql_database.warehouse.name
  schema      = postgresql_schema.raw.name
  role        = postgresql_role.this["dbt_runner"].name
  object_type = "schema"
  privileges  = ["USAGE"]
}

resource "postgresql_default_privileges" "dbt_raw_select" {
  database    = postgresql_database.warehouse.name
  schema      = postgresql_schema.raw.name
  owner       = postgresql_role.this["ingest_writer"].name
  role        = postgresql_role.this["dbt_runner"].name
  object_type = "table"
  privileges  = ["SELECT"]
}
