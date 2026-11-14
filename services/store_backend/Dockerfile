# Store API image (spec 02, F02.3). Built by terraform/modules/local/app; the build context is the repo root
# (see /.dockerignore), because the API depends on the `telemetry` package of the uv workspace.
ARG PYTHON_IMAGE
ARG UV_IMAGE

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /bin/uv
# The venv is built at its final path: console scripts (uvicorn) hard-code their interpreter path.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# The workspace needs every member's pyproject to resolve uv.lock; only the API's sources are installed.
COPY pyproject.toml uv.lock ./
COPY telemetry/ telemetry/
COPY services/store_backend/ services/store_backend/
COPY services/store_frontend/pyproject.toml services/store_frontend/
COPY services/ingest_consumer/pyproject.toml services/ingest_consumer/
RUN uv sync --frozen --no-default-groups --no-editable --package store-backend

FROM ${PYTHON_IMAGE}
RUN useradd --create-home --uid 1000 app
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "store_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
