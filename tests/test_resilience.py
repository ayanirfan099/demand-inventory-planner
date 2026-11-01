"""Dependency-failure behaviour.

The product promises graceful degradation, not a stack trace: a database outage must read as
"try again shortly" (503) and a missing queue must fail the job visibly instead of pretending
the work was scheduled. These tests exercise both without needing Postgres or Redis.
"""

from __future__ import annotations

import pytest
from app.db import SessionLocal, get_db
from app.main import app
from app.models import ForecastJob
from app.services import queue as queue_service
from sqlalchemy.exc import InterfaceError, OperationalError

from tests.helpers import create_job


def _outage(exc: BaseException):
    """Build a generator dependency that fails exactly like an unreachable database."""

    def _dependency():
        raise exc
        yield  # pragma: no cover - keeps it a generator, like get_db

    return _dependency


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("could not connect to server")),
        InterfaceError("SELECT 1", {}, Exception("connection already closed")),
    ],
)
def test_database_outage_is_a_503_without_leaking_the_driver_error(owner_client, error):
    # An authenticated session is required to reach the database at all: the session lookup
    # is itself the first query, which is why an anonymous request returns 401, not 503.
    app.dependency_overrides[get_db] = _outage(error)
    try:
        response = owner_client.get("/api/v1/datasets")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "service_unavailable"
    assert "database is unavailable" in body["message"].lower()
    # Driver messages contain hostnames and ports; they must not reach the client.
    serialised = response.text.lower()
    assert "could not connect" not in serialised
    assert "connection already closed" not in serialised


def test_the_api_recovers_once_the_database_returns(owner_client, seeded_org):
    app.dependency_overrides[get_db] = _outage(OperationalError("SELECT 1", {}, Exception("boom")))
    try:
        assert owner_client.get("/api/v1/datasets").status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert owner_client.get("/api/v1/datasets").status_code == 200


def test_rq_dispatch_enqueues_one_bounded_job(seeded_org, monkeypatch):
    import redis
    import rq
    from app.config import settings
    from app.services.runner import run_forecast_job

    class FakeConnection:
        def __init__(self) -> None:
            self.pinged = 0

        def ping(self) -> bool:
            self.pinged += 1
            return True

    created: list[RecordingQueue] = []

    class RecordingQueue:

        def __init__(self, name: str, connection=None) -> None:
            self.name = name
            self.connection = connection
            self.calls: list[tuple[object, tuple, dict]] = []
            created.append(self)

        def enqueue(self, func, *args, **kwargs):
            self.calls.append((func, args, kwargs))
            return object()

    connection = FakeConnection()
    monkeypatch.setattr(settings, "execution_mode", "rq")
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda *_args, **_kwargs: connection))
    monkeypatch.setattr(rq, "Queue", RecordingQueue)

    job_id = create_job(seeded_org["dataset_id"])
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        assert queue_service.dispatch(session, job) == "rq"

    assert connection.pinged == 1
    assert len(created) == 1
    enqueued = created[0]
    assert enqueued.name == settings.job_queue_name

    (func, args, kwargs), = enqueued.calls
    assert func is run_forecast_job
    assert args == (job_id,)
    # The queue-level timeout mirrors the runner's own wall-clock budget.
    assert kwargs["job_timeout"] == settings.job_timeout_seconds
    assert str(job_id) in kwargs["description"]

    with SessionLocal() as session:
        # Dispatch never invents a terminal state; it only hands work over.
        assert session.get(ForecastJob, job_id).status == "queued"


def test_rq_dispatch_marks_the_job_failed_when_redis_rejects_the_enqueue(seeded_org, monkeypatch):
    import redis
    import rq
    from app.config import settings

    class RefusingQueue:
        def __init__(self, name: str, connection=None) -> None:
            pass

        def enqueue(self, *_args, **_kwargs):
            raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(settings, "execution_mode", "rq")
    class PingingConnection:
        def ping(self) -> bool:
            return True

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda *_args, **_kwargs: PingingConnection()))
    monkeypatch.setattr(rq, "Queue", RefusingQueue)

    job_id = create_job(seeded_org["dataset_id"])
    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job is not None
        queue_service.dispatch(session, job)

    with SessionLocal() as session:
        job = session.get(ForecastJob, job_id)
        assert job.status == "failed"
        assert job.failure_code == "queue_unavailable"
        assert "queue is unavailable" in (job.failure_message or "").lower()
