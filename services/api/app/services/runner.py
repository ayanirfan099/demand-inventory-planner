"""Forecast job execution.

Shared by the in-process executor, the RQ worker and the database poller, so there is
exactly one implementation of "what a forecast job does". The job row is the contract:
status transitions are ``queued -> running -> succeeded | failed | cancelled`` and every
transition carries a stage, progress percentage and (on failure) a structured reason.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from sqlalchemy import delete, insert, select

from ..db import session_scope
from ..models import (
    ForecastJob,
    ForecastPoint,
    ForecastRun,
    MetricResult,
    SeriesDefinition,
    utcnow,
)
from ..observability import set_job_id
from . import alerts, audit, storage
from .ratelimit import limiter  # noqa: F401 - imported for clarity of module boundaries

logger = logging.getLogger("forecastops.runner")

PUBLIC_METRICS = ("mae", "rmse", "wape", "mase", "bias")

STUDY_ERROR_MESSAGES = {
    "insufficient_history": "The dataset does not contain enough history for the requested holdout and horizon.",
    "invalid_horizon": "The requested horizon is outside the allowed range.",
    "invalid_holdout": "The requested holdout window is outside the allowed range.",
    "invalid_folds": "The requested number of validation folds is outside the allowed range.",
    "baseline_required": "The seasonal-naive baseline must be included.",
    "model_failure": "The model could not produce a finite prediction for this dataset.",
}


class JobCancelled(Exception):
    """Raised inside the study when the job was cancelled by a user."""


class JobTimeout(Exception):
    """Raised when a job exceeds its wall-clock budget."""


def _job_or_none(job_id: int) -> dict[str, Any] | None:
    with session_scope() as db:
        job = db.get(ForecastJob, job_id)
        if job is None:
            logger.warning("job %s no longer exists", job_id)
            return None
        if job.status == "succeeded":
            logger.info("job %s already succeeded; ignoring duplicate delivery", job_id)
            return None
        if job.cancel_requested or job.status == "cancelled":
            job.status = "cancelled"
            job.finished_at = job.finished_at or utcnow()
            job.stage = "cancelled"
            db.add(job)
            return None
        job.status = "running"
        job.started_at = job.started_at or utcnow()
        job.stage = "loading_data"
        job.progress = 2
        job.failure_code = None
        job.failure_message = None
        db.add(job)
        return {
            "id": job.id,
            "org_id": job.org_id,
            "dataset_id": job.dataset_id,
            "dataset_version_id": job.dataset_version_id,
            "horizon_days": job.horizon_days,
            "holdout_days": job.holdout_days,
            "validation_folds": job.validation_folds,
            "seed": job.seed,
            "model_keys": list(job.model_keys or []),
            "model_params": dict(job.model_params or {}),
        }


def _version_path(job_id: int) -> str:
    from ..models import DatasetVersion

    with session_scope() as db:
        job = db.get(ForecastJob, job_id)
        if job is None:
            raise JobCancelled()
        version = db.get(DatasetVersion, job.dataset_version_id)
        if version is None:
            raise RuntimeError("dataset version missing")
        return version.storage_path


def _ticker(job_id: int, started: float, timeout_seconds: int):
    logger_ = logger

    def tick(percent: int, message: str) -> None:
        if time.monotonic() - started > timeout_seconds:
            raise JobTimeout()
        with session_scope() as db:
            job = db.get(ForecastJob, job_id)
            if job is None:
                raise JobCancelled()
            if job.cancel_requested:
                raise JobCancelled()
            job.progress = max(1, min(99, int(percent)))
            job.stage = message[:80]
            db.add(job)
        logger_.info(
            "job progress %s%%: %s", percent, message, extra={"context": {"job_id": job_id, "progress": percent}}
        )

    return tick


def _persist_results(job_id: int, result: dict[str, Any], started_at: float) -> None:
    with session_scope() as db:
        job = db.get(ForecastJob, job_id)
        if job is None:
            return

        series_rows = db.scalars(select(SeriesDefinition).where(SeriesDefinition.dataset_id == job.dataset_id)).all()
        series_ids = {f"{row.store}||{row.item}": row.id for row in series_rows}

        # Idempotency: a retried delivery of the same job replaces its artifacts wholesale
        # rather than appending duplicates. Cascades remove points and metrics.
        db.execute(delete(ForecastRun).where(ForecastRun.job_id == job.id))

        for run in result["runs"]:
            holdout = run["holdout"]
            run_model = ForecastRun(
                org_id=job.org_id,
                job_id=job.id,
                dataset_version_id=job.dataset_version_id,
                model_key=run["model_key"],
                label=run["label"],
                model_config={"params": run["params"], "seed": run["seed"], "requires_fit": run["requires_fit"]},
                forecast_mode=run["forecast_mode"],
                forecast_mode_label=run["forecast_mode_label"],
                is_selected=run["model_key"] == result["selected_model"],
                seed=run["seed"],
                train_start=date.fromisoformat(holdout["train_start"]),
                train_end=date.fromisoformat(holdout["train_end"]),
                test_start=date.fromisoformat(holdout["test_start"]),
                test_end=date.fromisoformat(holdout["test_end"]),
                horizon_days=result["config"]["horizon_days"],
                limitations=list(result["limitations"]),
                validation_folds=list(run.get("validation_folds") or []),
            )
            db.add(run_model)
            db.flush()

            aggregate = run["metrics"]["aggregate"]
            metric_rows = [
                MetricResult(
                    org_id=job.org_id,
                    run_id=run_model.id,
                    scope="aggregate",
                    series_id=None,
                    metric=metric,
                    value=aggregate.get(metric),
                )
                for metric in PUBLIC_METRICS
            ]
            for row in run["metrics"]["per_series"]:
                series_id = series_ids.get(row["series_key"])
                if series_id is None:
                    continue
                for metric in PUBLIC_METRICS:
                    metric_rows.append(
                        MetricResult(
                            org_id=job.org_id,
                            run_id=run_model.id,
                            scope="series",
                            series_id=series_id,
                            metric=metric,
                            value=row.get(metric),
                        )
                    )
            db.add_all(metric_rows)

            point_rows = []
            test_start = date.fromisoformat(holdout["test_start"])
            for point in run["holdout_points"]:
                series_id = series_ids.get(point["series_key"])
                if series_id is None:
                    continue
                target = date.fromisoformat(point["date"])
                point_rows.append(
                    {
                        "org_id": job.org_id,
                        "run_id": run_model.id,
                        "series_id": series_id,
                        "kind": "holdout",
                        "target_date": target,
                        "horizon_step": (target - test_start).days + 1,
                        "forecast": float(point["forecast"]),
                        "actual": float(point["actual"]),
                        "lower": None,
                        "upper": None,
                    }
                )
            forecast_start = min((date.fromisoformat(p["date"]) for p in run["forecast_points"]), default=None)
            for point in run["forecast_points"]:
                series_id = series_ids.get(point["series_key"])
                if series_id is None:
                    continue
                target = date.fromisoformat(point["date"])
                point_rows.append(
                    {
                        "org_id": job.org_id,
                        "run_id": run_model.id,
                        "series_id": series_id,
                        "kind": "forecast",
                        "target_date": target,
                        "horizon_step": (target - forecast_start).days + 1 if forecast_start else 1,
                        "forecast": float(point["forecast"]),
                        "actual": None,
                        "lower": float(point.get("lower") or 0.0),
                        "upper": float(point.get("upper") or 0.0),
                    }
                )
            if point_rows:
                db.execute(insert(ForecastPoint), point_rows)

        job.status = "succeeded"
        job.progress = 100
        job.stage = "completed"
        job.finished_at = utcnow()
        job.failure_code = None
        job.failure_message = None
        db.add(job)

        audit.record(
            db,
            org_id=job.org_id,
            action="forecast_job.succeeded",
            entity_type="forecast_job",
            entity_id=job.id,
            actor_user_id=job.created_by_id,
            payload={
                "selected_model": result["selected_model"],
                "horizon_days": job.horizon_days,
                "holdout_days": job.holdout_days,
                "duration_seconds": round(time.monotonic() - started_at, 2),
                "models": [run["model_key"] for run in result["runs"]],
            },
        )
        alerts.refresh_for_job(db, job)


def _fail(job_id: int, code: str, message: str, *, detail: str | None = None) -> None:
    with session_scope() as db:
        job = db.get(ForecastJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.stage = "failed"
        job.failure_code = code
        job.failure_message = message[:500]
        job.finished_at = utcnow()
        db.add(job)
        audit.record(
            db,
            org_id=job.org_id,
            action="forecast_job.failed",
            entity_type="forecast_job",
            entity_id=job.id,
            actor_user_id=job.created_by_id,
            payload={"code": code, "message": message},
        )
        alerts.raise_job_failure(db, job, code, message)
        logger.error(
            "job failed: %s (%s)",
            code,
            detail or message,
            extra={"context": {"job_id": job_id, "code": code}},
        )


def _cancel(job_id: int) -> None:
    with session_scope() as db:
        job = db.get(ForecastJob, job_id)
        if job is None or job.status in {"succeeded", "failed"}:
            return
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished_at = utcnow()
        db.add(job)
        audit.record(
            db,
            org_id=job.org_id,
            action="forecast_job.cancelled",
            entity_type="forecast_job",
            entity_id=job.id,
            actor_user_id=job.created_by_id,
            payload={"progress": job.progress},
        )


def run_forecast_job(job_id: int) -> None:
    """Execute one forecast job. Safe to call twice for the same id."""

    from forecastops_forecasting import StudyConfig, StudyError, run_forecast_study
    from forecastops_forecasting.schema import DemandValidationError

    from ..config import settings

    set_job_id(job_id)
    started = time.monotonic()
    context = _job_or_none(job_id)
    if context is None:
        return

    try:
        storage_path = _version_path(job_id)
        frame = storage.read_version_frame(storage_path)
        config = StudyConfig(
            horizon_days=context["horizon_days"],
            holdout_days=context["holdout_days"],
            validation_folds=context["validation_folds"],
            seed=context["seed"],
            model_keys=tuple(context["model_keys"]),
            model_params=context["model_params"],
        )
        result = run_forecast_study(
            frame,
            config,
            progress=_ticker(job_id, started, settings.job_timeout_seconds),
        )
        _persist_results(job_id, result, started)
    except JobCancelled:
        _cancel(job_id)
        logger.info("job cancelled", extra={"context": {"job_id": job_id}})
    except JobTimeout:
        _fail(
            job_id,
            "timeout",
            "The forecast exceeded its time budget and was stopped. Try a shorter horizon or fewer series.",
        )
    except StudyError as exc:
        message = STUDY_ERROR_MESSAGES.get(exc.code, "The forecast could not be completed for this dataset.")
        _fail(job_id, exc.code, message, detail=str(exc))
    except DemandValidationError as exc:
        _fail(job_id, "invalid_dataset", "The dataset no longer satisfies the data contract.", detail=str(exc))
    except FileNotFoundError:
        _fail(job_id, "dataset_unavailable", "The stored dataset could not be read. Re-import the data.")
    except Exception:
        logger.exception("unexpected worker failure", extra={"context": {"job_id": job_id}})
        _fail(job_id, "worker_error", "The forecast failed unexpectedly. The job can be retried.")
