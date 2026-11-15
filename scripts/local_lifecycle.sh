#!/usr/bin/env bash
# make stop / make start (F01.5): pause and resume the local environment without destroying anything.
# Containers, volumes and Terraform state are kept, so data, Airflow history and logs survive.
#
#   stop   services first (the outbox relay drains, the consumer commits), then the platform
#   start  the platform first, wait for it to be healthy, then the long-running services;
#          one-shot containers (no restart policy: airflow-init, store-seed) are not rerun
set -euo pipefail

cd "$(dirname "$0")/.."

action="${1:?usage: local_lifecycle.sh stop|start}"
project="$(sed -n 's/^project_name *= *"\(.*\)"/\1/p' terraform/envs/local/10-platform/terraform.tfvars)"
platform=("$project-postgres" "$project-kafka" "$project-kafka-ui")
timeout_s=180

# Every container of the project that Terraform manages, running or not.
project_containers() {
  docker ps -a --filter "label=project=$project" --filter "label=managed_by=terraform" --format '{{.Names}}'
}

is_platform() { local c; for c in "${platform[@]}"; do [ "$1" = "$c" ] && return 0; done; return 1; }

long_running_services() {
  local name
  for name in $(project_containers); do
    is_platform "$name" && continue
    [ "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name")" = "unless-stopped" ] && echo "$name"
  done
  return 0
}

existing_platform() {
  local name
  for name in "${platform[@]}"; do docker inspect "$name" >/dev/null 2>&1 && echo "$name"; done
  return 0
}

# Waits until each container is running, and healthy when it has a healthcheck.
wait_ready() {
  local name status deadline=$((SECONDS + timeout_s))
  for name in "$@"; do
    while true; do
      status="$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name")"
      case "$status" in
        running/healthy | running/none) break ;;
      esac
      if [ "$SECONDS" -ge "$deadline" ]; then
        echo "start: $name is not ready after ${timeout_s}s ($status); see docker logs $name" >&2
        exit 1
      fi
      sleep 2
    done
  done
}

case "$action" in
  stop)
    mapfile -t services < <(long_running_services)
    mapfile -t base < <(existing_platform)
    [ "${#services[@]}" -gt 0 ] && docker stop -t 30 "${services[@]}" >/dev/null
    [ "${#base[@]}" -gt 0 ] && docker stop -t 30 "${base[@]}" >/dev/null
    echo "stop: ${#services[@]} service and ${#base[@]} platform containers stopped (data kept; make start resumes)"
    ;;
  start)
    mapfile -t base < <(existing_platform)
    if [ "${#base[@]}" -eq 0 ]; then
      echo "start: no $project containers found; run make up" >&2
      exit 1
    fi
    docker start "${base[@]}" >/dev/null
    wait_ready "${base[@]}"
    mapfile -t services < <(long_running_services)
    if [ "${#services[@]}" -gt 0 ]; then
      docker start "${services[@]}" >/dev/null
      wait_ready "${services[@]}"
    fi
    echo "start: ${#base[@]} platform and ${#services[@]} service containers running"
    ;;
  *)
    echo "usage: local_lifecycle.sh stop|start" >&2
    exit 2
    ;;
esac
