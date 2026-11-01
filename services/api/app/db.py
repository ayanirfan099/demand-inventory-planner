"""Database engine, session factory and request-scoped session dependency."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


def _build_engine(url: str | None = None) -> Engine:
    database_url = url or settings.database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}
    if database_url.startswith("sqlite"):
        # A file-backed SQLite database is shared with in-process worker threads, so the
        # connection must not be pinned to the creating thread.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(database_url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001 - SQLAlchemy hook
    """Enable foreign keys and WAL on SQLite (no-op for PostgreSQL)."""

    module = type(dbapi_connection).__module__
    if not module.startswith("sqlite3"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope used by workers and scripts."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: commits on success, rolls back on error."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
