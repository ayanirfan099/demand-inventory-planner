"""RQ worker entry point.

Run with ``python -m worker.main``. The API enqueues ``app.services.runner.run_forecast_job``
on the configured Redis queue; this process executes it.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("forecastops.worker")


def main() -> int:
    try:
        import redis
        from rq import Queue, Worker
    except ImportError:  # pragma: no cover - only without the queue extras
        print("redis and rq are required for the queue worker: pip install 'forecastops-worker'", file=sys.stderr)
        return 2

    from app.config import settings
    from app.observability import configure_logging

    configure_logging(settings.log_level)
    connection = redis.Redis.from_url(settings.redis_url)
    queue = Queue(settings.job_queue_name, connection=connection)
    worker = Worker([queue], connection=connection, name=f"forecastops-{os.getpid()}")
    logger.info(
        "worker listening on %s (queue=%s)", settings.job_queue_name, settings.redis_url.split("@")[-1]
    )
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
