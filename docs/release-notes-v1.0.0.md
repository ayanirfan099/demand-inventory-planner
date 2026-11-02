# ForecastOps v1.0.0 — Demand & Inventory Planning

First release. A forecasting and inventory-planning tool with honest baselines, a tested
methodology, and a UI that states what it knows and what it does not.

Tagged from `main` at `3bc4a6e`, after four merged milestones (M0–M5) and five green CI jobs.

## What it does

Upload demand CSVs (or use the seeded fictional demo), run a bounded asynchronous forecast,
compare models against a **lag-7 seasonal-naive baseline that is always reported**, inspect
forecast-vs-actual charts with aggregate and per-series metrics, then turn the selected forecast
into **reorder suggestions with the formula and its assumptions shown**.

## Highlights

- **Leakage-free by construction** — lag and shifted-rolling features only; chronological
  holdout; rolling-origin validation selects the model; the final test range is never tuned on.
- **Fixed multi-step is labelled as such** — recursive forecasting, distinguished from one-step
  rolling evaluation in both the UI and the methodology.
- **Undefined metrics stay undefined** — MASE/WAPE zero-demand behaviour is documented and
  returns `null` rather than a plausible-looking number.
- **Inventory maths is visible** — lead time, review period, service level → safety factor, MOQ
  and pack size, with the raw value kept for audit. No supplier, price or lead-time data is ever
  invented.
- **Four alert rules** — low projected stock, high forecast error, stale dataset, failed job.
- **Org-scoped with tested isolation** — owner/analyst/viewer roles, cross-tenant reads answer
  404 in both directions, HttpOnly hashed sessions, fictional demo account.
- **Failure behaviour is a feature** — Redis, worker or Postgres outages degrade to 503 /
  `queue_unavailable` instead of 500s, and the DB-poller mode recovers orphaned jobs.
- **Accessibility is gated** — palette contrast is unit-tested and an axe-core WCAG 2.1 A/AA
  audit runs against login, every page and the data-dense screens in CI.

## What it is not

The bundled numbers are a **synthetic smoke study, not a benchmark**: seasonal-naive
MAE 10.768 / RMSE 14.821 / WAPE 0.230 / MASE 1.106; gradient boosting MAE 9.001 / RMSE 11.990 /
WAPE 0.192 / MASE 0.937. Selection chose the baseline on rolling-origin WAPE while the
chronological holdout preferred gradient boosting — that disagreement is documented rather than
resolved in the model's favour (see [`benchmark.md`](benchmark.md)).

Deliberately out of scope: promotions, prices, holidays, stockout censoring, lead-time
variability, supplier costs and shared-store (multi-process) rate limiting.

## Verified in CI

| Gate | Result |
| --- | --- |
| Python — ruff, mypy (41 files), 139 tests | pass |
| Web — `tsc`, `next lint`, 18 unit tests, build (12 routes) | pass |
| Queue — live Redis 7 round-trip through RQ, forecast persisted by the worker | pass |
| Containers — compose config, three image builds, API container migrates and answers `/healthz` + `/readyz` | pass |
| Browser — Playwright flow (login → upload → forecast → charts → reorder → export) | pass |
| Accessibility — axe-core WCAG 2.1 A/AA, 0 violations | pass |

Everything in that table also runs locally except the browser suite (Chromium cannot be
downloaded in the restricted development sandbox) and Docker (no daemon there); the README
states exactly which claims are CI-only.

## Quick start

```bash
docker compose -f infra/docker-compose.yml up --build
docker compose -f infra/docker-compose.yml exec api python scripts/seed_demo.py
# sign in as demo@forecastops.example / planning-demo-2024
```

Without Docker: install `requirements/dev.txt`, run `alembic upgrade head`, `python
services/api/scripts/seed_demo.py`, then the API and `npm run dev` in `apps/web`.

## Documentation

[`README.md`](../README.md) ·
[`docs/methodology.md`](methodology.md) ·
[`docs/architecture.md`](architecture.md) ·
[`docs/operations.md`](operations.md) ·
[`docs/benchmark.md`](benchmark.md) ·
[`docs/adr/`](adr/) (six decision records)

## Known limits

- No screen-reader usability testing with real users; the claim is contrast, keyboard-first
  markup, textual chart equivalents and a clean automated audit.
- The queue's rate limiter is in-process, so it bounds a single API process, not a fleet.
- The demo dataset is synthetic by design; no real business data ships with the repository.
