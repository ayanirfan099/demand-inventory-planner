"""Database poller worker.

Used when Redis is not available (``FORECASTOPS_EXECUTION_MODE=external``). Jobs are
claimed with a conditional UPDATE so two pollers cannot run the same job concurrently.
"""

from __future__ import annotations

import logging
import os
import signal
import time

logger = logging.getLogger("forecastops.poller")

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
