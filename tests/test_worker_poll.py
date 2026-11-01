"""Worker claim semantics.

The RQ path needs Redis; the database poller does not, so its two guarantees are tested
here: a job is claimed exactly once, and a claim abandoned by a dead worker is recovered
into a terminal state with an audit trail rather than blocking the queue forever.
"""

from __future__ import annotations

from datetime import timedelta

from app.db import SessionLocal
from app.models import Alert, AuditEvent, ForecastJob, utcnow
from sqlalchemy import select
from worker.poll import claim_next_job, sweep_stale_claims

from tests.helpers import create_job


def _job(job_id: int) -> ForecastJob:
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        return job


def test_claim_transitions_a_queued_job_and_never_hands_it_out_twice(seeded_org):
    job_id = create_job(seeded_org["dataset_id"])

    assert claim_next_job() == job_id
    assert claim_next_job() is None

    job = _job(job_id)
    assert job.status == "running"
    assert job.stage == "claimed"
    assert job.started_at is not None


def test_claim_ignores_jobs_that_already_finished(seeded_org):
    job_id = create_job(seeded_org["dataset_id"])
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        job.status = "succeeded"
        session.add(job)
        session.commit()

    assert claim_next_job() is None
    assert _job(job_id).status == "succeeded"


def test_empty_queue_returns_none(seeded_org):
    assert claim_next_job() is None


def test_a_fresh_claim_is_not_swept(seeded_org):
    job_id = create_job(seeded_org["dataset_id"])
    assert claim_next_job() == job_id

    assert sweep_stale_claims(timeout_seconds=300) == 0
    assert _job(job_id).status == "running"


def test_an_abandoned_claim_is_failed_with_an_audit_event_and_one_alert(seeded_org):
    job_id = create_job(seeded_org["dataset_id"])
    assert claim_next_job() == job_id

    # Simulate a worker that died well past its budget.
    stale_start = utcnow() - timedelta(seconds=3600)
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        job.started_at = stale_start
        session.add(job)
        session.commit()

    assert sweep_stale_claims(timeout_seconds=300) == 1

    job = _job(job_id)
    assert job.status == "failed"
    assert job.failure_code == "worker_error"
    assert job.stage == "stale_claim"
    assert job.finished_at is not None

    with SessionLocal() as session:
        alerts = session.scalars(select(Alert).where(Alert.job_id == job_id)).all()
        assert [alert.kind for alert in alerts] == ["failed_job"]
        assert alerts[0].dedupe_key == f"failed_job:{job_id}:{job.attempt}"

        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "forecast_job",
                AuditEvent.entity_id == job_id,
                AuditEvent.action == "forecast_job.failed",
            )
        ).all()
        assert len(audits) == 1


def test_sweeping_twice_records_the_failure_once(seeded_org):
    job_id = create_job(seeded_org["dataset_id"])
    assert claim_next_job() == job_id
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        job.started_at = utcnow() - timedelta(seconds=3600)
        session.add(job)
        session.commit()

    assert sweep_stale_claims(timeout_seconds=300) == 1
    assert sweep_stale_claims(timeout_seconds=300) == 0

    with SessionLocal() as session:
        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == job_id,
                AuditEvent.action == "forecast_job.failed",
            )
        ).all()
        assert len(audits) == 1
