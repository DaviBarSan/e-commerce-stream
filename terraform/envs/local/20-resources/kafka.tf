locals {
  # Logical topic -> Kafka topic name (spec 04 §6).
  kafka_topic_names = {
    events     = "${var.project_name}.events.v1"
    events_dlq = "${var.project_name}.events.dlq"
  }
}

resource "kafka_topic" "this" {
  for_each = var.topics

  name               = local.kafka_topic_names[each.key]
  partitions         = each.value.partitions
  replication_factor = 1

  config = {
    "cleanup.policy" = "delete"
    "retention.ms"   = tostring(each.value.retention_hours * 3600 * 1000)
  }
}
