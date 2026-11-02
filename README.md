# ForecastOps — Demand & Inventory Planning

[![CI](https://github.com/ayanirfan099/demand-inventory-planner/actions/workflows/ci.yml/badge.svg)](https://github.com/ayanirfan099/demand-inventory-planner/actions/workflows/ci.yml)

A full-stack demand forecasting and inventory planning workspace: validated CSV ingestion,
bounded asynchronous forecast jobs, an honest seasonal-naive baseline next to one documented
ML model, forecast-vs-actual evaluation, and reorder suggestions whose formula and
assumptions are visible in the product and stored in an audit trail.

Everything here is decision support on a single chronological holdout. **No number in this
repository is a real-world benchmark, and there is no production deployment, no real users
and no real business data.**

---

## What it does

| Capability | Where |
| --- | --- |
| CSV upload with a preview + rejection report before anything is committed | `/upload`, `POST /api/v1/datasets/previews` |
| Deterministic synthetic demo data (seeded, fictional products and stores) | `POST /api/v1/datasets/synthetic` |
| Bounded async forecast jobs (horizon, holdout, folds, models, seeds) | `/forecasts`, `POST /api/v1/forecast-jobs` |
| Baseline vs ML comparison under one identical protocol | `/forecasts/[runId]` |
| MAE / RMSE / WAPE / MASE / bias, aggregate + per series, plus residuals | `/forecasts/[runId]` |
| Inventory policies → reorder point, safety stock, suggested order | `/planning` |
| Four derived alert rules with acknowledgement | `/alerts` |
| Forecast / metrics CSV, JSON report, and an export registry | `/audit`, `GET /api/v1/forecast-runs/{id}/exports/report.json` |
| Org-scoped authN/authZ with owner / analyst / viewer roles | `services/api/app/deps.py` |
| A database outage returns 503 (not 500) without leaking driver details | `app/errors.py`, `tests/test_resilience.py` |
| Audit log of every consequential action | `/audit` |

## Architecture at a glance

```
┌────────────────────────────┐        ┌───────────────────────────────┐
│ apps/web — Next.js 15      │  HTTP  │ services/api — FastAPI        │
│ React 19, Recharts         │───────▶│ session cookies, authz,       │
│ server components + client │  /api  │ validation, exports           │
└────────────────────────────┘ proxy  └──────────┬────────────────────┘
                                                 │ SQLAlchemy
                                    ┌────────────▼─────────────┐
                                    │ PostgreSQL (or SQLite)   │
                                    │ org-scoped tables        │
                                    └────────────▲─────────────┘
                                                 │ claim / write
   ┌────────────────────────┐   job id    ┌──────┴────────────────────┐
   │ services/worker         │◀────────────│ packages/forecasting      │
   │ RQ worker or DB poller  │             │ pandas + scikit-learn     │
   └────────────────────────┘             └───────────────────────────┘
```

The web app never talks to the API host directly from the browser: `next.config.mjs`
proxies `/api/*` (and `/healthz`) to the API origin, so the browser only ever sees one
origin and the session cookie stays first-party. The authenticated shell is client-rendered:
it confirms the session with `/api/v1/auth/me`, then each page loads its data through the
same proxy. That keeps cookies first-party and one code path for every view, at the cost of a
loading state and a JavaScript requirement for the UI (the REST API itself does not need it).

- **Why RQ rather than Celery** and the other decisions: [`docs/adr/`](docs/adr).
- **Forecasting protocol, metrics, zero-demand behaviour:** [`docs/methodology.md`](docs/methodology.md).
- **Components, request flow, failure modes, security:** [`docs/architecture.md`](docs/architecture.md).
- **The synthetic smoke run and how (not) to read it:** [`docs/benchmark.md`](docs/benchmark.md).
- **Limits, retention, runbook, configuration:** [`docs/operations.md`](docs/operations.md).

## Repository layout

```
apps/web/                 Next.js 15 app (App Router, TypeScript, Recharts)
services/api/             FastAPI app, SQLAlchemy models, Alembic migrations, seed script
services/worker/          RQ worker (Redis) and standalone DB-poller worker
packages/forecasting/     Pure forecasting/evaluation library (no web or DB imports)
packages/contracts/       Shared contract constants, OpenAPI snapshot, drift tests
infra/                    Dockerfiles and docker-compose.yml
docs/                     Methodology, architecture, operations, ADRs
scripts/                  e2e server bootstrapper
tests/                    API integration tests (pytest, isolated SQLite)
```

## Quick start (SQLite, no Docker)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e packages/forecasting -e services/api

alembic -c services/api/alembic.ini upgrade head
python services/api/scripts/seed_demo.py            # fictional demo org + dataset
uvicorn app.main:app --reload --app-dir services/api --port 8000

cd apps/web && npm ci && npm run dev                # http://localhost:3000
```

Demo accounts (fictional, seeded only by the seed script):

| Role | Email | Password |
| --- | --- | --- |
| owner | `demo@forecastops.example` | `planning-demo-2024` |
| analyst | `analyst@forecastops.example` | `analyst-demo-2024` |
| viewer | `viewer@forecastops.example` | `viewer-demo-2024` |
| owner of a second, isolated org | `cascade@forecastops.example` | `cascade-demo-2024` |

`FORECASTOPS_DEMO_PASSWORD` overrides the demo password at seed time. Never reuse these
values anywhere real.

## Quick start (Docker Compose)

```bash
cp .env.example .env          # set POSTGRES_PASSWORD and FORECASTOPS_DEMO_PASSWORD
docker compose -f infra/docker-compose.yml up --build
# one-off seeding, once the api container is healthy:
docker compose -f infra/docker-compose.yml exec api python scripts/seed_demo.py
```

Services: `db` (Postgres 16), `redis` (7), `api`, `worker`, `web`. The API container runs
`alembic upgrade head` before starting. Seeding is deliberately *not* automatic, so a
restart never mutates demo data.

The images and the compose file are built and checked in CI (`Containers — build images and
validate compose`): `docker compose config` is validated, all three images are built, and the
API image is started for real — it applies Alembic migrations, then `/healthz` and `/readyz`
must answer. That job is the reason this section is a claim rather than a hope.

## Data contract

```
date,store,item,sales[,on_hand]
```

- `date` is an ISO date; `sales` is daily units sold for the `(store, item)` pair.
- Duplicate `(date, store, item)` rows are **summed** (transaction-style exports).
- Gaps *inside* an observed series are treated as zero-demand days, and the count is
  reported in the quality report — never silently invented.
- Column aliases (`demand`, `qty`, `units`, `sku`, `product`, `location`, `shop`) are mapped
  explicitly and the mapping is shown in the preview.
- Invalid rows are rejected with row numbers and reasons; the file is never partially
  imported as if it were clean.

| Bound | Default |
| --- | --- |
| Upload size | 5 MiB |
| Rows | 200,000 |
| Series | 200 |
| Horizon | 90 days |
| Holdout | 90 days (7–90) |
| Rolling-origin folds | 0–5 (default 2) |
| Serialised job time budget | 300 s |
| Login / upload / job rate limits | 10 / 20 / 30 per hour |

## Forecasting in one paragraph

Every run fits **lag-7 seasonal naive** (required, always) and one documented ML model
(histogram gradient boosting) on leakage-free features: only shifted lags, a rolling mean
that ends before the forecast origin, and calendar terms. Models are compared by
**rolling-origin validation**, the winner is refit, and a **chronological holdout** is
scored once — selection never touches it. Forecasts are **fixed multi-step recursive**
(`fixed_multi_step_recursive`): each horizon step is produced at the forecast origin and
later steps feed on the model's own earlier predictions, so error compounds. This is not the
same as a one-step rolling evaluation and the UI says so.

Metrics: MAE, RMSE, WAPE, MASE and mean bias. WAPE is undefined (not zero) when total
actual demand is zero; MASE is `None` when the baseline in-sample scale is zero. Per-series
metrics are always shown next to the aggregate so a good average cannot hide a bad series.

## Inventory planning in one paragraph

`W = lead_time + review_period`; projected demand is the forecast over `W` with mean-rate
extrapolation beyond the horizon; `safety_stock = z(service_level) * sigma_holdout * sqrt(W)`;
`reorder_point = projected demand + safety_stock`; the suggested order rounds the shortage up
to the MOQ and pack size. Every assumption is echoed in the API response and on the page:
`sigma_holdout` is an empirical residual scale, demand is assumed stationary over `W`, and
**no supplier data, lead-time history or unit costs are invented** — if it is not in your
upload or policy, it is not in the plan.

## API surface (v1)

```
POST   /api/v1/auth/login | logout          GET /api/v1/auth/me
POST   /api/v1/auth/switch-org              GET /api/v1/organizations[/members]
GET    /api/v1/datasets                     POST /api/v1/datasets/previews | imports
POST   /api/v1/datasets/imports/direct | synthetic
GET    /api/v1/datasets/{id}[/series|/demand|/quality]
GET    /api/v1/datasets/{id}/versions/{vid}/download
POST   /api/v1/forecast-jobs                GET /api/v1/forecast-jobs[/{id}|/{id}/runs]
POST   /api/v1/forecast-jobs/{id}/cancel | retry
GET    /api/v1/forecast-runs                GET /api/v1/forecast-runs/{id}
GET    /api/v1/forecast-runs/{id}/points | series-metrics | comparison | residuals
GET    /api/v1/forecast-runs/{id}/exports/{forecast.csv|metrics.csv|report.json}
CREATE/PATCH/GET /api/v1/inventory-policies[/{id}] , /{id}/suggestions, /{id}/latest-run
GET    /api/v1/inventory-suggestions        PATCH /api/v1/inventory-suggestions/{id}
GET    /api/v1/alerts                       POST /api/v1/alerts/{id}/status
GET    /api/v1/audit-events                 GET /api/v1/exports
GET    /healthz                             GET /readyz
```

OpenAPI is served at `/api/docs` and `/api/openapi.json`.

## Verification status

All of the following was run in this workspace (Python 3.11, Node 20):

| Command | Result |
| --- | --- |
| `pytest packages/forecasting/tests -q` | 43 passed |
| `pytest packages/contracts/tests -q` | 10 passed (contract + OpenAPI drift) |
| `pytest tests -q` (API integration + worker + resilience) | 86 passed (~45 s) |
| `ruff check .` | All checks passed |
| `mypy services/api/app packages/forecasting/src services/worker/worker packages/contracts/src` | Success: no issues in 41 source files |
| `npx tsc --noEmit` (apps/web) | clean |
| `npx next lint` (apps/web) | no warnings or errors |
| `npx vitest run` (apps/web) | 18 passed (formatting, API client, palette contrast) |
| `npx next build` (apps/web) | success, 12 routes |
| `python scripts/export-openapi.py --check` | snapshot current (45 paths) |
| `python scripts/smoke_study.py` | 12 series, 2 models, ~4 s (synthetic smoke; see [`docs/benchmark.md`](docs/benchmark.md)) |
| `pytest tests/test_queue_redis.py -q` | 2 skipped here (no broker); **passes in CI against a real Redis 7 service** |
| `docker compose config` + 3 image builds + API container health | **CI only** (`Containers` job) — no Docker daemon in this sandbox |
| `npx playwright test` | **not executed here** — Chromium cannot be downloaded in this sandbox; green in CI |
| axe-core WCAG 2.1 A/AA audit (browser suite) | **CI only** — login, all seven pages, and the data-dense screens once a run and suggestions exist; zero violations |

Known gaps, stated plainly:

- Browser end-to-end tests exist (`apps/web/e2e/`) but have never been executed in this
  environment. `curl` verified page shells, the Next→API proxy and every API endpoint, but
  page *content* is fetched client-side after the session resolves, so no rendered data view
  has been visually checked here. The Playwright suite in CI is what closes that gap.
- Docker and the live queue are verified in CI, not here: this sandbox has no Docker daemon
  and no Redis. Locally the `rq` dispatch contract is covered with a recording queue (job id,
  queue name, timeout, description) and a refusing queue (`queue_unavailable`); in CI the same
  job round-trips through a real Redis 7 broker and an RQ worker in burst mode, and the image
  build plus API container health checks run for real.
- `tests/test_queue_redis.py` skips when no broker answers, so a laptop without Redis reports
  "skipped" rather than a false pass.

## Milestones

- **M0** — documentation, ADRs, CI.
- **M1** — foundation: schema, auth, org isolation, ingestion.
- **M2** — async forecasting: job lifecycle, study protocol, metrics, exports.
- **M3** — dashboard, run detail, upload, datasets, alerts, audit UI.
- **M4** — inventory policies and reorder suggestions.
- **M5** — benchmark polish, seeded demo, deployment, limitations pass.

Each milestone is a reviewed pull request; nothing is tagged `v1.0.0` without the owner's
explicit sign-off.
