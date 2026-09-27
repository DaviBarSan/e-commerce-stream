"""Database engine and sessions (SQLAlchemy 2, psycopg 3)."""
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from store_backend.models import Base


def make_engine(dsn: str) -> Engine:
    # The contract DSN is a plain postgresql:// URL; select the psycopg 3 driver.
    url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


def create_schema(engine: Engine) -> None:
    """Create missing tables. No migration tool: local schema changes recreate the environment."""
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
