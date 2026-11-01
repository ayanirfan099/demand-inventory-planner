"""Forecast run analytics: points, metrics, comparison and exports."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth, get_run, require_role
from ..errors import AppError, NotFoundError
from ..models import (
    Dataset,
    DatasetVersion,
    ForecastJob,
    ForecastPoint,
    ForecastRun,
    MetricResult,
    SeriesDefinition,
)
from ..serializers import (
    iso,
    metrics_dict,
    run_detail,
    run_summary,
)
from ..serializers import (
    point as serialize_point,
)
from ..serializers import (
    series as serialize_series,
)
from ..services import audit, exports

router = APIRouter(prefix="/forecast-runs", tags=["forecast runs"])

SORTABLE_METRICS = {"mae", "rmse", "wape", "mase", "bias"}


def _series_index(db: Session, dataset_id: int) -> dict[int, SeriesDefinition]:
    rows = db.scalars(select(SeriesDefinition).where(SeriesDefinition.dataset_id == dataset_id)).all()
    return {row.id: row for row in rows}


def _aggregate(db: Session, run_id: int) -> dict[str, float | None]:
    rows = db.scalars(
        select(MetricResult).where(MetricResult.run_id == run_id, MetricResult.scope == "aggregate")
    ).all()
    return metrics_dict(rows)


def _per_series(db: Session, run_id: int, series_index: dict[int, SeriesDefinition]) -> list[dict]:
    rows = db.scalars(
        select(MetricResult).where(MetricResult.run_id == run_id, MetricResult.scope == "series")
    ).all()
    grouped: dict[int, dict[str, float | None]] = defaultdict(dict)
    for row in rows:
        if row.series_id is None:
            continue
        grouped[row.series_id][row.metric] = None if row.value is None else round(row.value, 6)
    output = []
    for series_id, metrics in grouped.items():
        series_row = series_index.get(series_id)
        if series_row is None:
            continue
        output.append(
            {
                "series_id": series_id,
                "store": series_row.store,
                "item": series_row.item,
                "on_hand": series_row.on_hand,
                **metrics,
            }
        )
    return output


def _dataset_for_run(db: Session, run: ForecastRun) -> Dataset | None:
    version = db.get(DatasetVersion, run.dataset_version_id)
    return db.get(Dataset, version.dataset_id) if version else None


@router.get("")
def list_runs(
    dataset_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    query = (
        select(ForecastRun)
        .join(ForecastJob, ForecastRun.job_id == ForecastJob.id)
        .where(ForecastRun.org_id == auth.org_id)
    )
    if dataset_id is not None:
        query = query.where(ForecastJob.dataset_id == dataset_id)
    runs = db.scalars(query.order_by(ForecastRun.id.desc()).limit(limit)).all()
    items = []
    for run in runs:
        job = db.get(ForecastJob, run.job_id)
        items.append(
            {
                **run_summary(run),
                "metrics": _aggregate(db, run.id),
                "job_status": job.status if job else None,
            }
        )
    return {"runs": items}


@router.get("/{run_id}")
def run_detail_view(
    run_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run(db, auth, run_id)
    job = db.get(ForecastJob, run.job_id)
    if job is None:  # jobs cascade with their runs, so this is defensive only
        raise NotFoundError("The job that produced this run no longer exists.")
    dataset = _dataset_for_run(db, run)
    version = db.get(DatasetVersion, run.dataset_version_id)
    series_index = _series_index(db, dataset.id) if dataset else {}
    per_series = _per_series(db, run.id, series_index)
    weakest = sorted(
        [row for row in per_series if row.get("wape") is not None], key=lambda row: row["wape"], reverse=True
    )[:8]
    return {
        "run": run_detail(run, _aggregate(db, run.id)),
        "job": {
            "id": job.id,
            "status": job.status,
            "horizon_days": job.horizon_days,
            "holdout_days": job.holdout_days,
            "validation_folds": job.validation_folds,
            "seed": job.seed,
            "created_at": iso(job.created_at),
        },
        "dataset": {
            "id": dataset.id if dataset else None,
            "name": dataset.name if dataset else None,
            "source": dataset.source if dataset else None,
            "version": version.version if version else None,
            "fingerprint": version.fingerprint if version else None,
            "date_min": iso(version.date_min) if version else None,
            "date_max": iso(version.date_max) if version else None,
            "quality": version.quality if version else {},
        },
        "series": [serialize_series(row) for row in series_index.values()],
        "per_series_metrics": per_series,
        "weak_series": weakest,
        "selection_rule": (
            "Model chosen by lowest mean WAPE on rolling-origin folds that end before the holdout; "
            "the holdout is never used for selection."
        ),
        "notices": [
            "Holdout metrics describe this dataset only and are not a real-world benchmark.",
            "Forecasts are fixed multi-step recursive: later steps consume earlier predictions.",
        ],
    }


@router.get("/{run_id}/points")
def run_points(
    run_id: int,
    kind: str = Query(default="forecast", pattern="^(forecast|holdout)$"),
    series_id: int | None = Query(default=None, gt=0),
    store: str | None = Query(default=None, max_length=120),
    item: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=5000, ge=1, le=50000),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run(db, auth, run_id)
    dataset = _dataset_for_run(db, run)
    series_index = _series_index(db, dataset.id) if dataset else {}

    query = (
        select(ForecastPoint)
        .where(ForecastPoint.run_id == run.id, ForecastPoint.kind == kind)
        .order_by(ForecastPoint.target_date, ForecastPoint.series_id)
    )
    if series_id is not None:
        query = query.where(ForecastPoint.series_id == series_id)
    rows = db.scalars(query.limit(limit)).all()

    points = []
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        series_row = series_index.get(row.series_id)
        if series_row is None:
            continue
        if store and series_row.store != store:
            continue
        if item and series_row.item != item:
            continue
        points.append(
            {
                **serialize_point(row),
                "store": series_row.store,
                "item": series_row.item,
            }
        )
        totals[row.target_date.isoformat()] += row.forecast

    return {
        "run": {"id": run.id, "model_key": run.model_key, "label": run.label, "kind": kind},
        "points": points,
        "total_by_date": [{"date": key, "forecast_total": round(value, 4)} for key, value in sorted(totals.items())],
        "truncated": len(rows) >= limit,
    }


@router.get("/{run_id}/series-metrics")
def run_series_metrics(
    run_id: int,
    sort: str = Query(default="wape"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    if sort not in SORTABLE_METRICS:
        raise AppError(f"sort must be one of {', '.join(sorted(SORTABLE_METRICS))}.", code="invalid_sort")
    run = get_run(db, auth, run_id)
    dataset = _dataset_for_run(db, run)
    series_index = _series_index(db, dataset.id) if dataset else {}
    rows = _per_series(db, run.id, series_index)

    def sort_key(row: dict):
        value = row.get(sort)
        return (value is None, -(value or 0) if order == "desc" else (value or 0))

    rows.sort(key=sort_key)
    return {"series_metrics": rows[:limit], "sorted_by": sort, "order": order}


@router.get("/{run_id}/comparison")
def run_comparison(
    run_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run(db, auth, run_id)
    siblings = db.scalars(
        select(ForecastRun).where(ForecastRun.job_id == run.job_id).order_by(ForecastRun.id)
    ).all()
    baseline = next((row for row in siblings if row.model_key == "seasonal_naive"), None)
    baseline_metrics = _aggregate(db, baseline.id) if baseline else {}
    baseline_wape = baseline_metrics.get("wape")
    rows = []
    for sibling in siblings:
        metrics = _aggregate(db, sibling.id)
        wape = metrics.get("wape")
        rows.append(
            {
                "run_id": sibling.id,
                "model_key": sibling.model_key,
                "label": sibling.label,
                "is_selected": sibling.is_selected,
                "metrics": metrics,
                "relative_wape_vs_baseline": (
                    round(wape / baseline_wape, 4) if wape is not None and baseline_wape else None
                ),
            }
        )
    return {
        "job_id": run.job_id,
        "baseline_run_id": baseline.id if baseline else None,
        "rows": rows,
        "selection_rule": (
            "Selected by lowest mean WAPE across rolling-origin validation folds that end before the holdout."
        ),
    }


@router.get("/{run_id}/exports/forecast.csv")
def export_forecast(
    run_id: int,
    series_id: int | None = Query(default=None, gt=0),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> Response:
    run = get_run(db, auth, run_id)
    payload = exports.forecast_csv(db, run, series_id=series_id)
    exports.register_export(
        db, org_id=auth.org_id, user_id=auth.user.id, kind="forecast_csv", payload=payload, run_id=run.id
    )
    return _download(payload)


@router.get("/{run_id}/exports/metrics.csv")
def export_metrics(
    run_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> Response:
    run = get_run(db, auth, run_id)
    payload = exports.metrics_csv(db, run)
    exports.register_export(
        db, org_id=auth.org_id, user_id=auth.user.id, kind="metrics_csv", payload=payload, run_id=run.id
    )
    return _download(payload)


@router.get("/{run_id}/exports/report.json")
def export_report(
    run_id: int,
    include_points: bool = Query(default=True),
    auth: AuthContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> Response:
    run = get_run(db, auth, run_id)
    audit.record(
        db,
        org_id=auth.org_id,
        action="export.requested",
        entity_type="forecast_run",
        entity_id=run.id,
        actor_user_id=auth.user.id,
        payload={"kind": "report_json", "include_points": include_points},
    )
    payload = exports.report_json(db, run, include_points=include_points)
    exports.register_export(
        db, org_id=auth.org_id, user_id=auth.user.id, kind="report_json", payload=payload, run_id=run.id
    )
    return _download(payload)


def _download(payload: exports.ExportPayload) -> Response:
    return Response(
        content=payload.body,
        media_type=payload.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "X-Export-Id": str(payload.export_id or ""),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{run_id}/exports")
def list_exports(
    run_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    from ..models import ReportExport

    run = get_run(db, auth, run_id)
    rows = db.scalars(
        select(ReportExport)
        .where(ReportExport.run_id == run.id, ReportExport.org_id == auth.org_id)
        .order_by(ReportExport.id.desc())
        .limit(20)
    ).all()
    return {
        "exports": [
            {
                "id": row.id,
                "kind": row.kind,
                "filename": row.filename,
                "content_type": row.content_type,
                "byte_size": row.byte_size,
                "created_at": iso(row.created_at),
            }
            for row in rows
        ]
    }


@router.get("/{run_id}/residuals")
def run_residuals(
    run_id: int,
    series_id: int | None = Query(default=None, gt=0),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    run = get_run(db, auth, run_id)
    query = (
        select(ForecastPoint)
        .where(ForecastPoint.run_id == run.id, ForecastPoint.kind == "holdout")
        .order_by(ForecastPoint.target_date)
    )
    if series_id is not None:
        query = query.where(ForecastPoint.series_id == series_id)
    rows = db.scalars(query).all()
    if not rows:
        raise NotFoundError("This run has no holdout residuals.")
    dataset = _dataset_for_run(db, run)
    series_index = _series_index(db, dataset.id) if dataset else {}
    residuals: list[dict[str, Any]] = []
    by_series: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        if row.actual is None:
            continue
        error = float(row.actual) - float(row.forecast)
        by_series[row.series_id].append(error)
        series_row = series_index.get(row.series_id)
        residuals.append(
            {
                "date": row.target_date.isoformat(),
                "series_id": row.series_id,
                "store": series_row.store if series_row else None,
                "item": series_row.item if series_row else None,
                "actual": round(float(row.actual), 4),
                "forecast": round(float(row.forecast), 4),
                "error": round(error, 4),
                "abs_error": round(abs(error), 4),
            }
        )
    error_values = [float(item["error"]) for item in residuals]
    summary = {
        "mean_error": round(sum(error_values) / len(error_values), 4),
        "mean_abs_error": round(sum(abs(value) for value in error_values) / len(error_values), 4),
        "over_forecast_share": round(sum(1 for value in error_values if value < 0) / len(error_values), 4),
        "bins": _residual_histogram(error_values),
    }
    return {"residuals": residuals, "summary": summary}


def _residual_histogram(values: list[float], bins: int = 12) -> list[dict]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high == low:
        return [{"lower": round(low, 2), "upper": round(high, 2), "count": len(values)}]
    width = (high - low) / bins
    edges = [low + width * index for index in range(bins + 1)]
    counts = [0] * bins
    for value in values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1
    return [
        {"lower": round(edges[index], 2), "upper": round(edges[index + 1], 2), "count": counts[index]}
        for index in range(bins)
        if counts[index] > 0
    ]
