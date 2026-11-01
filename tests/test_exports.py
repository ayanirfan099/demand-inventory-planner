"""Export authorization, content, filename safety and audit records."""

from __future__ import annotations

import csv
import io
import json
import re

from tests.helpers import create_completed_job, selected_run_id


def test_forecast_export_is_valid_csv_with_a_safe_filename(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)

    response = owner_client.get(f"/api/v1/forecast-runs/{run_id}/exports/forecast.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    filename = re.search(r'filename="([^"]+)"', disposition).group(1)
    assert "/" not in filename and ".." not in filename
    assert response.headers["cache-control"] == "no-store"

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows
    assert {"date", "store", "item", "forecast", "model", "run_id"} <= set(rows[0])
    assert all(float(row["forecast"]) >= 0 for row in rows)


def test_metrics_export_contains_aggregate_and_series_rows(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    response = owner_client.get(f"/api/v1/forecast-runs/{run_id}/exports/metrics.csv")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    scopes = {row["scope"] for row in rows}
    assert scopes == {"aggregate", "series"}
    assert {"mae", "rmse", "wape", "mase", "bias"} == {
        row["metric"] for row in rows if row["scope"] == "aggregate"
    }


def test_report_export_is_labelled_decision_support(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    response = owner_client.get(f"/api/v1/forecast-runs/{run_id}/exports/report.json")
    assert response.status_code == 200
    payload = json.loads(response.text)
    assert "decision-support" in payload["notice"].lower()
    assert payload["metrics"]["aggregate"]["mae"] is not None
    assert payload["run"]["id"] == run_id
    assert payload["forecast_points"]
    assert payload["limitations"]

    without_points = owner_client.get(
        f"/api/v1/forecast-runs/{run_id}/exports/report.json?include_points=false"
    )
    assert "forecast_points" not in json.loads(without_points.text)


def test_exports_are_recorded_and_audited(owner_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    owner_client.get(f"/api/v1/forecast-runs/{run_id}/exports/report.json")

    listed = owner_client.get(f"/api/v1/forecast-runs/{run_id}/exports").json()["exports"]
    assert listed and listed[0]["kind"] == "report_json"

    all_exports = owner_client.get("/api/v1/exports").json()["exports"]
    assert any(row["run_id"] == run_id for row in all_exports)

    events = owner_client.get("/api/v1/audit-events?action=export").json()["events"]
    assert events


def test_viewer_can_export_but_not_read_the_audit_trail(viewer_client, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    assert viewer_client.get(f"/api/v1/forecast-runs/{run_id}/exports/forecast.csv").status_code == 200
    assert viewer_client.get("/api/v1/audit-events").status_code == 403


def test_anonymous_export_is_rejected(api, seeded_org):
    job_id = create_completed_job(seeded_org["dataset_id"])
    run_id = selected_run_id(job_id)
    api.cookies.clear()
    assert api.get(f"/api/v1/forecast-runs/{run_id}/exports/forecast.csv").status_code == 401
