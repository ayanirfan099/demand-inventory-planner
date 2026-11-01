"""Dataset ingestion: bounded upload, validation preview, import and inspection."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from forecastops_forecasting import generate_demo_demand
from forecastops_forecasting.schema import (
    DemandValidationError,
    frame_to_records,
    normalize_demand,
    read_demand_csv,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import AuthContext, get_auth, get_dataset, require_role
from ..errors import AppError, NotFoundError, PayloadTooLargeError
from ..models import ActualObservation, DatasetVersion, SeriesDefinition
from ..schemas import SeriesUpdateRequest, SyntheticImportRequest
from ..serializers import dataset_summary, version_summary
from ..serializers import series as serialize_series
from ..services import ingestion, storage
from ..services.ratelimit import enforce

router = APIRouter(prefix="/datasets", tags=["datasets"])
logger = logging.getLogger("forecastops.datasets")

MAX_PREVIEW_ROWS = 15
MAX_PREVIEW_SERIES = 60
CHUNK = 1024 * 256


class ImportFromPreviewRequest(BaseModel):
    preview_id: str = Field(min_length=32, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


async def _read_upload(file: UploadFile) -> bytes:
    """Read an upload while enforcing the byte cap (never trust Content-Length)."""

    filename = (file.filename or "").lower()
    if filename and not filename.endswith(".csv"):
        raise AppError(
            "Only .csv files are supported.",
            code="unsupported_file_type",
            details={"filename": filename[:120]},
        )
    buffer = bytearray()
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > settings.max_upload_bytes:
            raise PayloadTooLargeError(
                f"Uploads are limited to {settings.max_upload_bytes // (1024 * 1024)} MB."
            )
    return bytes(buffer)


def _preview_payload(clean: pd.DataFrame, report, preview_id: str | None) -> dict:
    quality = report.as_dict()
    series_frame = (
        clean.groupby(["store", "item"], as_index=False)
        .agg(
            days=("sales", "size"),
            total=("sales", "sum"),
            mean=("sales", "mean"),
            zero_days=("sales", lambda values: int((values == 0).sum())),
        )
        .sort_values(["store", "item"])
    )
    return {
        "preview_id": preview_id,
        "valid": True,
        "quality": quality,
        "fingerprint": storage.fingerprint(clean),
        "columns": list(clean.columns),
        "sample_rows": frame_to_records(clean.head(MAX_PREVIEW_ROWS)),
        "series_preview": [
            {
                "store": str(row.store),
                "item": str(row.item),
                "days": int(row.days),
                "total": round(float(row.total), 2),
                "mean": round(float(row.mean), 2),
                "zero_days": int(row.zero_days),
            }
            for row in series_frame.head(MAX_PREVIEW_SERIES).itertuples(index=False)
        ],
        "series_total": len(series_frame),
        "limits": {
            "max_rows": settings.max_upload_rows,
            "max_series": settings.max_series,
            "max_bytes": settings.max_upload_bytes,
            "required_columns": ["date", "store", "item", "sales"],
            "optional_columns": ["on_hand"],
        },
        "policy": {
            "duplicates": "Rows sharing store/item/date are summed into daily demand.",
            "missing_dates": "Calendar days missing from a series are filled with zero demand and counted.",
            "negative_sales": "Negative quantities are rejected; returns are not modelled in v1.",
            "dates": "Dates are normalised to calendar dates; any time component is dropped.",
        },
    }


@router.get("")
def list_datasets(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> dict:
    from ..models import Dataset

    datasets = db.scalars(select(Dataset).where(Dataset.org_id == auth.org_id).order_by(Dataset.id)).all()
    items = []
    for dataset in datasets:
        current = db.get(DatasetVersion, dataset.current_version_id) if dataset.current_version_id else None
        items.append(dataset_summary(dataset, current))
    return {"datasets": items}


@router.post("/previews", status_code=status.HTTP_201_CREATED)
async def create_preview(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_role("analyst")),
) -> dict:
    enforce(f"upload:{auth.user.id}", settings.upload_rate_limit)
    raw = await _read_upload(file)
    try:
        clean, report = read_demand_csv(raw, max_rows=settings.max_upload_rows)
    except DemandValidationError as exc:
        raise AppError(
            exc.args[0] if exc.args else "The dataset is not valid.",
            code=exc.code,
            details=exc.details or None,
        ) from exc

    if report.series_count > settings.max_series:
        raise AppError(
            f"Datasets are limited to {settings.max_series} store/item series.",
            code="too_many_series",
        )
    preview_id = storage.save_preview(storage.canonical_csv(clean), report.as_dict())
    payload = _preview_payload(clean, report, preview_id)
    payload["original_filename"] = storage.safe_filename(file.filename)
    return payload


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def import_from_preview(
    payload: ImportFromPreviewRequest,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        csv_text, _quality = storage.load_preview(payload.preview_id)
    except (FileNotFoundError, ValueError) as exc:
        raise AppError(
            "This preview expired. Upload the file again.",
            code="preview_expired",
        ) from exc

    try:
        clean, report = read_demand_csv(csv_text.encode("utf-8"), max_rows=settings.max_upload_rows)
    except DemandValidationError as exc:
        raise AppError(exc.args[0] if exc.args else "The dataset is not valid.", code=exc.code) from exc

    result = ingestion.import_demand(
        db,
        org_id=auth.org_id,
        user_id=auth.user.id,
        name=payload.name,
        description=payload.description,
        frame=clean,
        quality=report.as_dict(),
        source="upload",
    )
    storage.delete_preview(payload.preview_id)
    return {
        "dataset": dataset_summary(result.dataset, result.version),
        "version": version_summary(result.version),
        "created_new_version": result.created,
        "duplicate_of_existing": not result.created,
        "message": (
            "Imported as a new dataset version."
            if result.created
            else "An identical file was already imported; the existing version was reused."
        ),
    }


@router.post("/imports/direct", status_code=status.HTTP_201_CREATED)
async def import_direct(
    name: str = Query(min_length=1, max_length=160),
    description: str | None = Query(default=None, max_length=2000),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    """Single-step upload for automation; the UI uses preview + confirm."""

    enforce(f"upload:{auth.user.id}", settings.upload_rate_limit)
    raw = await _read_upload(file)
    try:
        clean, report = read_demand_csv(raw, max_rows=settings.max_upload_rows)
    except DemandValidationError as exc:
        raise AppError(exc.args[0] if exc.args else "The dataset is not valid.", code=exc.code) from exc
    result = ingestion.import_demand(
        db,
        org_id=auth.org_id,
        user_id=auth.user.id,
        name=name,
        description=description,
        frame=clean,
        quality=report.as_dict(),
        source="upload",
        original_filename=file.filename,
    )
    return {
        "dataset": dataset_summary(result.dataset, result.version),
        "created_new_version": result.created,
    }


@router.post("/synthetic", status_code=status.HTTP_201_CREATED)
def import_synthetic(
    payload: SyntheticImportRequest,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.demo_enabled:
        raise AppError("Synthetic data generation is disabled in this deployment.", code="demo_disabled")

    frame = generate_demo_demand(
        days=payload.days,
        seed=payload.seed,
        end_date=payload.end_date,
    )
    clean, report = normalize_demand(frame, max_rows=settings.max_upload_rows, max_series=settings.max_series)
    quality = report.as_dict()
    quality["synthetic"] = True
    quality["generator_seed"] = payload.seed
    quality["notice"] = (
        "Synthetic data for demonstration only. Metrics from this dataset are smoke results, "
        "not evidence of real-world forecasting performance."
    )
    result = ingestion.import_demand(
        db,
        org_id=auth.org_id,
        user_id=auth.user.id,
        name=payload.name,
        description="Deterministic synthetic demo demand (seeded generator).",
        frame=clean,
        quality=quality,
        source="synthetic",
    )
    return {
        "dataset": dataset_summary(result.dataset, result.version),
        "version": version_summary(result.version),
        "created_new_version": result.created,
        "notice": quality["notice"],
    }


@router.get("/{dataset_id}")
def get_dataset_detail(
    dataset_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, auth, dataset_id)
    versions = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version.desc())
    ).all()
    current = next((v for v in versions if v.id == dataset.current_version_id), versions[0] if versions else None)
    series_rows = db.scalars(
        select(SeriesDefinition)
        .where(SeriesDefinition.dataset_id == dataset.id)
        .order_by(SeriesDefinition.store, SeriesDefinition.item)
    ).all()
    return {
        "dataset": dataset_summary(dataset, current),
        "versions": [version_summary(v) for v in versions],
        "series": [serialize_series(row) for row in series_rows],
        "alerts": [],
    }


@router.get("/{dataset_id}/series")
def list_series(
    dataset_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, auth, dataset_id)
    rows = db.scalars(
        select(SeriesDefinition)
        .where(SeriesDefinition.dataset_id == dataset.id)
        .order_by(SeriesDefinition.store, SeriesDefinition.item)
    ).all()
    return {"series": [serialize_series(row) for row in rows]}


@router.patch("/{dataset_id}/series/{series_id}")
def update_series_on_hand(
    dataset_id: int,
    series_id: int,
    payload: SeriesUpdateRequest,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    from ..models import SeriesDefinition as Series
    from ..services import audit

    dataset = get_dataset(db, auth, dataset_id)
    row = db.scalar(select(Series).where(Series.id == series_id, Series.dataset_id == dataset.id))
    if row is None:
        raise NotFoundError("Series not found.")
    previous = row.on_hand
    row.on_hand = payload.on_hand
    from ..models import utcnow

    row.on_hand_updated_at = utcnow()
    db.add(row)
    audit.record(
        db,
        org_id=auth.org_id,
        action="series.on_hand_updated",
        entity_type="series_definition",
        entity_id=row.id,
        actor_user_id=auth.user.id,
        payload={"previous": previous, "new": payload.on_hand, "store": row.store, "item": row.item},
    )
    return serialize_series(row)


@router.get("/{dataset_id}/demand")
def demand_history(
    dataset_id: int,
    series_id: int | None = Query(default=None, gt=0),
    days: int = Query(default=90, ge=1, le=730),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Recent observed demand for charting actuals next to a forecast."""

    dataset = get_dataset(db, auth, dataset_id)
    version_id = dataset.current_version_id
    if version_id is None:
        raise NotFoundError("This dataset has no imported version.")
    version = db.get(DatasetVersion, version_id)
    if version is None:
        raise NotFoundError("This dataset has no imported version.")
    cutoff = version.date_max - timedelta(days=days - 1)

    query = (
        select(ActualObservation, SeriesDefinition)
        .join(SeriesDefinition, ActualObservation.series_id == SeriesDefinition.id)
        .where(
            ActualObservation.dataset_version_id == version.id,
            ActualObservation.observed_on >= cutoff,
        )
        .order_by(ActualObservation.observed_on)
    )
    if series_id is not None:
        query = query.where(ActualObservation.series_id == series_id)
    rows = db.execute(query).all()
    return {
        "series_id": series_id,
        "dataset_version_id": version.id,
        "points": [
            {
                "date": observation.observed_on.isoformat(),
                "series_id": observation.series_id,
                "store": series_row.store,
                "item": series_row.item,
                "quantity": round(observation.quantity, 4),
            }
            for observation, series_row in rows
        ],
    }


@router.get("/{dataset_id}/versions/{version_id}/download")
def download_version(
    dataset_id: int,
    version_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> Response:
    dataset = get_dataset(db, auth, dataset_id)
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == version_id, DatasetVersion.dataset_id == dataset.id
        )
    )
    if version is None:
        raise NotFoundError("Dataset version not found.")
    try:
        text = storage.Path(version.storage_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise NotFoundError("The stored file for this version is unavailable.") from exc
    filename = storage.safe_filename(f"{dataset.name}-v{version.version}.csv")
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{dataset_id}/quality")
def dataset_quality(
    dataset_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, auth, dataset_id)
    if not dataset.current_version_id:
        raise NotFoundError("This dataset has no imported version.")
    version = db.get(DatasetVersion, dataset.current_version_id)
    return {
        "version": version_summary(version),
        "as_of": date.today().isoformat(),
        "stale_after_days": settings.stale_dataset_days,
    }
