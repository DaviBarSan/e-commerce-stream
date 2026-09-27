# Environment contract inputs for local (spec 01 §4.1).
project_name = "clickstream"
environment  = "local"
topics = {
  events     = { partitions = 3, retention_hours = 168 }
  events_dlq = { partitions = 1, retention_hours = 336 }
}
warehouse_raw_schema = "raw"
labels = {
  owner = "davi"
}
