"""Shared pytest fixtures for API and worker tests.

The environment is configured *before* the application package is imported, because
settings are read once at import time. Each test gets a fresh schema and data directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="forecastops-tests-"))
os.environ["FORECASTOPS_ENVIRONMENT"] = "test"
os.environ["FORECASTOPS_DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["FORECASTOPS_DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["FORECASTOPS_EXECUTION_MODE"] = "external"
os.environ["FORECASTOPS_SESSION_COOKIE_NAME"] = "forecastops_session"
os.environ["FORECASTOPS_ALLOWED_ORIGINS"] = "http://testserver"
os.environ["FORECASTOPS_LOG_LEVEL"] = "WARNING"
os.environ["FORECASTOPS_MAX_UPLOAD_BYTES"] = str(2 * 1024 * 1024)
os.environ["FORECASTOPS_RATE_LIMIT_WINDOW_SECONDS"] = "3600"

import pytest  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Membership, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import ingestion  # noqa: E402
from app.services.ratelimit import limiter  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from forecastops_forecasting import normalize_demand  # noqa: E402

from tests.helpers import PASSWORDS, demand_frame, login  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database():
    """Recreate every table and clear the data directory + rate limiter per test."""

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    data_dir = Path(settings.data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    limiter.reset()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def seeded_org():
    """Two tenants, three roles in tenant A, one dataset per tenant."""

    with SessionLocal() as session:
        org = Organization(name="Tenant A", slug="tenant-a")
        other = Organization(name="Tenant B", slug="tenant-b")
        session.add_all([org, other])
        session.flush()

        user_ids = {}
        for email, password in PASSWORDS.items():
            user = User(email=email, display_name=email.split("@")[0], password_hash=hash_password(password))
            session.add(user)
            session.flush()
            user_ids[email] = user.id

        session.add_all(
            [
                Membership(user_id=user_ids["owner@test.example"], org_id=org.id, role="owner"),
                Membership(user_id=user_ids["analyst@test.example"], org_id=org.id, role="analyst"),
                Membership(user_id=user_ids["viewer@test.example"], org_id=org.id, role="viewer"),
                Membership(user_id=user_ids["other@test.example"], org_id=other.id, role="owner"),
            ]
        )
        session.flush()

        clean, report = normalize_demand(demand_frame())
        primary = ingestion.import_demand(
            session,
            org_id=org.id,
            user_id=user_ids["owner@test.example"],
            name="Test demand",
            description="fixture dataset",
            frame=clean,
            quality=report.as_dict(),
            source="synthetic",
        )
        secondary = ingestion.import_demand(
            session,
            org_id=other.id,
            user_id=user_ids["other@test.example"],
            name="Other tenant demand",
            description="isolation fixture",
            frame=clean,
            quality=report.as_dict(),
            source="synthetic",
        )
        session.commit()

        return {
            "org_id": org.id,
            "other_org_id": other.id,
            "users": user_ids,
            "dataset_id": primary.dataset.id,
            "version_id": primary.version.id,
            "other_dataset_id": secondary.dataset.id,
        }


@pytest.fixture()
def api():
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def owner_client(seeded_org):
    with TestClient(app) as client:
        yield login(client, "owner@test.example")


@pytest.fixture()
def analyst_client(seeded_org):
    with TestClient(app) as client:
        yield login(client, "analyst@test.example")


@pytest.fixture()
def viewer_client(seeded_org):
    with TestClient(app) as client:
        yield login(client, "viewer@test.example")


@pytest.fixture()
def other_client(seeded_org):
    with TestClient(app) as client:
        yield login(client, "other@test.example")


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
