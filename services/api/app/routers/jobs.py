"""Forecast job API: create, inspect, cancel and retry."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from forecastops_forecasting import MODEL_KEYS
from forecastops_forecasting.models import validate_model_params
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import AuthContext, get_auth, get_dataset, get_job, require_role
from ..errors import AppError, ConflictError, NotFoundError
from ..models import (
    DatasetVersion,
    ForecastJob,
    ForecastRun,
    MetricResult,
    ModelConfiguration,
    utcnow,
)
from ..observability import get_request_id
from ..schemas import ForecastJobCreate
from ..serializers import job as serialize_job
from ..serializers import metrics_dict, run_summary
from ..services import audit, queue
from ..services.ratelimit import enforce

router = APIRouter(prefix="/forecast-jobs", tags=["forecast jobs"])
logger = logging.getLogger("forecastops.jobs")


def _aggregate_for(db: Session, run_ids: list[int]) -> dict[int, dict[str, float | None]]:
    if not run_ids:
        return {}
    rows = db.scalars(
        select(MetricResult).where(MetricResult.run_id.in_(run_ids), MetricResult.scope == "aggregate")
    ).all()
    grouped: dict[int, list[MetricResult]] = {}
    for row in rows:
        grouped.setdefault(row.run_id, []).append(row)
    return {run_id: metrics_dict(items) for run_id, items in grouped.items()}


def _resolve_version(db: Session, auth: AuthContext, payload: ForecastJobCreate) -> DatasetVersion:
    dataset = get_dataset(db, auth, payload.dataset_id)
    version_id = payload.dataset_version_id or dataset.current_version_id
    if not version_id:
        raise NotFoundError("This dataset has no imported version yet.")
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == version_id, DatasetVersion.dataset_id == dataset.id
        )
    )
    if version is None:
        raise NotFoundError("Dataset version not found.")
    return version


def _upsert_model_configurations(db: Session, auth: AuthContext, job: ForecastJob) -> None:
    for key in job.model_keys:
        params = validate_model_params(key, (job.model_params or {}).get(key))
        existing = db.scalar(
            select(ModelConfiguration).where(
                ModelConfiguration.org_id == auth.org_id,
                ModelConfiguration.key == key,
                ModelConfiguration.name == "default",
            )
        )
        if existing is None:
            db.add(
                ModelConfiguration(
                    org_id=auth.org_id,
                    key=key,
                    name="default",
                    params=params,
                    is_default=True,
                )
            )
        else:
            existing.params = params
            db.add(existing)


def _validate_bounds(payload: ForecastJobCreate) -> None:
    if payload.horizon_days > settings.max_horizon_days:
        raise AppError(
            f"horizon_days is limited to {settings.max_horizon_days}.",
            code="horizon_too_large",
        )
    if payload.holdout_days > settings.max_holdout_days:
        raise AppError(
            f"holdout_days is limited to {settings.max_holdout_days}.",
            code="holdout_too_large",
        )
    if payload.validation_folds > settings.max_validation_folds:
        raise AppError(
            f"validation_folds is limited to {settings.max_validation_folds}.",
            code="folds_too_large",
        )
    unknown = [key for key in payload.model_keys if key not in MODEL_KEYS]
    if unknown:
        raise AppError(f"Unknown model(s): {', '.join(unknown)}.", code="unknown_model")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_job(
    payload: ForecastJobCreate,
    response: Response,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    enforce(f"job:{auth.user.id}", settings.job_rate_limit)
    _validate_bounds(payload)
    version = _resolve_version(db, auth, payload)

    if version.series_count > settings.max_series:
        raise AppError(
            f"Forecast jobs are limited to {settings.max_series} series; this version has {version.series_count}.",
            code="too_many_series",
        )

    model_keys: list[str] = list(payload.model_keys)
    if "seasonal_naive" not in model_keys:
        # The baseline is mandatory for comparability; adding it is explicit in the response.
        model_keys.insert(0, "seasonal_naive")

    idempotency_key = payload.idempotency_key or uuid.uuid4().hex
    existing = db.scalar(
        select(ForecastJob).where(
            ForecastJob.org_id == auth.org_id, ForecastJob.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return {
            "job": serialize_job(existing),
            "runs": _runs_for_job(db, existing.id),
            "idempotentReplay": True,
            "dispatch_mode": settings.execution_mode,
        }

    job = ForecastJob(
        org_id=auth.org_id,
        dataset_id=version.dataset_id,
        dataset_version_id=version.id,
        status="queued",
        stage="queued",
        progress=0,
        horizon_days=payload.horizon_days,
        holdout_days=payload.holdout_days,
        validation_folds=payload.validation_folds,
        seed=payload.seed,
        model_keys=model_keys,
        model_params=payload.model_params,
        idempotency_key=idempotency_key,
        attempt=1,
        request_id=get_request_id(),
        created_by_id=auth.user.id,
        created_at=utcnow(),
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent identical request
        db.rollback()
        existing = db.scalar(
            select(ForecastJob).where(
                ForecastJob.org_id == auth.org_id, ForecastJob.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            raise ConflictError("The job could not be created. Try again.") from exc
        response.status_code = status.HTTP_200_OK
        return {"job": serialize_job(existing), "runs": _runs_for_job(db, existing.id), "idempotentReplay": True}

    _upsert_model_configurations(db, auth, job)
    audit.record(
        db,
        org_id=auth.org_id,
        action="forecast_job.created",
        entity_type="forecast_job",
        entity_id=job.id,
        actor_user_id=auth.user.id,
        payload={
            "dataset_version_id": version.id,
            "horizon_days": job.horizon_days,
            "holdout_days": job.holdout_days,
            "validation_folds": job.validation_folds,
            "models": model_keys,
            "baseline_added": "seasonal_naive" not in payload.model_keys,
        },
    )
    db.commit()  # the worker thread must see the queued row before dispatch
    dispatch_mode = queue.dispatch(db, job)
    db.refresh(job)
    return {
        "job": serialize_job(job),
        "runs": [],
        "baseline_added": "seasonal_naive" not in payload.model_keys,
        "dispatch_mode": dispatch_mode,
    }


def _runs_for_job(db: Session, job_id: int) -> list[dict]:
    runs = db.scalars(select(ForecastRun).where(ForecastRun.job_id == job_id).order_by(ForecastRun.id)).all()
    aggregates = _aggregate_for(db, [run.id for run in runs])
    return [run_summary(run, aggregates.get(run.id)) for run in runs]


@router.get("")
def list_jobs(
    dataset_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    query = select(ForecastJob).where(ForecastJob.org_id == auth.org_id)
    if dataset_id is not None:
        query = query.where(ForecastJob.dataset_id == dataset_id)
    jobs = db.scalars(query.order_by(ForecastJob.id.desc()).limit(limit)).all()
    return {"jobs": [serialize_job(row) for row in jobs]}


@router.get("/{job_id}")
def get_job_detail(
    job_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job(db, auth, job_id)
    return {"job": serialize_job(job), "runs": _runs_for_job(db, job.id)}


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: int,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job(db, auth, job_id)
    if job.status in {"succeeded", "failed", "cancelled"}:
        raise ConflictError(f"This job already finished with status '{job.status}'.")
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished_at = utcnow()
    else:
        job.stage = "cancelling"
    db.add(job)
    audit.record(
        db,
        org_id=auth.org_id,
        action="forecast_job.cancel_requested",
        entity_type="forecast_job",
        entity_id=job.id,
        actor_user_id=auth.user.id,
        payload={"status": job.status},
    )
    db.flush()
    return {"job": serialize_job(job)}


@router.post("/{job_id}/retry", status_code=status.HTTP_201_CREATED)
def retry_job(
    job_id: int,
    response: Response,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    """Retry a failed or cancelled job as a *new* attempt.

    Completed artifacts are keyed by job id, so a retry can never duplicate a successful
    run's points or metrics.
    """

    enforce(f"job:{auth.user.id}", settings.job_rate_limit)
    original = get_job(db, auth, job_id)
    if original.status not in {"failed", "cancelled"}:
        raise ConflictError("Only failed or cancelled jobs can be retried.")

    sibling = db.scalar(
        select(ForecastJob).where(
            ForecastJob.parent_job_id == original.id, ForecastJob.status.in_(["queued", "running"])
        )
    )
    if sibling is not None:
        response.status_code = status.HTTP_200_OK
        return {"job": serialize_job(sibling), "already_retrying": True}

    retry = ForecastJob(
        org_id=auth.org_id,
        dataset_id=original.dataset_id,
        dataset_version_id=original.dataset_version_id,
        status="queued",
        stage="queued",
        progress=0,
        horizon_days=original.horizon_days,
        holdout_days=original.holdout_days,
        validation_folds=original.validation_folds,
        seed=original.seed,
        model_keys=list(original.model_keys or []),
        model_params=dict(original.model_params or {}),
        idempotency_key=f"{original.idempotency_key}:retry{original.attempt + 1}"[:120],
        attempt=original.attempt + 1,
        parent_job_id=original.id,
        request_id=get_request_id(),
        created_by_id=auth.user.id,
        created_at=utcnow(),
    )
    db.add(retry)
    db.flush()
    audit.record(
        db,
        org_id=auth.org_id,
        action="forecast_job.retried",
        entity_type="forecast_job",
        entity_id=retry.id,
        actor_user_id=auth.user.id,
        payload={"parent_job_id": original.id, "attempt": retry.attempt},
    )
    db.commit()
    dispatch_mode = queue.dispatch(db, retry)
    db.refresh(retry)
    return {"job": serialize_job(retry), "dispatch_mode": dispatch_mode}


@router.get("/{job_id}/runs")
def list_job_runs(
    job_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job(db, auth, job_id)
    return {"runs": _runs_for_job(db, job.id), "selected_model": _selected_model(db, job.id)}


def _selected_model(db: Session, job_id: int) -> str | None:
    run = db.scalar(select(ForecastRun).where(ForecastRun.job_id == job_id, ForecastRun.is_selected.is_(True)))
    return run.model_key if run else None
