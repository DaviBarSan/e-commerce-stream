# Storefront image (spec 02, F02.3): Reflex in production mode, UI and Reflex backend on one port (3000).
# Built by terraform/modules/local/app; the build context is the repo root (see /.dockerignore).
ARG PYTHON_IMAGE
ARG UV_IMAGE

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE}
COPY --from=uv /uv /bin/uv
# Reflex downloads bun to build the frontend; its installer needs curl and unzip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /src
# The workspace needs every member's pyproject to resolve uv.lock; only the storefront's dependencies install.
COPY pyproject.toml uv.lock ./
COPY services/store_backend/pyproject.toml services/store_backend/
COPY services/ingest_consumer/pyproject.toml services/ingest_consumer/
COPY services/store_frontend/pyproject.toml services/store_frontend/
RUN uv sync --frozen --no-default-groups --no-install-workspace --package store-frontend

# Reflex compiles the app from its source folder, so the source stays in the image.
COPY services/store_frontend/ services/store_frontend/
RUN chown -R app:app /src/services/store_frontend
USER app
WORKDIR /src/services/store_frontend
# Warm the build: downloads bun and the frontend packages and builds once, so container starts are quicker.
RUN BACKEND_URL=http://build.invalid reflex export --frontend-only --no-zip --env prod

EXPOSE 3000
CMD ["reflex", "run", "--env", "prod", "--frontend-port", "3000", "--backend-port", "3000", "--backend-host", "0.0.0.0"]
