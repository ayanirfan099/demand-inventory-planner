"""Job dispatch.

Three modes, selected by ``FORECASTOPS_EXECUTION_MODE``:

``thread``
    A bounded in-process thread pool runs the job. Used for local development and for the
    hosted preview, where no Redis is available. Bounded so a single API process cannot be
    swamped by queued work.

``rq``
    Enqueue the job with RQ on Redis. This is the Docker Compose / production path.

``external``
    Leave the job ``queued`` in the database for a separate poller worker (``worker.poll``).

If Redis is unreachable while enqueueing, the job is marked failed with a structured reason
instead of disappearing: the API never pretends a job was scheduled when it was not.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ..config import settings
from ..models import ForecastJob, utcnow
from ..observability import set_job_id

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger("forecastops.queue")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="forecast-job")


def run_inline(job_id: int) -> None:
    from .runner import run_forecast_job

    set_job_id(job_id)
    try:
        run_forecast_job(job_id)
    except Exception:  # pragma: no cover - runner already records failures
        logger.exception("inline job dispatch failed", extra={"context": {"job_id": job_id}})


def dispatch(db: Session, job: ForecastJob) -> str:
    """Hand a queued job to the configured executor. Returns the dispatch mode used."""

    mode = settings.execution_mode

    if mode == "thread":
        _executor.submit(run_inline, job.id)
        return "thread"

    if mode == "rq":
        try:
            import redis
            from rq import Queue

            from .runner import run_forecast_job
        except ImportError:  # pragma: no cover - only when extras are missing
            _mark_dispatch_failure(
                db, job, "queue_unavailable", "Redis/RQ support is not installed in this deployment."
            )
            return "rq"
        try:
            connection = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
            connection.ping()
            Queue(settings.job_queue_name, connection=connection).enqueue(
                run_forecast_job,
                job.id,
                job_timeout=settings.job_timeout_seconds,
                description=f"forecast job {job.id}",
            )
        except Exception as exc:
            logger.warning(
                "could not enqueue job on Redis: %s", type(exc).__name__, extra={"context": {"job_id": job.id}}
            )
            _mark_dispatch_failure(
                db,
                job,
                "queue_unavailable",
                "The job queue is unavailable, so the forecast could not be started. Try again shortly.",
            )
        return "rq"

    # external: a poller worker will pick the job up from the database.
    return "external"


def _mark_dispatch_failure(db: Session, job: ForecastJob, code: str, message: str) -> None:
    job.status = "failed"
    job.failure_code = code
    job.failure_message = message
    job.finished_at = utcnow()
    db.add(job)
    db.commit()
    logger.error("job dispatch failed", extra={"context": {"job_id": job.id, "code": code}})


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
