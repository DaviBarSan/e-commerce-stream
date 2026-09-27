"""Store API entry point: `uvicorn store_backend.main:app --port 8000`."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from store_backend.db import create_schema, make_engine, session_factory
from store_backend.identity import IdentityMiddleware
from store_backend.routers import cart, catalog, checkout
from store_backend.settings import Settings
from telemetry import get_producer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    engine = make_engine(settings.store_db_dsn)
    create_schema(engine)
    app.state.sessions = session_factory(engine)
    app.state.producer = get_producer()  # one producer per process (spec 04 §5)
    try:
        yield
    finally:
        app.state.producer.close()  # flushes pending events
        engine.dispose()


app = FastAPI(title="Store API", version="1.0.0", lifespan=lifespan)
app.add_middleware(IdentityMiddleware)
app.include_router(catalog.router)
app.include_router(cart.router)
app.include_router(checkout.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
