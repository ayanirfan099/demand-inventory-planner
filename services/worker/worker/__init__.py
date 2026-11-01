"""ForecastOps worker entry points.

Two runners share one implementation (``app.services.runner``):

* :mod:`worker.main` — RQ worker consuming the Redis queue (Docker Compose default).
* :mod:`worker.poll` — database poller for environments without Redis.
"""
