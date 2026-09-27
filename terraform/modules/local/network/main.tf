resource "docker_network" "this" {
  name = "${var.project_name}-net"

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}
