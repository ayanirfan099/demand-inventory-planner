# 0001 — Monorepo with a framework-free forecasting library

- **Status:** accepted
- **Date:** 2026-10-30

## Context

The product needs a web UI, an API, a worker and a forecasting core. The forecasting code is
the most valuable and most testable part, and it is also the part most likely to be reused
(e.g. a batch CLI later). Mixing it into the API would make every experiment need a database
and an HTTP client.

## Decision

One repository, four deployables plus one library:

```
apps/web            Next.js
services/api        FastAPI
services/worker     RQ worker / DB poller
packages/forecasting  pure pandas/sklearn library
packages/contracts    shared constants + drift tests
```

`packages/forecasting` imports nothing from `services/` or `apps/`; `services/api` depends on
it one-way. Bounds (horizon, holdout, folds, series) are declared in the library and mirrored
by the API, which is the first line of defence rather than the only one.

## Consequences

- Forecasting tests run in seconds with no fixtures beyond a pandas frame.
- The same `run_forecast_job(job_id)` executes in dev, in tests and in production; only the
  dispatch transport changes.
- Duplication risk: data-contract constants exist in both the library and the API. Mitigated
  by drift tests in `packages/contracts` and by the API importing library errors verbatim.
- Heavier repo tooling (ruff/mypy/pytest run across three Python trees).

## Rejected

- **Everything in the API.** Simpler deployment, but the library would drag FastAPI and a
  session into every test.
- **Separate repositories.** The contract changes often enough that cross-repo PRs would
  dominate the work for no benefit at this size.
