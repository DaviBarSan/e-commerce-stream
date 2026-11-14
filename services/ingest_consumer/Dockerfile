# Ingest consumer image (spec 05, F05.2). Built by terraform/modules/local/consumer; the build context is the
# repo root (see /.dockerignore), because the consumer depends on the `telemetry` package of the uv workspace.
ARG PYTHON_IMAGE
ARG UV_IMAGE

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /bin/uv
# The venv is built at its final path: console scripts hard-code their interpreter path.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# The workspace needs every member's pyproject to resolve uv.lock; only the consumer's sources are installed.
COPY pyproject.toml uv.lock ./
COPY telemetry/ telemetry/
COPY services/ingest_consumer/ services/ingest_consumer/
COPY services/store_backend/pyproject.toml services/store_backend/
COPY services/store_frontend/pyproject.toml services/store_frontend/
RUN uv sync --frozen --no-default-groups --no-editable --package ingest-consumer

FROM ${PYTHON_IMAGE}
RUN useradd --create-home --uid 1000 app
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
# SIGTERM (docker stop, terraform destroy) runs the consumer's flush-commit-close shutdown.
CMD ["python", "-m", "ingest_consumer"]
