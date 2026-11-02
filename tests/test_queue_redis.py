"""Live Redis/RQ round-trip.

This is the one test that needs a real broker. It is skipped unless a Redis server answers, so
a machine without Redis reports "skipped" rather than pretending the queue path is verified.
CI runs it against a Redis service container; see `.github/workflows/ci.yml`.

What it proves that the recording-queue tests cannot:
  1. the job function survives RQ's serialisation (importable by path),
  2. a worker actually dequeues it,
  3. the run lands in the database through the worker, not through the API process.
"""

from __future__ import annotations

import os

import pytest
import redis as redis_client
from app.db import SessionLocal
from app.models import ForecastJob

from tests.helpers import create_job, run_ids

REDIS_URL = os.environ.get("FORECASTOPS_REDIS_URL", "redis://127.0.0.1:6379/0")


def _connect():
    try:
        connection = redis_client.Redis.from_url(
            REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        connection.ping()
        return connection
    except Exception:  # any failure means "no broker here"
        return None


_connection = _connect()

pytestmark = pytest.mark.skipif(
    _connection is None,
    reason=f"no Redis broker at {REDIS_URL}",
)


def test_a_forecast_job_round_trips_through_redis(seeded_org, monkeypatch):
    from app.config import settings
    from app.services import queue as queue_service
    from rq import Queue, Worker

    monkeypatch.setattr(settings, "execution_mode", "rq")
    queue = Queue(settings.job_queue_name, connection=_connection)
    queue.empty()

    job_id = create_job(seeded_org["dataset_id"], validation_folds=0)
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        assert queue_service.dispatch(session, job) == "rq"

    # The job is now a serialised payload in Redis; nothing has executed it yet.
    assert queue.count == 1
    with SessionLocal() as session:
        assert session.get(ForecastJob, job_id).status == "queued"

    Worker([queue], connection=_connection).work(burst=True)

    assert queue.count == 0
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job.status == "succeeded", job.failure_message
        assert job.stage in {"done", "succeeded", None} or job.finished_at is not None

    # The selected run and its points were written by the worker.
    assert run_ids(job_id)


def test_the_queue_survives_an_unreachable_worker_and_keeps_the_payload(seeded_org, monkeypatch):
    """A job that is enqueued but never worked stays queued — and is recoverable by a poller."""

    from app.config import settings
    from app.services import queue as queue_service
    from rq import Queue

    monkeypatch.setattr(settings, "execution_mode", "rq")
    queue = Queue(settings.job_queue_name, connection=_connection)
    queue.empty()

    job_id = create_job(seeded_org["dataset_id"], validation_folds=0)
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        queue_service.dispatch(session, job)

    with SessionLocal() as session:
        assert session.get(ForecastJob, job_id).status == "queued"

    # A restarted worker can still see the payload; it is not lost with a process.
    payloads = queue.get_job_ids()
    assert len(payloads) == 1
    queue.empty()
