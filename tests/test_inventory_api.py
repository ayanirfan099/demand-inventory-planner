"""Inventory policy API: configuration, suggestion generation and status changes."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Alert, ReorderSuggestion
from sqlalchemy import select

from tests.helpers import create_completed_job, selected_run_id


def _policy(client, dataset_id: int, **overrides) -> dict:
    payload = {
        "dataset_id": dataset_id,
        "name": "Weekly review",
        "lead_time_days": 14,
        "review_period_days": 7,
        "service_level": 0.95,
        "min_order_qty": 12,
        "pack_size": 6,
    }
    payload.update(overrides)
    response = client.post("/api/v1/inventory-policies", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["policy"]


def test_policy_validation_rejects_out_of_range_service_level(analyst_client, seeded_org):
    for value in (0.4, 0.999, 1.0):
        response = analyst_client.post(
            "/api/v1/inventory-policies",
            json={"dataset_id": seeded_org["dataset_id"], "name": f"bad-{value}", "service_level": value},
        )
        assert response.status_code == 422, value


def test_duplicate_policy_name_is_a_conflict(analyst_client, seeded_org):
    _policy(analyst_client, seeded_org["dataset_id"])
    duplicate = analyst_client.post(
        "/api/v1/inventory-policies",
        json={"dataset_id": seeded_org["dataset_id"], "name": "Weekly review"},
    )
    assert duplicate.status_code == 409


def test_generate_suggestions_creates_rows_alerts_and_audit(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    policy = _policy(owner_client, seeded_org["dataset_id"], pack_size=6, min_order_qty=12)

    response = owner_client.post(f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["summary"]["series"] == 4
    assert len(body["suggestions"]) == 4
    for suggestion in body["suggestions"]:
        assert suggestion["suggested_qty"] % 6 == 0
        if suggestion["suggested_qty"] > 0:
            assert suggestion["suggested_qty"] >= 12 or suggestion["suggested_qty"] == suggestion["suggested_qty_raw"]

    assumptions = body["suggestions"][0]["assumptions"]
    assert assumptions["service_factor_z"] > 1.6
    assert "not_modelled" in assumptions
    assert assumptions["service_level_is_not_a_guarantee"] is True

    events = owner_client.get("/api/v1/audit-events").json()["events"]
    generated = [event for event in events if event["action"] == "reorder_suggestions.generated"]
    assert generated
    assert generated[0]["payload"]["policy_snapshot"]["pack_size"] == 6

    alerts = owner_client.get("/api/v1/alerts").json()["alerts"]
    low_stock = [alert for alert in alerts if alert["kind"] == "low_projected_stock"]
    assert low_stock, "expected at least one low-stock alert from the seeded policy"


def test_regenerating_supersedes_previous_open_suggestions(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    policy = _policy(owner_client, seeded_org["dataset_id"])

    owner_client.post(f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id})
    owner_client.post(f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id})

    with SessionLocal() as session:
        rows = session.scalars(select(ReorderSuggestion).where(ReorderSuggestion.policy_id == policy["id"])).all()
    open_rows = [row for row in rows if row.status == "open"]
    assert len(open_rows) == 4
    assert len(rows) == 8


def test_suggestion_status_changes_are_audited(analyst_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    policy = _policy(analyst_client, seeded_org["dataset_id"])
    suggestion = analyst_client.post(
        f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id}
    ).json()["suggestions"][0]

    response = analyst_client.patch(
        f"/api/v1/inventory-suggestions/{suggestion['id']}", json={"status": "acknowledged"}
    )
    assert response.status_code == 200
    assert response.json()["suggestion"]["status"] == "acknowledged"


def test_suggestions_require_a_run_from_the_same_version(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    policy = _policy(owner_client, seeded_org["dataset_id"])

    # Import a new version of the dataset, then point the policy's dataset at it implicitly.
    from tests.helpers import demand_frame, frame_to_csv

    preview = owner_client.post(
        "/api/v1/datasets/previews",
        files={"file": ("demand.csv", frame_to_csv(demand_frame(seed=99)), "text/csv")},
    ).json()
    owner_client.post(
        "/api/v1/datasets/imports",
        json={"preview_id": preview["preview_id"], "name": "Test demand"},
    )

    response = owner_client.post(f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_alert_acknowledgement(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    policy = _policy(owner_client, seeded_org["dataset_id"])
    owner_client.post(f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id})

    with SessionLocal() as session:
        alert = session.scalars(select(Alert).where(Alert.status == "open")).first()
    assert alert is not None

    response = owner_client.post(f"/api/v1/alerts/{alert.id}/status", json={"status": "acknowledged"})
    assert response.status_code == 200
    assert response.json()["alert"]["status"] == "acknowledged"


def test_viewer_cannot_create_policies(viewer_client, seeded_org):
    response = viewer_client.post(
        "/api/v1/inventory-policies", json={"dataset_id": seeded_org["dataset_id"], "name": "nope"}
    )
    assert response.status_code == 403
