"""Migrations must produce exactly the schema the ORM expects."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.config import settings
from app.db import engine
from app.models import Base
from sqlalchemy import create_engine, inspect

API_ROOT = Path(__file__).resolve().parents[1] / "services" / "api"


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def test_alembic_upgrade_head_matches_the_orm_metadata(monkeypatch):
    monkeypatch.setenv("FORECASTOPS_SKIP_ALEMBIC_LOGGING", "1")
    Base.metadata.drop_all(engine)

    config = _alembic_config()
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # idempotent

    inspector = inspect(create_engine(settings.database_url))
    migrated = {name for name in inspector.get_table_names() if name != "alembic_version"}
    assert migrated == set(Base.metadata.tables)

    # Spot-check that constraints from the model survive the migration.
    uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("forecast_jobs")}
    assert any(name and "idempotency" in name for name in uniques)
