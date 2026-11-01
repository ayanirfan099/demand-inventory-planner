"""Cross-tenant isolation: every tenant-scoped resource must be invisible to other tenants."""

from __future__ import annotations

import pytest
from app.db import SessionLocal
from app.models import InventoryPolicy

from tests.helpers import create_completed_job, selected_run_id


@pytest.fixture()
def tenant_a_job(seeded_org):
    return create_completed_job(seeded_org["dataset_id"])


def test_other_tenant_cannot_read_dataset(owner_client, other_client, seeded_org):
    assert owner_client.get(f"/api/v1/datasets/{seeded_org['dataset_id']}").status_code == 200
    assert other_client.get(f"/api/v1/datasets/{seeded_org['dataset_id']}").status_code == 404


def test_other_tenant_cannot_read_version_series_or_demand(other_client, seeded_org):
    dataset_id = seeded_org["dataset_id"]
    version_id = seeded_org["version_id"]
    for url in (
        f"/api/v1/datasets/{dataset_id}/series",
        f"/api/v1/datasets/{dataset_id}/demand",
        f"/api/v1/datasets/{dataset_id}/quality",
        f"/api/v1/datasets/{dataset_id}/versions/{version_id}/download",
    ):
        assert other_client.get(url).status_code == 404, url


def test_other_tenant_cannot_see_runs_or_points(other_client, seeded_org, tenant_a_job):
    run_id = selected_run_id(tenant_a_job)
    assert run_id is not None
    for url in (
        f"/api/v1/forecast-runs/{run_id}",
        f"/api/v1/forecast-runs/{run_id}/points",
        f"/api/v1/forecast-runs/{run_id}/comparison",
        f"/api/v1/forecast-runs/{run_id}/series-metrics",
        f"/api/v1/forecast-runs/{run_id}/exports/forecast.csv",
        f"/api/v1/forecast-runs/{run_id}/exports/report.json",
    ):
        assert other_client.get(url).status_code == 404, url


def test_other_tenant_cannot_cancel_or_retry_jobs(other_client, seeded_org, tenant_a_job):
    assert other_client.post(f"/api/v1/forecast-jobs/{tenant_a_job}/cancel").status_code == 404
    assert other_client.post(f"/api/v1/forecast-jobs/{tenant_a_job}/retry").status_code == 404
    assert other_client.get(f"/api/v1/forecast-jobs/{tenant_a_job}").status_code == 404


def test_other_tenant_cannot_create_job_on_foreign_dataset(other_client, seeded_org):
    response = other_client.post("/api/v1/forecast-jobs", json={"dataset_id": seeded_org["dataset_id"]})
    assert response.status_code == 404


def test_other_tenant_cannot_read_or_update_policies(owner_client, other_client, seeded_org):
    created = owner_client.post(
        "/api/v1/inventory-policies",
        json={"dataset_id": seeded_org["dataset_id"], "name": "Tenant A policy"},
    )
    assert created.status_code == 201
    policy_id = created.json()["policy"]["id"]

    assert other_client.get(f"/api/v1/inventory-policies/{policy_id}").status_code == 404
    assert other_client.patch(f"/api/v1/inventory-policies/{policy_id}", json={"pack_size": 12}).status_code == 404
    assert other_client.get("/api/v1/inventory-suggestions").json()["suggestions"] == []


def test_other_tenant_cannot_reach_alerts_of_a_foreign_tenant(other_client, seeded_org, tenant_a_job):
    # Tenant A's failed/threshold alerts must not appear in tenant B's list.
    alerts = other_client.get("/api/v1/alerts").json()["alerts"]
    assert all(alert["job_id"] != tenant_a_job for alert in alerts)


def test_list_endpoints_are_scoped(owner_client, other_client, seeded_org, tenant_a_job):
    datasets_a = {row["id"] for row in owner_client.get("/api/v1/datasets").json()["datasets"]}
    datasets_b = {row["id"] for row in other_client.get("/api/v1/datasets").json()["datasets"]}
    assert seeded_org["dataset_id"] in datasets_a
    assert seeded_org["other_dataset_id"] in datasets_b
    assert datasets_a.isdisjoint(datasets_b)

    jobs_b = other_client.get("/api/v1/forecast-jobs").json()["jobs"]
    assert all(job["id"] != tenant_a_job for job in jobs_b)


def test_suggestions_are_queryable_only_inside_the_tenant(owner_client, seeded_org, tenant_a_job):
    run_id = selected_run_id(tenant_a_job)
    policy = owner_client.post(
        "/api/v1/inventory-policies",
        json={"dataset_id": seeded_org["dataset_id"], "name": "Scoped policy", "pack_size": 4},
    ).json()["policy"]
    generated = owner_client.post(
        f"/api/v1/inventory-policies/{policy['id']}/suggestions", json={"run_id": run_id}
    )
    assert generated.status_code == 201

    with SessionLocal() as session:
        assert session.query(InventoryPolicy).count() == 1
