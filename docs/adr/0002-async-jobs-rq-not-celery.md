# 0002 — RQ on Redis for async jobs, with a DB-poller fallback

- **Status:** accepted
- **Date:** 2026-10-30

## Context

A forecast run is CPU-bound, can take longer than a request, and must survive a browser
navigation. It needs: bounded runtime, retryable failure, visible status, and no work lost
when the broker is down. The stack choice was Redis + Celery **or** Redis + RQ.

## Decision

Use **RQ** (`services/worker/worker/main.py`), with three execution modes selected by
`FORECASTOPS_EXECUTION_MODE`:

| Mode | Transport |
| --- | --- |
| `thread` | bounded `ThreadPoolExecutor` in the API process |
| `rq` | `Queue.enqueue(run_forecast_job, job_id, job_timeout=…)` |
| `external` | job stays `queued`; `worker.poll` claims it with a conditional UPDATE |

Job state lives in **our** database (`forecast_jobs`), not in the broker. The broker is only
a wake-up signal; a lost message cannot lose a job's state, and the DB poller can always
recover work.

### Why RQ and not Celery

| Criterion | RQ | Celery |
| --- | --- | --- |
| Concepts needed here | queue + worker + job | broker, backend, tasks, result backend, routes |
| Defaults | one queue, small API, easy to read | many features we would not use |
| Result storage | we already store results in Postgres | would add a second result store |
| Failure visibility | job registry + our own status column | more knobs, more ways to misconfigure |
| Crash recovery | one conditional UPDATE in the poller, tested | worker-lost handling is configuration |
| Fit for a single job type | excellent | acceptable but heavier |

There is exactly one kind of asynchronous task. Celery's routing, chords, chaining and
beat scheduler would be unused surface area that still has to be operated.

## Consequences

- `thread` mode lets the whole product run on a laptop (and in hosted previews) without
  Redis; the tests use it.
- Dispatch failures are explicit: unreachable Redis marks the job `failed` with
  `queue_unavailable` and raises an alert. The API never reports a job as scheduled when it
  is not.
- The dispatch contract is tested without Redis (recording queue: job id, queue name,
  `job_timeout`, description; refusing queue: `queue_unavailable`), and the real thing is
  tested with Redis: `tests/test_queue_redis.py` enqueues through `dispatch`, runs an RQ
  worker in burst mode and asserts the run landed in the database. CI provides Redis 7 as a
  service container; the file skips cleanly where no broker exists.
- RQ gives us per-job `job_timeout`, which maps onto the same 300 s budget the runner
  enforces independently (so a hung process is still bounded).
- A claim abandoned by a dead worker is **failed**, not silently re-queued: the sweep in
  `worker.poll` transitions it with a conditional UPDATE, writes one audit event and raises
  one alert. Re-running work that may have produced side effects stays a human decision.
- If we later need scheduled/periodic workloads, Celery beat or a cron entry becomes more
  attractive; the DB-outbox shape of the job table makes that a transport change, not a
  redesign.

## Rejected

- **Celery.** More moving parts than the workload justifies; would still need our own status
  table to survive broker restarts.
- **FastAPI `BackgroundTasks` only.** Dies with the process, no claim semantics, no retry.
- **In-process threads only.** Simple, but a restart loses running work and there is no way
  to scale workers independently.
