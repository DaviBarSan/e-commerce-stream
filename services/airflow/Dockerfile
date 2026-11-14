# Airflow image for local orchestration (spec 05 §7, D17). Built by terraform/modules/local/airflow;
# the build context is the repo root (see /.dockerignore).
ARG AIRFLOW_IMAGE
FROM ${AIRFLOW_IMAGE}

ARG DBT_CORE_VERSION
ARG DBT_POSTGRES_VERSION

USER root

# dbt gets its own virtualenv so none of its dependencies land in Airflow's environment.
RUN python -m venv /opt/dbt-venv \
 && /opt/dbt-venv/bin/pip install --no-cache-dir "dbt-core==${DBT_CORE_VERSION}" "dbt-postgres==${DBT_POSTGRES_VERSION}"

# The dbt project, with its packages installed at build time. profiles.yml only needs a DSN to render.
COPY dbt/ /opt/dbt/
RUN cd /opt/dbt \
 && DBT_WAREHOUSE_DSN=postgresql://build:build@localhost:5432/build /opt/dbt-venv/bin/dbt deps --profiles-dir . \
 && rm -rf logs target

# The project stays read-only: runs write their artifacts and logs under /tmp (DBT_TARGET_PATH, DBT_LOG_PATH).
ENV DBT_PROJECT_DIR=/opt/dbt \
    DBT_PROFILES_DIR=/opt/dbt \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false

USER airflow
