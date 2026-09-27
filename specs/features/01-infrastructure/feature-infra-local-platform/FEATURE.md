# F01.2: Local Platform (Network, Kafka, Postgres)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Done | [01](../../../01-infrastructure.md) | T1.1–T1.4 | infra-foundations | 1 |

## 1. Goal
Use Terraform (docker provider) to bring up the local runtime platform: the Docker network, Kafka (KRaft), Kafka UI and Postgres.

## 2. Scope
- **In:**
  - `modules/local/{network,kafka,postgres}`
  - The root stack `envs/local/10-platform`
  - Its outputs (host and in-network endpoints, and admin credentials for Postgres)
- **Out:**
  - Topics, databases and roles (F01.3)
  - Application containers (their own features)

## 3. Implementation definition
- **`modules/local/network`:** a `docker_network` named `${project_name}-net`.
- **`modules/local/kafka`:**
  - Kafka container:
    - Image `apache/kafka:<pinned>`, running KRaft combined mode (broker + controller) as a single node.
    - Listeners: `INTERNAL://kafka:19092`, `EXTERNAL://127.0.0.1:9092`, `CONTROLLER://kafka:9093`.
    - Replication factor and min ISR set to 1.
    - Automatic topic creation turned **off**.
  - Kafka UI container: `provectuslabs/kafka-ui:<pinned>` on `:8085`, pointed at `kafka:19092`.
  - Healthcheck on the broker port.
- **`modules/local/postgres`:**
  - Image `postgres:<pinned>` on host port `var.postgres_host_port` (default `5432`), with the named volume `${project_name}-pgdata` mounted at `/var/lib/postgresql`.
  - A machine where 5432 is taken (for example by a native Postgres install) overrides the port in a gitignored `*.local.auto.tfvars` file in the stack directory. Consumers read the port from the `postgres_port` output, never assume it.
  - The superuser password comes from `random_password`. After each container start, Terraform sets it with `ALTER USER`, because Postgres only reads `POSTGRES_PASSWORD` when it initializes an empty data directory (this matters when `keep_data = true` reuses the volume after the old state is destroyed).
  - Healthcheck: `pg_isready` over TCP (`-h 127.0.0.1`), so the temporary init server doesn't count as ready.
  - `keep_data` (default `false`): when `true`, the volume isn't managed by Terraform, so `destroy` leaves it and the next apply reuses it.
- **All host ports bind to `127.0.0.1` only.** Images are pulled with `keep_locally = true`, so a destroy doesn't delete them.
- **`envs/local/10-platform`:**
  - Wires the three modules together and uses the local backend.
  - Image tags come from `versions.env` through `TF_VAR_kafka_image`, `TF_VAR_kafka_ui_image` and `TF_VAR_postgres_image`, which the Makefile and the E2E helpers export. The provider pins in `versions.tf` must match `versions.env`.
  - The contract inputs are in the committed `terraform.tfvars`.
  - Outputs: `kafka_bootstrap_host`, `kafka_bootstrap_internal`, `postgres_host`, `postgres_port`, `postgres_admin_user`, `postgres_admin_password` (sensitive), `network_name`.

## 4. Interfaces
- **Consumes:** the contract inputs (`project_name`, `environment`, `labels`) and `versions.env`.
- **Produces:** the outputs listed above, which F01.3 reads through `terraform_remote_state`.

## 5. E2E test flows
**E2E-1: platform comes up and can be reached.**
1. Apply `envs/local/10-platform`.
2. Every container reports healthy.
3. From the host, a Kafka admin client can list the cluster metadata on `127.0.0.1:9092`. Host-facing endpoints use `127.0.0.1`, not `localhost`: the ports are bound to IPv4 only, and `localhost` resolves to `::1` first, which stalls clients on Windows.
4. A throwaway container on `${project_name}-net` reaches `kafka:19092`.
5. The Kafka UI returns HTTP 200 on `:8085`.
6. A Postgres client on the host connects to `localhost:<postgres_port>` with the admin outputs and runs `SELECT 1`.

**E2E-2: lifecycle.**
1. Apply (if needed), then plan again. The plan shows **no changes**.
2. Destroy the stack. No containers or networks with the project prefix remain.
3. The `pgdata` volume is removed, unless the variable `keep_data = true` is set, in which case it's kept and reused on the next apply.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=infra-local-platform`, and `terraform fmt` and `validate` are clean.

## 7. Open items
None.
