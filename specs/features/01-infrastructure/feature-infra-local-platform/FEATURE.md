# F01.2: Local Platform (Network, Kafka, Postgres)

| Status | Spec | Tasks | Depends on | Phase |
|---|---|---|---|---|
| Not started | [01](../../../01-infrastructure.md) | T1.1–T1.4 | F01.1 | 1 |

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
    - Listeners: `INTERNAL://kafka:19092`, `EXTERNAL://localhost:9092`, `CONTROLLER://kafka:9093`.
    - Replication factor and min ISR set to 1.
    - Automatic topic creation turned **off**.
  - Kafka UI container: `provectuslabs/kafka-ui:<pinned>` on `:8085`, pointed at `kafka:19092`.
  - Healthcheck on the broker port.
- **`modules/local/postgres`:**
  - Image `postgres:<pinned>` on `:5432`, with a named volume `pgdata`.
  - The superuser password comes from `random_password`.
  - Healthcheck: `pg_isready`.
- **`envs/local/10-platform`:**
  - Wires the three modules together and uses the local backend.
  - Outputs: `kafka_bootstrap_host`, `kafka_bootstrap_internal`, `postgres_host`, `postgres_port`, `postgres_admin_user`, `postgres_admin_password` (sensitive), `network_name`.

## 4. Interfaces
- **Consumes:** the contract inputs (`project_name`, `environment`, `labels`) and `versions.env`.
- **Produces:** the outputs listed above, which F01.3 reads through `terraform_remote_state`.

## 5. E2E test flows
**E2E-1: platform comes up and can be reached.**
1. Apply `envs/local/10-platform`.
2. Every container reports healthy.
3. From the host, a Kafka admin client can list the cluster metadata on `localhost:9092`.
4. A throwaway container on `${project_name}-net` reaches `kafka:19092`.
5. The Kafka UI returns HTTP 200 on `:8085`.
6. `psql` on `localhost:5432` runs `SELECT 1`.

**E2E-2: lifecycle.**
1. Apply again. The plan shows **no changes**.
2. Destroy the stack. No containers or networks with the project prefix remain.
3. The `pgdata` volume is removed, unless the variable `keep_data = true` is set, in which case it's kept and reused on the next apply.

## 6. Definition of done
Both flows pass through `make e2e FEATURE=F01.2`, and `terraform fmt` and `validate` are clean.

## 7. Open items
None.
