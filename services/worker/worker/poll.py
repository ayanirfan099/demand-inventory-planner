"""Database poller worker.

Used when Redis is not available (``FORECASTOPS_EXECUTION_MODE=external``). Jobs are
claimed with a conditional UPDATE so two pollers cannot run the same job concurrently.

On start the poller also sweeps *stale claims*: a job left ``running`` by a worker that died
is marked failed (with an audit event and a single alert) instead of sitting in ``running``
forever. It is deliberately not silently re-queued — re-running work that may have produced
side effects is a decision a person makes, and the retry endpoint is one click away.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timedelta

logger = logging.getLogger("forecastops.poller")

# A worker enforces its own wall-clock budget, so anything older than budget + grace lost
# its worker rather than merely being slow.
STALE_CLAIM_GRACE_SECONDS = 60
STALE_CLAIM_MESSAGE = "The worker running this job stopped before it finished. Retry the job."

_running = True


def _stop(*_args):
    global _running
    _running = False


def claim_next_job() -> int | None:
    """Claim the oldest queued job, transitioning it to ``running`` atomically."""

    from app.db import session_scope
    from app.models import ForecastJob, utcnow
    from sqlalchemy import update
    from sqlalchemy.engine import CursorResult

    with session_scope() as session:
        candidate = session.scalar(
            ForecastJob.__table__.select()
            .with_only_columns(ForecastJob.id)
            .where(ForecastJob.status == "queued")
            .order_by(ForecastJob.id)
            .limit(1)
        )
        if candidate is None:
            return None
        result = session.execute(
            update(ForecastJob)
            .where(ForecastJob.id == candidate, ForecastJob.status == "queued")
            .values(status="running", started_at=utcnow(), stage="claimed", progress=1)
        )
        claimed = result.rowcount if isinstance(result, CursorResult) else 0
        if claimed != 1:
            return None
    return int(candidate)


def sweep_stale_claims(
    *,
    timeout_seconds: int | None = None,
    now: datetime | None = None,
) -> int:
    """Fail jobs whose worker disappeared. Returns the number of jobs transitioned.

    Each job is transitioned with a conditional UPDATE, so two pollers sweeping at the same
    time cannot both record the failure (and the audit event and alert are written once).
    """

    from app.config import settings
    from app.db import session_scope
    from app.models import ForecastJob, utcnow
    from app.services import alerts, audit
    from sqlalchemy import select, update
    from sqlalchemy.engine import CursorResult

    budget = settings.job_timeout_seconds if timeout_seconds is None else timeout_seconds
    cutoff = (now or utcnow()) - timedelta(seconds=budget + STALE_CLAIM_GRACE_SECONDS)

    swept = 0
    with session_scope() as session:
        candidate_ids = session.scalars(
            select(ForecastJob.id).where(
                ForecastJob.status == "running",
                ForecastJob.started_at.is_not(None),
                ForecastJob.started_at < cutoff,
            )
        ).all()

        for job_id in candidate_ids:
            result = session.execute(
                update(ForecastJob)
                .where(
                    ForecastJob.id == job_id,
                    ForecastJob.status == "running",
                    ForecastJob.started_at < cutoff,
                )
                .values(
                    status="failed",
                    stage="stale_claim",
                    failure_code="worker_error",
                    failure_message=STALE_CLAIM_MESSAGE,
                    finished_at=utcnow(),
                )
            )
            transitioned = result.rowcount if isinstance(result, CursorResult) else 0
            if transitioned != 1:
                continue

            job = session.get(ForecastJob, job_id, populate_existing=True)
            if job is None:  # pragma: no cover - deleted between the two statements
                continue
            audit.record(
                session,
                org_id=job.org_id,
                action="forecast_job.failed",
                entity_type="forecast_job",
                entity_id=job.id,
                actor_user_id=None,
                payload={"code": "worker_error", "stale_claim": True},
            )
            alerts.raise_job_failure(session, job, "worker_error", STALE_CLAIM_MESSAGE)
            swept += 1
            logger.warning(
                "recovered a stale job claim",
                extra={"context": {"job_id": job_id}},
            )

    return swept


def main(poll_seconds: float = 2.0) -> int:
    from app.config import settings
    from app.observability import configure_logging
    from app.services import storage
    from app.services.runner import run_forecast_job

    configure_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("poller worker started (pid=%s, mode=%s)", os.getpid(), settings.execution_mode)
    storage.sweep_previews()
    recovered = sweep_stale_claims()
    if recovered:
        logger.warning("recovered %s stale job claim(s) on startup", recovered)

    while _running:
        job_id = claim_next_job()
        if job_id is None:
            time.sleep(poll_seconds)
            continue
        logger.info("claimed job", extra={"context": {"job_id": job_id}})
        try:
            run_forecast_job(job_id)
        except Exception:  # pragma: no cover - the runner records its own failures
            logger.exception("poller job crashed", extra={"context": {"job_id": job_id}})
    logger.info("poller worker stopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
