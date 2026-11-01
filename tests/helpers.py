"""Test helpers shared by API and worker tests.

Imported only after ``tests/conftest.py`` has configured the environment, which pytest
guarantees because the root conftest is loaded before test modules.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from app.db import SessionLocal
from app.models import Dataset, ForecastJob, ForecastRun
from app.services.runner import run_forecast_job
from fastapi.testclient import TestClient
from forecastops_forecasting import generate_demo_demand
from sqlalchemy import select

PASSWORDS = {
    "owner@test.example": "owner-password-1",
    "analyst@test.example": "analyst-password-1",
    "viewer@test.example": "viewer-password-1",
    "other@test.example": "other-password-1",
}


def demand_frame(
    *,
    days: int = 120,
    stores: tuple[str, ...] = ("s1", "s2"),
    items: tuple[str, ...] = ("i1", "i2"),
    seed: int = 7,
    end_date: date = date(2025, 6, 30),
) -> pd.DataFrame:
    return generate_demo_demand(days=days, seed=seed, stores=stores, items=items, end_date=end_date)


def frame_to_csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def login(client: TestClient, email: str) -> TestClient:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORDS[email]},
    )
    assert response.status_code == 200, response.text
    return client


def create_job(
    dataset_id: int,
    *,
    user_id: int | None = None,
    idempotency_key: str | None = None,
    **kwargs,
) -> int:
    """Insert a queued job row directly (bypassing dispatch) and return its id."""

    with SessionLocal() as session:
        dataset = session.get(Dataset, dataset_id)
        assert dataset is not None
        job = ForecastJob(
            org_id=dataset.org_id,
            dataset_id=dataset.id,
            dataset_version_id=dataset.current_version_id,
            status="queued",
            stage="queued",
            horizon_days=kwargs.get("horizon_days", 10),
            holdout_days=kwargs.get("holdout_days", 10),
            validation_folds=kwargs.get("validation_folds", 1),
            seed=kwargs.get("seed", 42),
            model_keys=kwargs.get("model_keys", ["seasonal_naive", "hist_gradient_boosting"]),
            model_params=kwargs.get("model_params", {}),
            idempotency_key=idempotency_key or f"helper-job-{dataset_id}-{kwargs.get('seed', 42)}",
            attempt=kwargs.get("attempt", 1),
            created_by_id=user_id,
        )
        session.add(job)
        session.commit()
        return job.id


def create_completed_job(dataset_id: int, *, user_id: int | None = None, **kwargs) -> int:
    job_id = create_job(dataset_id, user_id=user_id, **kwargs)
    run_forecast_job(job_id)
    return job_id


def run_ids(job_id: int) -> list[int]:
    with SessionLocal() as session:
        rows = session.scalars(select(ForecastRun).where(ForecastRun.job_id == job_id)).all()
        return [row.id for row in rows]


def selected_run_id(job_id: int) -> int | None:
    with SessionLocal() as session:
        row = session.scalar(
            select(ForecastRun).where(ForecastRun.job_id == job_id, ForecastRun.is_selected.is_(True))
        )
        return row.id if row else None
