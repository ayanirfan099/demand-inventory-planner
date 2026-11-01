"""Ingestion tests: validation, limits, fingerprints, previews and storage hygiene."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from app.config import settings
from app.db import SessionLocal
from app.models import Dataset, DatasetVersion
from app.services import storage

from tests.helpers import demand_frame, frame_to_csv


def _upload(client, content: bytes, filename: str = "demand.csv"):
    return client.post(
        "/api/v1/datasets/previews",
        files={"file": (filename, content, "text/csv")},
    )


def test_preview_reports_quality_without_persisting(analyst_client, seeded_org):
    frame = demand_frame(days=90)
    response = _upload(analyst_client, frame_to_csv(frame))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["quality"]["series_count"] == 4
    assert body["preview_id"]
    assert body["policy"]["duplicates"].startswith("Rows sharing")

    with SessionLocal() as session:
        names = [row.name for row in session.query(Dataset).all()]
    assert "Uploaded test data" not in names
    assert len(names) == 2  # only the two fixture datasets


def test_import_from_preview_creates_a_version_and_audit(analyst_client, owner_client, seeded_org):
    response = _upload(analyst_client, frame_to_csv(demand_frame(days=90)))
    preview_id = response.json()["preview_id"]
    imported = analyst_client.post(
        "/api/v1/datasets/imports",
        json={"preview_id": preview_id, "name": "Uploaded dataset", "description": "unit test"},
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["created_new_version"] is True
    dataset_id = body["dataset"]["id"]

    detail = analyst_client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail.status_code == 200
    assert detail.json()["dataset"]["current_version"]["row_count"] > 0
    assert len(detail.json()["series"]) == 4

    events = owner_client.get("/api/v1/audit-events").json()["events"]
    assert any(event["action"] == "dataset.version_imported" for event in events)

    # The single-use preview is consumed.
    replay = analyst_client.post(
        "/api/v1/datasets/imports",
        json={"preview_id": preview_id, "name": "Uploaded dataset"},
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "preview_expired"


def test_identical_content_reuses_the_existing_version(analyst_client, seeded_org):
    csv_bytes = frame_to_csv(demand_frame(days=90))
    first = _upload(analyst_client, csv_bytes).json()
    second = _upload(analyst_client, csv_bytes).json()
    assert first["fingerprint"] == second["fingerprint"]

    first_import = analyst_client.post(
        "/api/v1/datasets/imports",
        json={"preview_id": first["preview_id"], "name": "Same content dataset"},
    ).json()
    second_import = analyst_client.post(
        "/api/v1/datasets/imports",
        json={"preview_id": second["preview_id"], "name": "Same content dataset"},
    ).json()

    assert first_import["created_new_version"] is True
    assert second_import["created_new_version"] is False
    assert second_import["duplicate_of_existing"] is True
    with SessionLocal() as session:
        dataset = session.query(Dataset).filter_by(name="Same content dataset").one()
        versions = session.query(DatasetVersion).filter_by(dataset_id=dataset.id).all()
    assert len(versions) == 1


def test_fingerprint_is_content_derived_and_stable(analyst_client, seeded_org):
    frame = demand_frame(days=60)
    reordered = frame.sort_values(["store", "item", "date"], ascending=False).reset_index(drop=True)
    assert storage.fingerprint(frame) == storage.fingerprint(reordered)
    changed = frame.copy()
    changed.loc[0, "sales"] = changed.loc[0, "sales"] + 1
    assert storage.fingerprint(frame) != storage.fingerprint(changed)


def test_missing_columns_are_rejected_with_a_typed_error(analyst_client, seeded_org):
    bad = b"date,store,item\n2025-01-01,s1,i1\n"
    response = _upload(analyst_client, bad)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_columns"


def test_malformed_csv_is_rejected(analyst_client, seeded_org):
    response = _upload(analyst_client, b"\xff\xfe\x00\x00garbage")
    assert response.status_code in {400, 422}
    assert response.json()["error"]["code"] in {"encoding_error", "parse_error", "empty_dataset", "missing_columns"}


def test_oversized_upload_is_rejected(analyst_client, seeded_org, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 512)
    response = _upload(analyst_client, frame_to_csv(demand_frame(days=120)))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_row_limit_is_enforced(analyst_client, seeded_org, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_rows", 50)
    response = _upload(analyst_client, frame_to_csv(demand_frame(days=90)))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "too_many_rows"


def test_non_csv_extension_is_rejected(analyst_client, seeded_org):
    response = _upload(analyst_client, b"date,store,item,sales\n", filename="payload.exe")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_negative_and_duplicate_rows_are_handled(analyst_client, seeded_org):
    frame = demand_frame(days=90)
    duplicated = frame.head(3).copy()
    duplicated["sales"] = 0
    frame = frame.copy()
    frame.loc[0, "sales"] = -5
    content = frame_to_csv(__import__("pandas").concat([frame, duplicated], ignore_index=True))
    body = _upload(analyst_client, content).json()
    assert body["quality"]["duplicate_rows_summed"] >= 2  # the rejected row never reaches aggregation
    assert body["quality"]["rejected_rows"] == 1
    assert body["quality"]["rejected_examples"][0]["reason"] == "negative_sales"


def test_preview_expires_and_is_swept(analyst_client, seeded_org):
    body = _upload(analyst_client, frame_to_csv(demand_frame(days=90))).json()
    preview_id = body["preview_id"]
    meta = Path(settings.data_dir) / "previews" / f"{preview_id}.meta"
    assert meta.exists()
    meta.write_text(str(int(time.time()) - storage.PREVIEW_TTL_SECONDS - 5), encoding="utf-8")
    removed = storage.sweep_previews()
    assert removed >= 1
    response = analyst_client.post(
        "/api/v1/datasets/imports", json={"preview_id": preview_id, "name": "Expired"}
    )
    assert response.status_code == 400


def test_preview_ids_cannot_traverse_paths(analyst_client, seeded_org):
    with pytest.raises(ValueError):
        storage.load_preview("../../etc/passwd")
    response = analyst_client.post(
        "/api/v1/datasets/imports", json={"preview_id": "a" * 32, "name": "Nope"}
    )
    assert response.status_code == 400


def test_safe_filename_strips_paths_and_extension():
    assert storage.safe_filename("../../etc/passwd.csv") == "passwd.csv"
    assert storage.safe_filename("sales report (final).csv") == "sales report _final_.csv"
    assert storage.safe_filename("script.sh") == "script.sh.csv"
    assert storage.safe_filename(None).endswith(".csv")
    assert len(storage.safe_filename("x" * 500)) <= storage.MAX_FILENAME_LENGTH


def test_download_is_tenant_scoped_and_named_safely(owner_client, other_client, seeded_org):
    url = f"/api/v1/datasets/{seeded_org['dataset_id']}/versions/{seeded_org['version_id']}/download"
    response = owner_client.get(url)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "date,store,item,sales" in response.text
    assert other_client.get(url).status_code == 404


def test_on_hand_update_is_audited(analyst_client, seeded_org):
    series = analyst_client.get(f"/api/v1/datasets/{seeded_org['dataset_id']}/series").json()["series"]
    target = series[0]
    response = analyst_client.patch(
        f"/api/v1/datasets/{seeded_org['dataset_id']}/series/{target['id']}",
        json={"on_hand": 250},
    )
    assert response.status_code == 200
    assert response.json()["on_hand"] == 250
    events = analyst_client.get("/api/v1/audit-events")
    assert events.status_code == 403  # analysts cannot read the audit log


def test_demand_history_endpoint_returns_observations(owner_client, seeded_org):
    response = owner_client.get(f"/api/v1/datasets/{seeded_org['dataset_id']}/demand?days=30")
    assert response.status_code == 200
    points = response.json()["points"]
    assert points
    assert len({point["date"] for point in points}) == 30
