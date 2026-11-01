"""Forecast job lifecycle: queueing, idempotency, cancellation, retries and failure modes."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import ForecastJob, ForecastPoint, ForecastRun, MetricResult
from app.services.runner import run_forecast_job
from sqlalchemy import select

from tests.helpers import create_completed_job, create_job, run_ids, selected_run_id


def test_job_creation_queues_work_and_forces_the_baseline(analyst_client, seeded_org):
    response = analyst_client.post(
        "/api/v1/forecast-jobs",
        json={
            "dataset_id": seeded_org["dataset_id"],
            "horizon_days": 7,
            "holdout_days": 10,
            "validation_folds": 1,
            "model_keys": ["hist_gradient_boosting"],
            "idempotency_key": "job-create-0001",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["job"]["status"] == "queued"
    assert body["job"]["model_keys"] == ["seasonal_naive", "hist_gradient_boosting"]
    assert body["baseline_added"] is True
    assert body["dispatch_mode"] == "external"


def test_completed_job_persists_runs_metrics_and_points(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    detail = owner_client.get(f"/api/v1/forecast-jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["job"]["status"] == "succeeded"
    assert body["job"]["progress"] == 100
    assert len(body["runs"]) == 2
    selected = [run for run in body["runs"] if run["is_selected"]]
    assert len(selected) == 1
    assert selected[0]["metrics"]["wape"] is not None

    run_id = selected[0]["id"]
    points = owner_client.get(f"/api/v1/forecast-runs/{run_id}/points?kind=forecast").json()["points"]
    assert points and all(point["actual"] is None for point in points)
    holdout = owner_client.get(f"/api/v1/forecast-runs/{run_id}/points?kind=holdout").json()["points"]
    assert holdout and all(point["actual"] is not None for point in holdout)


def test_completed_job_is_idempotent_when_delivered_twice(seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"], idempotency_key="double-delivery")
    first_runs = run_ids(job_id)
    with SessionLocal() as session:
        first_points = session.query(ForecastPoint).count()

    run_forecast_job(job_id)  # duplicate delivery

    assert run_ids(job_id) == first_runs
    with SessionLocal() as session:
        assert session.query(ForecastPoint).count() == first_points


def test_duplicate_idempotency_key_returns_the_original_job(analyst_client, seeded_org):
    payload = {"dataset_id": seeded_org["dataset_id"], "idempotency_key": "same-key-00001"}
    first = analyst_client.post("/api/v1/forecast-jobs", json=payload)
    second = analyst_client.post("/api/v1/forecast-jobs", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["idempotentReplay"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]


def test_queued_job_can_be_cancelled(analyst_client, seeded_org):
    job_id = analyst_client.post(
        "/api/v1/forecast-jobs",
        json={"dataset_id": seeded_org["dataset_id"], "idempotency_key": "cancel-me-0001"},
    ).json()["job"]["id"]

    cancelled = analyst_client.post(f"/api/v1/forecast-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["job"]["status"] == "cancelled"

    run_forecast_job(job_id)  # a cancelled job must not run
    detail = analyst_client.get(f"/api/v1/forecast-jobs/{job_id}").json()
    assert detail["job"]["status"] == "cancelled"
    assert detail["runs"] == []

    again = analyst_client.post(f"/api/v1/forecast-jobs/{job_id}/cancel")
    assert again.status_code == 409


def test_running_job_honours_a_cancel_request(analyst_client, seeded_org):
    job_id = create_job(seeded_org["dataset_id"])
    with SessionLocal() as session:
        session.get(ForecastJob, job_id).cancel_requested = True
        session.commit()

    run_forecast_job(job_id)

    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job.status == "cancelled"
        assert session.query(ForecastRun).filter_by(job_id=job_id).count() == 0


def test_failed_job_records_a_structured_reason_and_can_be_retried(analyst_client, seeded_org, monkeypatch):
    import app.services.runner as runner

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic worker explosion")

    monkeypatch.setattr(runner, "run_forecast_job", runner.run_forecast_job)
    job_id = create_job(seeded_org["dataset_id"], idempotency_key="retry-source")
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        job.status = "failed"
        job.failure_code = "worker_error"
        job.failure_message = "The forecast failed unexpectedly. The job can be retried."
        session.commit()

    response = analyst_client.post(f"/api/v1/forecast-jobs/{job_id}/retry")
    assert response.status_code == 201
    retry_body = response.json()["job"]
    assert retry_body["attempt"] == 2
    assert retry_body["parent_job_id"] == job_id
    assert retry_body["status"] == "queued"

    duplicate = analyst_client.post(f"/api/v1/forecast-jobs/{job_id}/retry")
    assert duplicate.status_code == 200
    assert duplicate.json()["already_retrying"] is True


def test_successful_job_cannot_be_retried(analyst_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    assert analyst_client.post(f"/api/v1/forecast-jobs/{job_id}/retry").status_code == 409


def test_worker_missing_is_reported_as_a_failure(analyst_client, seeded_org, monkeypatch):
    from app.config import settings
    from app.services import queue as queue_service

    monkeypatch.setattr(settings, "execution_mode", "rq")
    job_id = create_job(seeded_org["dataset_id"])
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        queue_service.dispatch(session, job)

    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job.status == "failed"
        assert job.failure_code == "queue_unavailable"


def test_invalid_job_parameters_are_rejected(analyst_client, seeded_org):
    too_long = analyst_client.post(
        "/api/v1/forecast-jobs", json={"dataset_id": seeded_org["dataset_id"], "horizon_days": 500}
    )
    assert too_long.status_code == 422

    bad_folds = analyst_client.post(
        "/api/v1/forecast-jobs", json={"dataset_id": seeded_org["dataset_id"], "validation_folds": 9}
    )
    assert bad_folds.status_code == 422

    unknown_model = analyst_client.post(
        "/api/v1/forecast-jobs",
        json={"dataset_id": seeded_org["dataset_id"], "model_keys": ["random_forest"]},
    )
    assert unknown_model.status_code == 422


def test_unknown_dataset_is_a_clean_404(analyst_client, seeded_org):
    response = analyst_client.post("/api/v1/forecast-jobs", json={"dataset_id": 99_999})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_job_failure_creates_an_alert(analyst_client, seeded_org):
    import app.services.runner as runner
    import forecastops_forecasting as package

    def fail(*_args, **_kwargs):
        raise package.StudyError("not enough history", code="insufficient_history")

    original = package.run_forecast_study
    package.run_forecast_study = fail
    try:
        job_id = create_job(seeded_org["dataset_id"], idempotency_key="failing-job")
        runner.run_forecast_job(job_id)
    finally:
        package.run_forecast_study = original

    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job.status == "failed"
        assert job.failure_code == "insufficient_history"

    alerts = analyst_client.get("/api/v1/alerts").json()["alerts"]
    failed = [alert for alert in alerts if alert["kind"] == "failed_job"]
    assert failed and failed[0]["job_id"] == job_id


def test_metrics_are_persisted_for_aggregate_and_series(seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    with SessionLocal() as session:
        aggregate = session.scalars(
            select(MetricResult).where(MetricResult.run_id == run_id, MetricResult.scope == "aggregate")
        ).all()
        series_metrics = session.scalars(
            select(MetricResult).where(MetricResult.run_id == run_id, MetricResult.scope == "series")
        ).all()
    assert {row.metric for row in aggregate} == {"mae", "rmse", "wape", "mase", "bias"}
    assert len({row.series_id for row in series_metrics}) == 4
