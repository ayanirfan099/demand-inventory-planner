"""Alerting rules.

Alerts are *derived* and idempotent: each rule writes at most one row per dedupe key, so
listing alerts repeatedly does not spam the table. Four rules are implemented:

* ``low_projected_stock`` — a generated reorder suggestion leaves projected stock below
  its safety stock within the planning window.
* ``high_forecast_error`` — the selected run's holdout WAPE exceeds the configured
  threshold (a signal to investigate, not a quality certificate).
* ``stale_dataset`` — the dataset has not received new demand within the configured window.
* ``failed_job`` — a forecast job failed and needs attention.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, Dataset, DatasetVersion, ForecastJob, ForecastRun, utcnow


def _upsert(
    db: Session,
    *,
    org_id: int,
    dedupe_key: str,
    kind: str,
    severity: str,
    title: str,
    detail: str,
    dataset_id: int | None = None,
    job_id: int | None = None,
    run_id: int | None = None,
    series_id: int | None = None,
) -> Alert:
    existing = db.scalar(select(Alert).where(Alert.org_id == org_id, Alert.dedupe_key == dedupe_key))
    if existing is not None:
        if existing.status == "open" and existing.detail != detail:
            existing.detail = detail
            db.add(existing)
        return existing
    alert = Alert(
        org_id=org_id,
        dedupe_key=dedupe_key[:160],
        kind=kind,
        severity=severity,
        title=title[:200],
        detail=detail,
        dataset_id=dataset_id,
        job_id=job_id,
        run_id=run_id,
        series_id=series_id,
        status="open",
        created_at=utcnow(),
    )
    db.add(alert)
    return alert


def _selected_aggregate(db: Session, run: ForecastRun) -> dict[str, float | None]:
    from ..models import MetricResult

    rows = db.scalars(
        select(MetricResult).where(MetricResult.run_id == run.id, MetricResult.scope == "aggregate")
    ).all()
    return {row.metric: row.value for row in rows}


def check_high_error(db: Session, org_id: int, run: ForecastRun | None) -> Alert | None:
    if run is None:
        return None
    metrics = _selected_aggregate(db, run)
    wape = metrics.get("wape")
    if wape is None or wape <= settings.high_error_wape_threshold:
        return None
    return _upsert(
        db,
        org_id=org_id,
        dedupe_key=f"high_error:{run.id}",
        kind="high_forecast_error",
        severity="warning",
        title=f"Holdout WAPE is {wape:.0%} for {run.label}",
        detail=(
            f"The selected model's holdout WAPE is {wape:.1%}, above the {settings.high_error_wape_threshold:.0%} "
            "review threshold. Check the weak-series table before using these forecasts for planning."
        ),
        dataset_id=None,
        run_id=run.id,
    )


def raise_job_failure(db: Session, job: ForecastJob, code: str, message: str) -> Alert:
    return _upsert(
        db,
        org_id=job.org_id,
        dedupe_key=f"failed_job:{job.id}:{job.attempt}",
        kind="failed_job",
        severity="critical",
        title=f"Forecast job #{job.id} failed",
        detail=f"{message} (code: {code}).",
        dataset_id=job.dataset_id,
        job_id=job.id,
    )


def check_stale_dataset(db: Session, org_id: int, dataset: Dataset) -> Alert | None:
    if not dataset.current_version_id:
        return None
    version = db.get(DatasetVersion, dataset.current_version_id)
    if version is None:
        return None
    age_days = (utcnow().date() - version.date_max).days
    if age_days < settings.stale_dataset_days:
        return None
    return _upsert(
        db,
        org_id=org_id,
        dedupe_key=f"stale_dataset:{dataset.id}:{version.date_max.isoformat()}",
        kind="stale_dataset",
        severity="info",
        title=f"{dataset.name} is {age_days} days out of date",
        detail=(
            f"The latest demand in this dataset ends on {version.date_max.isoformat()} "
            f"({age_days} days before today). Forecasts will roll forward from that date."
        ),
        dataset_id=dataset.id,
    )


def raise_low_stock(
    db: Session,
    *,
    org_id: int,
    policy_id: int,
    series_id: int,
    store: str,
    item: str,
    projected_on_hand: float,
    safety_stock: float,
    suggested_qty: int,
) -> Alert | None:
    if suggested_qty <= 0:
        return None
    return _upsert(
        db,
        org_id=org_id,
        dedupe_key=f"low_stock:{policy_id}:{series_id}",
        kind="low_projected_stock",
        severity="warning",
        title=f"Projected stock below safety level: {item} @ {store}",
        detail=(
            f"Projected on-hand of {projected_on_hand:.1f} units is below the safety stock of "
            f"{safety_stock:.1f}. The policy suggests ordering {suggested_qty} units (decision support only)."
        ),
        series_id=series_id,
    )


def refresh_for_job(db: Session, job: ForecastJob) -> None:
    """Post-job rules: stale dataset plus high error on the selected run."""

    dataset = db.get(Dataset, job.dataset_id)
    if dataset is not None:
        check_stale_dataset(db, job.org_id, dataset)
    selected = db.scalar(
        select(ForecastRun).where(ForecastRun.job_id == job.id, ForecastRun.is_selected.is_(True))
    )
    check_high_error(db, job.org_id, selected)


def refresh_org(db: Session, org_id: int) -> list[Alert]:
    """Evaluate the read-time rules for an organization (idempotent)."""

    datasets = db.scalars(select(Dataset).where(Dataset.org_id == org_id)).all()
    for dataset in datasets:
        check_stale_dataset(db, org_id, dataset)

    cutoff = utcnow() - timedelta(hours=24)
    recent_failures = db.scalars(
        select(ForecastJob).where(
            ForecastJob.org_id == org_id,
            ForecastJob.status == "failed",
            ForecastJob.finished_at.is_not(None),
            ForecastJob.finished_at >= cutoff,
        )
    ).all()
    for job in recent_failures:
        raise_job_failure(
            db,
            job,
            job.failure_code or "worker_error",
            job.failure_message or "The forecast job failed.",
        )

    latest_run = db.scalar(
        select(ForecastRun)
        .join(ForecastJob, ForecastRun.job_id == ForecastJob.id)
        .where(ForecastRun.org_id == org_id, ForecastRun.is_selected.is_(True))
        .order_by(ForecastRun.id.desc())
    )
    check_high_error(db, org_id, latest_run)
    db.flush()
    return list(db.scalars(select(Alert).where(Alert.org_id == org_id, Alert.status == "open")))
