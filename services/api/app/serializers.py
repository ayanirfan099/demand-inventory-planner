"""ORM -> JSON serialisers shared by the routers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from .models import (
    Alert,
    AuditEvent,
    Dataset,
    DatasetVersion,
    ForecastJob,
    ForecastPoint,
    ForecastRun,
    InventoryPolicy,
    MetricResult,
    Organization,
    ReorderSuggestion,
    SeriesDefinition,
)


def iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def organization(org: Organization) -> dict[str, Any]:
    return {"id": org.id, "name": org.name, "slug": org.slug}


def version_summary(version: DatasetVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "id": version.id,
        "version": version.version,
        "fingerprint": version.fingerprint,
        "fingerprint_short": version.fingerprint.split(":")[-1][:12],
        "row_count": version.row_count,
        "series_count": version.series_count,
        "date_min": iso(version.date_min),
        "date_max": iso(version.date_max),
        "byte_size": version.byte_size,
        "created_at": iso(version.created_at),
        "quality": version.quality,
    }


def dataset_summary(dataset: Dataset, current: DatasetVersion | None) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "source": dataset.source,
        "original_filename": dataset.original_filename,
        "created_at": iso(dataset.created_at),
        "current_version": version_summary(current),
    }


def series(series_row: SeriesDefinition) -> dict[str, Any]:
    return {
        "id": series_row.id,
        "store": series_row.store,
        "item": series_row.item,
        "on_hand": series_row.on_hand,
        "on_hand_updated_at": iso(series_row.on_hand_updated_at),
    }


def job(job_row: ForecastJob) -> dict[str, Any]:
    return {
        "id": job_row.id,
        "dataset_id": job_row.dataset_id,
        "dataset_version_id": job_row.dataset_version_id,
        "status": job_row.status,
        "stage": job_row.stage,
        "progress": job_row.progress,
        "horizon_days": job_row.horizon_days,
        "holdout_days": job_row.holdout_days,
        "validation_folds": job_row.validation_folds,
        "seed": job_row.seed,
        "model_keys": job_row.model_keys,
        "model_params": job_row.model_params,
        "attempt": job_row.attempt,
        "parent_job_id": job_row.parent_job_id,
        "failure_code": job_row.failure_code,
        "failure_message": job_row.failure_message,
        "cancel_requested": job_row.cancel_requested,
        "created_at": iso(job_row.created_at),
        "started_at": iso(job_row.started_at),
        "finished_at": iso(job_row.finished_at),
        "duration_seconds": (
            round((job_row.finished_at - job_row.started_at).total_seconds(), 2)
            if job_row.finished_at and job_row.started_at
            else None
        ),
    }


def run_summary(run: ForecastRun, aggregate: dict[str, float | None] | None = None) -> dict[str, Any]:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "model_key": run.model_key,
        "label": run.label,
        "is_selected": run.is_selected,
        "forecast_mode": run.forecast_mode,
        "horizon_days": run.horizon_days,
        "train_start": iso(run.train_start),
        "train_end": iso(run.train_end),
        "test_start": iso(run.test_start),
        "test_end": iso(run.test_end),
        "metrics": aggregate or {},
        "created_at": iso(run.created_at),
    }


def run_detail(run: ForecastRun, aggregate: dict[str, float | None] | None = None) -> dict[str, Any]:
    data = run_summary(run, aggregate)
    data.update(
        {
            "forecast_mode_label": run.forecast_mode_label,
            "model_config": run.model_config,
            "seed": run.seed,
            "dataset_version_id": run.dataset_version_id,
            "validation_folds": run.validation_folds,
            "limitations": run.limitations,
        }
    )
    return data


def point(row: ForecastPoint) -> dict[str, Any]:
    return {
        "date": iso(row.target_date),
        "horizon_step": row.horizon_step,
        "kind": row.kind,
        "forecast": round(row.forecast, 4),
        "actual": None if row.actual is None else round(row.actual, 4),
        "lower": None if row.lower is None else round(row.lower, 4),
        "upper": None if row.upper is None else round(row.upper, 4),
        "series_id": row.series_id,
    }


def metrics_dict(rows: Sequence[MetricResult]) -> dict[str, float | None]:
    return {row.metric: (None if row.value is None else round(row.value, 6)) for row in rows}


def policy(policy_row: InventoryPolicy) -> dict[str, Any]:
    return {
        "id": policy_row.id,
        "dataset_id": policy_row.dataset_id,
        "name": policy_row.name,
        "lead_time_days": policy_row.lead_time_days,
        "review_period_days": policy_row.review_period_days,
        "planning_window_days": policy_row.lead_time_days + policy_row.review_period_days,
        "service_level": policy_row.service_level,
        "min_order_qty": policy_row.min_order_qty,
        "pack_size": policy_row.pack_size,
        "notes": policy_row.notes,
        "is_active": policy_row.is_active,
        "created_at": iso(policy_row.created_at),
    }


def suggestion(row: ReorderSuggestion, series_row: SeriesDefinition | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "policy_id": row.policy_id,
        "run_id": row.run_id,
        "status": row.status,
        "series_id": row.series_id,
        "store": series_row.store if series_row else None,
        "item": series_row.item if series_row else None,
        "horizon_days": row.horizon_days,
        "on_hand": row.on_hand,
        "forecast_demand": row.forecast_demand,
        "safety_stock": row.safety_stock,
        "reorder_point": row.reorder_point,
        "target_level": row.target_level,
        "projected_on_hand": row.projected_on_hand,
        "shortage": row.shortage,
        "suggested_qty_raw": row.suggested_qty_raw,
        "suggested_qty": row.suggested_qty_rounded,
        "assumptions": row.assumptions,
        "created_at": iso(row.created_at),
    }


def alert(row: Alert) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "severity": row.severity,
        "title": row.title,
        "detail": row.detail,
        "status": row.status,
        "dataset_id": row.dataset_id,
        "job_id": row.job_id,
        "run_id": row.run_id,
        "series_id": row.series_id,
        "created_at": iso(row.created_at),
        "acknowledged_at": iso(row.acknowledged_at),
    }


def audit_event(row: AuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "actor_user_id": row.actor_user_id,
        "payload": row.payload,
        "request_id": row.request_id,
        "created_at": iso(row.created_at),
    }
