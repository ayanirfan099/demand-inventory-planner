"""Server-side export generation (CSV / JSON) with audit records.

Exports are produced from persisted rows only, scoped to the caller's organization by the
router before this module is called. Filenames are generated here — never taken from user
input — so a download can't escape its directory or inject headers.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ForecastJob,
    ForecastPoint,
    ForecastRun,
    MetricResult,
    ReportExport,
    SeriesDefinition,
    utcnow,
)
from . import audit


@dataclass
class ExportPayload:
    filename: str
    content_type: str
    body: bytes
    export_id: int | None = None


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _filtered_points(db: Session, run: ForecastRun, kind: str, series_id: int | None, limit: int | None):
    query = (
        select(ForecastPoint, SeriesDefinition)
        .join(SeriesDefinition, ForecastPoint.series_id == SeriesDefinition.id)
        .where(ForecastPoint.run_id == run.id, ForecastPoint.kind == kind)
        .order_by(SeriesDefinition.store, SeriesDefinition.item, ForecastPoint.target_date)
    )
    if series_id is not None:
        query = query.where(ForecastPoint.series_id == series_id)
    if limit is not None:
        query = query.limit(limit)
    return db.execute(query).all()


def forecast_csv(
    db: Session, run: ForecastRun, *, series_id: int | None = None, limit: int | None = None
) -> ExportPayload:
    rows = _filtered_points(db, run, "forecast", series_id, limit)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "date",
            "store",
            "item",
            "horizon_step",
            "forecast",
            "lower_empirical",
            "upper_empirical",
            "model",
            "run_id",
        ]
    )
    for point, series in rows:
        writer.writerow(
            [
                point.target_date.isoformat(),
                series.store,
                series.item,
                point.horizon_step,
                f"{point.forecast:.4f}",
                "" if point.lower is None else f"{point.lower:.4f}",
                "" if point.upper is None else f"{point.upper:.4f}",
                run.model_key,
                run.id,
            ]
        )
    return ExportPayload(
        filename=f"forecast-run{run.id}-{run.model_key}-{_stamp()}.csv",
        content_type="text/csv; charset=utf-8",
        body=buffer.getvalue().encode("utf-8"),
    )


def metrics_csv(db: Session, run: ForecastRun) -> ExportPayload:
    aggregate = db.scalars(
        select(MetricResult).where(MetricResult.run_id == run.id, MetricResult.scope == "aggregate")
    ).all()
    per_series = db.execute(
        select(MetricResult, SeriesDefinition)
        .join(SeriesDefinition, MetricResult.series_id == SeriesDefinition.id)
        .where(MetricResult.run_id == run.id, MetricResult.scope == "series")
        .order_by(SeriesDefinition.store, SeriesDefinition.item, MetricResult.metric)
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["scope", "store", "item", "metric", "value"])
    for row in aggregate:
        writer.writerow(["aggregate", "", "", row.metric, "" if row.value is None else round(row.value, 6)])
    for metric, series in per_series:
        writer.writerow(
            ["series", series.store, series.item, metric.metric, "" if metric.value is None else round(metric.value, 6)]
        )
    return ExportPayload(
        filename=f"metrics-run{run.id}-{run.model_key}-{_stamp()}.csv",
        content_type="text/csv; charset=utf-8",
        body=buffer.getvalue().encode("utf-8"),
    )


def report_json(db: Session, run: ForecastRun, *, include_points: bool = True) -> ExportPayload:
    job = db.get(ForecastJob, run.job_id)
    aggregate = db.scalars(
        select(MetricResult).where(MetricResult.run_id == run.id, MetricResult.scope == "aggregate")
    ).all()
    per_series = db.execute(
        select(MetricResult, SeriesDefinition)
        .join(SeriesDefinition, MetricResult.series_id == SeriesDefinition.id)
        .where(MetricResult.run_id == run.id, MetricResult.scope == "series")
        .order_by(SeriesDefinition.store, SeriesDefinition.item)
    ).all()

    series_metrics: dict[str, dict[str, float | None]] = {}
    for metric, series in per_series:
        key = f"{series.store}||{series.item}"
        series_metrics.setdefault(key, {})[metric.metric] = metric.value

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "notice": (
            "Decision-support export. Metrics describe one chronological holdout on this dataset and are not a "
            "benchmark on real retail demand."
        ),
        "run": {
            "id": run.id,
            "job_id": run.job_id,
            "model": run.model_key,
            "label": run.label,
            "forecast_mode": run.forecast_mode,
            "forecast_mode_label": run.forecast_mode_label,
            "is_selected": run.is_selected,
            "seed": run.seed,
            "horizon_days": run.horizon_days,
            "model_config": run.model_config,
            "train_start": run.train_start.isoformat() if run.train_start else None,
            "train_end": run.train_end.isoformat() if run.train_end else None,
            "test_start": run.test_start.isoformat() if run.test_start else None,
            "test_end": run.test_end.isoformat() if run.test_end else None,
            "validation_folds": run.validation_folds,
        },
        "job": {
            "id": job.id if job else None,
            "holdout_days": job.holdout_days if job else None,
            "requested_models": job.model_keys if job else None,
            "status": job.status if job else None,
        },
        "metrics": {
            "aggregate": {row.metric: row.value for row in aggregate},
            "per_series": series_metrics,
        },
        "limitations": run.limitations,
    }
    if include_points:
        points = db.scalars(
            select(ForecastPoint)
            .where(ForecastPoint.run_id == run.id, ForecastPoint.kind == "forecast")
            .order_by(ForecastPoint.series_id, ForecastPoint.target_date)
        ).all()
        series_lookup = {
            series.id: series
            for series in db.scalars(
                select(SeriesDefinition).where(SeriesDefinition.dataset_id == _dataset_id(db, run))
            )
        }
        payload["forecast_points"] = [
            {
                "date": point.target_date.isoformat(),
                "store": series_lookup[point.series_id].store if point.series_id in series_lookup else None,
                "item": series_lookup[point.series_id].item if point.series_id in series_lookup else None,
                "horizon_step": point.horizon_step,
                "forecast": point.forecast,
                "lower_empirical": point.lower,
                "upper_empirical": point.upper,
            }
            for point in points
        ]
    return ExportPayload(
        filename=f"report-run{run.id}-{run.model_key}-{_stamp()}.json",
        content_type="application/json",
        body=json.dumps(payload, indent=2, default=str).encode("utf-8"),
    )


def _dataset_id(db: Session, run: ForecastRun) -> int:
    from ..models import DatasetVersion

    version = db.get(DatasetVersion, run.dataset_version_id)
    return version.dataset_id if version else -1


def register_export(
    db: Session,
    *,
    org_id: int,
    user_id: int | None,
    kind: str,
    payload: ExportPayload,
    run_id: int | None = None,
    dataset_version_id: int | None = None,
) -> ExportPayload:
    record = ReportExport(
        org_id=org_id,
        kind=kind,
        run_id=run_id,
        dataset_version_id=dataset_version_id,
        filename=payload.filename,
        content_type=payload.content_type,
        byte_size=len(payload.body),
        status="ready",
        created_by_id=user_id,
        created_at=utcnow(),
    )
    db.add(record)
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        action="export.created",
        entity_type="report_export",
        entity_id=record.id,
        actor_user_id=user_id,
        payload={"kind": kind, "run_id": run_id, "filename": payload.filename, "bytes": len(payload.body)},
    )
    payload.export_id = record.id
    return payload
