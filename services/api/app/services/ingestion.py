"""Dataset import: fingerprinting, versioning and persistence.

Import is idempotent at the content level: re-uploading an identical file returns the
existing version instead of creating a duplicate, and the response says so explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..errors import ConflictError
from ..models import (
    ActualObservation,
    Dataset,
    DatasetVersion,
    SeriesDefinition,
    utcnow,
)
from . import audit, storage


@dataclass
class ImportResult:
    dataset: Dataset
    version: DatasetVersion
    created: bool
    quality: dict


def _next_version(db: Session, dataset_id: int) -> int:
    current = db.scalar(select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == dataset_id))
    return int(current or 0) + 1


def _sync_series(db: Session, *, org_id: int, dataset: Dataset, frame: pd.DataFrame) -> dict[str, int]:
    """Create missing series and refresh on-hand snapshots; returns store||item -> id."""

    existing = {
        f"{row.store}||{row.item}": row
        for row in db.scalars(select(SeriesDefinition).where(SeriesDefinition.dataset_id == dataset.id))
    }
    latest = frame.sort_values("date").groupby(["store", "item"], as_index=False).last()
    for row in latest.itertuples(index=False):
        key = f"{row.store}||{row.item}"
        series = existing.get(key)
        if series is None:
            series = SeriesDefinition(org_id=org_id, dataset_id=dataset.id, store=str(row.store), item=str(row.item))
            db.add(series)
            existing[key] = series
        if hasattr(row, "on_hand") and pd.notna(getattr(row, "on_hand", None)):
            series.on_hand = round(float(row.on_hand))
            series.on_hand_updated_at = utcnow()
    db.flush()
    return {f"{series.store}||{series.item}": series.id for series in existing.values()}


def _store_actuals(
    db: Session,
    *,
    org_id: int,
    version: DatasetVersion,
    frame: pd.DataFrame,
    series_ids: dict[str, int],
) -> int:
    db.execute(delete(ActualObservation).where(ActualObservation.dataset_version_id == version.id))
    records = []
    for row in frame.itertuples(index=False):
        key = f"{row.store}||{row.item}"
        series_id = series_ids.get(key)
        if series_id is None:
            continue
        observed: date = pd.Timestamp(row.date).date()
        records.append(
            {
                "org_id": org_id,
                "dataset_version_id": version.id,
                "series_id": series_id,
                "observed_on": observed,
                "quantity": float(row.sales),
            }
        )
    for start in range(0, len(records), 5000):
        db.execute(insert(ActualObservation), records[start : start + 5000])
    return len(records)


def import_demand(
    db: Session,
    *,
    org_id: int,
    user_id: int | None,
    name: str,
    description: str | None,
    frame: pd.DataFrame,
    quality: dict,
    source: str,
    original_filename: str | None = None,
    dataset_id: int | None = None,
) -> ImportResult:
    """Persist a validated demand frame as a new dataset version."""

    content_fingerprint = storage.fingerprint(frame)
    clean_name = name.strip()[:160]
    if not clean_name:
        raise ConflictError("A dataset name is required.", code="invalid_name")

    dataset = None
    if dataset_id is not None:
        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.org_id == org_id))
        if dataset is None:
            raise ConflictError("Dataset not found for this organization.", code="not_found")
    else:
        dataset = db.scalar(select(Dataset).where(Dataset.org_id == org_id, Dataset.name == clean_name))
        if dataset is None:
            dataset = Dataset(
                org_id=org_id,
                name=clean_name,
                description=(description or "").strip()[:2000] or None,
                source=source,
                original_filename=storage.safe_filename(original_filename) if original_filename else None,
                created_by_id=user_id,
            )
            db.add(dataset)
            db.flush()

    duplicate = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.fingerprint == content_fingerprint,
        )
    )
    if duplicate is not None:
        return ImportResult(dataset=dataset, version=duplicate, created=False, quality=dict(duplicate.quality or {}))

    text = storage.canonical_csv(frame)
    version_number = _next_version(db, dataset.id)
    path = storage.version_path(org_id, dataset.id, version_number, content_fingerprint)
    byte_size = storage.write_version_file(path, text)

    version = DatasetVersion(
        org_id=org_id,
        dataset_id=dataset.id,
        version=version_number,
        fingerprint=content_fingerprint,
        row_count=int(quality.get("row_count_out") or len(frame)),
        series_count=int(quality.get("series_count") or frame[["store", "item"]].drop_duplicates().shape[0]),
        date_min=pd.Timestamp(str(quality.get("date_min") or frame["date"].min())).date(),
        date_max=pd.Timestamp(str(quality.get("date_max") or frame["date"].max())).date(),
        storage_path=str(path),
        byte_size=byte_size,
        quality=quality,
        created_by_id=user_id,
    )
    db.add(version)
    db.flush()

    series_ids = _sync_series(db, org_id=org_id, dataset=dataset, frame=frame)
    observation_count = _store_actuals(
        db, org_id=org_id, version=version, frame=frame, series_ids=series_ids
    )

    dataset.current_version_id = version.id
    if description:
        dataset.description = description.strip()[:2000]
    if original_filename:
        dataset.original_filename = storage.safe_filename(original_filename)

    audit.record(
        db,
        org_id=org_id,
        action="dataset.version_imported",
        entity_type="dataset_version",
        entity_id=version.id,
        actor_user_id=user_id,
        payload={
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "version": version.version,
            "fingerprint": content_fingerprint,
            "rows": version.row_count,
            "series": version.series_count,
            "observations": observation_count,
            "source": source,
            "original_filename": dataset.original_filename,
            "warnings": len(quality.get("warnings") or []),
        },
    )
    return ImportResult(dataset=dataset, version=version, created=True, quality=quality)
