# Operations

Configuration, limits, retention, backups, failure handling and the day-2 runbook.

## 1. Configuration

Everything is environment-driven with the `FORECASTOPS_` prefix (`services/api/app/config.py`).
`.env.example` documents a working local set.

| Variable | Default | Notes |
| --- | --- | --- |
| `FORECASTOPS_ENVIRONMENT` | `development` | `development` / `test` / `production` |
| `FORECASTOPS_DATABASE_URL` | `sqlite:///./data/local/forecastops.db` | Compose uses `postgresql+psycopg://…` |
| `FORECASTOPS_DATA_DIR` | `./data/local` | Datasets, previews, temp uploads |
| `FORECASTOPS_EXECUTION_MODE` | `thread` | `thread` / `rq` / `external` |
| `FORECASTOPS_REDIS_URL` | `redis://localhost:6379/0` | Only used in `rq` mode |
| `FORECASTOPS_JOB_QUEUE_NAME` | `forecastops` | RQ queue name |
| `FORECASTOPS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated allow-list |
| `FORECASTOPS_SESSION_COOKIE_NAME` | `forecastops_session` | |
| `FORECASTOPS_SESSION_TTL_HOURS` | `12` | Absolute session expiry |
| `FORECASTOPS_COOKIE_SECURE` | `false` | **Set `true` behind TLS** |
| `FORECASTOPS_MAX_UPLOAD_BYTES` | 5 MiB | Enforced while streaming |
| `FORECASTOPS_MAX_UPLOAD_ROWS` | 200 000 | Enforced during parsing |
| `FORECASTOPS_MAX_SERIES` | 200 | Enforced twice (API + library) |
| `FORECASTOPS_MAX_HORIZON_DAYS` | 90 | Mirrors the library bound |
| `FORECASTOPS_JOB_TIMEOUT_SECONDS` | 300 | Wall-clock budget checked in the progress callback |
| `FORECASTOPS_LOGIN_RATE_LIMIT` | 10 / hour / identity | Sliding window |
| `FORECASTOPS_UPLOAD_RATE_LIMIT` | 20 / hour / user | |
| `FORECASTOPS_JOB_RATE_LIMIT` | 30 / hour / user | |
| `FORECASTOPS_STALE_DATASET_DAYS` | 30 | Stale-dataset alert threshold |
| `FORECASTOPS_HIGH_ERROR_WAPE_THRESHOLD` | 0.5 | High-error alert threshold |
| `FORECASTOPS_DEMO_PASSWORD` | `planning-demo-2024` | Fictional; change for any shared deployment |
| `FORECASTOPS_LOG_LEVEL` | `INFO` | |

Rate limiting is **in-process** (a bounded sliding-window counter per key). It protects a
single API replica; with several replicas each has its own budget. Moving it to Redis is a
known follow-up, not a hidden behaviour.

## 2. Resource bounds

| Resource | Bound | Where enforced |
| --- | --- | --- |
| Upload bytes | 5 MiB | Request streaming + `413 payload_too_large` |
| Rows | 200 000 | `read_demand_csv(max_rows=…)` |
| Series | 200 | API check + `normalize_demand(max_series=…)` |
| Horizon | 90 days | Pydantic + `StudyConfig.validate()` |
| Holdout | 90 days | Pydantic + library |
| Validation folds | 5 | Pydantic + library |
| Model hyper-parameters | bounded ranges | `models.validate_model_params` |
| Job wall-clock | 300 s | Progress callback → `timeout` failure |
| Queue concurrency | 2 threads (`thread` mode) | `ThreadPoolExecutor(max_workers=2)` |
| Preview lifetime | 30 minutes | `storage.PREVIEW_TTL_SECONDS` |

## 3. Retention

| Data | Retention | Mechanism |
| --- | --- | --- |
| Upload previews | 30 minutes | `sweep_previews()` on API startup and preview load |
| Temporary upload files | Cleared at startup | `cleanup_temp_dir()` |
| Dataset version CSVs | Kept with the dataset version | Delete the dataset (owner) to remove the files |
| Forecast runs, points, metrics | Kept with the job | Deleting the job cascades to its runs |
| Audit events | **Never deleted by the app** | Retain ≥ 1 year in production; export and archive rather than prune |
| Export records | Kept with the run | Files are generated on demand, not stored |
| Sessions | Deleted on expiry/logout | TTL check on every request |

There is no background retention daemon. In production, run the preview sweep with the API
restart or a scheduled `curl -X POST` against your own maintenance endpoint — do not assume
a cleanup job exists that this repository does not ship.

## 4. Backups

- **Database**: standard `pg_dump` of the `forecastops` database. Audit events and
  dataset/job metadata are the irreplaceable part.
- **Data directory**: back up `data/datasets/{org_id}/{dataset_id}/*.csv` together with the
  database. A version row whose file is missing fails loudly (`dataset_unavailable`) rather
  than forecasting an empty frame — but the run is lost until the file is restored.
- **Restore order**: files first, then database, then verify `GET /readyz` and re-run a
  known forecast job to confirm results reproduce (same seed + same config + same version
  must give identical numbers).

## 5. Failure handling

| Symptom | Meaning | Action |
| --- | --- | --- |
| `/readyz` 503 with `database: error`, data endpoints 503 `service_unavailable` | DB unreachable (the API maps driver outages to 503, never 500) | Check `FORECASTOPS_DATABASE_URL`, DB health, credentials |
| `/readyz` 200 with `queue.degraded` | Redis unreachable, API still serving | Jobs will fail with `queue_unavailable` until Redis returns |
| Jobs stuck `running` | Worker died mid-job | `sweep_stale_claims()` on poller start fails claims older than the budget + 60 s with `worker_error` and raises an alert; retry the job explicitly |
| `413` on upload | Over 5 MiB | Raise the limit consciously, or split by store |
| `invalid_dataset` with row numbers | Contract violation | Fix the file; nothing was imported |
| `insufficient_history` | Dataset shorter than holdout + 15 days | Shorten holdout or upload more history |
| `timeout` | 300 s budget exceeded | Fewer series / shorter horizon / disable folds |
| Repeated 429 | Rate limit | Wait for the window, or raise the configured limit |

### Runbook: restart safely

1. `docker compose -f infra/docker-compose.yml ps` — confirm `db` and `redis` are healthy.
2. `docker compose ... restart api` — the API applies migrations, sweeps previews, then
   serves traffic. `/healthz` is live immediately; `/readyz` follows the DB.
3. `docker compose ... restart worker` — the poller fails abandoned claims (budget + 60 s) on
   start, each with one alert, so nothing sits in `running` forever.
4. Check `GET /api/v1/forecast-jobs?status=failed` for jobs that failed during the outage.

### Seeding

```bash
docker compose -f infra/docker-compose.yml exec api python scripts/seed_demo.py
```

Idempotent: it will not duplicate the demo org, dataset or users. Never run it against a
database that contains real data.

## 6. Testing and CI

| Layer | Command | Notes |
| --- | --- | --- |
| Forecasting library | `pytest packages/forecasting/tests -q` | 43 tests, no DB, no network |
| API integration + worker | `pytest tests -q` | 81 tests, isolated SQLite per test |
| Lint / types | `ruff check .`, `mypy services/api/app packages/forecasting/src services/worker/worker packages/contracts/src` | |
| Contract drift | `pytest packages/contracts/tests -q` | 10 tests: limits, metric keys, error codes, alert keys, OpenAPI snapshot |
| Synthetic smoke | `python scripts/smoke_study.py` | Reproducible pipeline run; explicitly not a benchmark (`docs/benchmark.md`) |
| Web unit | `cd apps/web && npm run typecheck && npm run lint && npm test` | Vitest: 18 tests (formatting, API client, WCAG contrast of the palette tokens) |
| Web e2e | `cd apps/web && npm run e2e` | Playwright; boots its own API + web on a throwaway SQLite DB |
| Accessibility | `cd apps/web && npx playwright test e2e/accessibility.spec.ts` | axe-core WCAG 2.1 A/AA; the flow spec audits run detail, planning, alerts and datasets too |
| Live queue | `pytest tests/test_queue_redis.py` | Needs `FORECASTOPS_REDIS_URL`; skips without a broker. CI runs it against a Redis 7 service |
| Containers | `docker compose -f infra/docker-compose.yml config`, `docker build …` | CI builds all three images and health-checks the API container |

The e2e script (`scripts/e2e-server.sh`) deletes and recreates `data/e2e/e2e.db`. Never point
it at a database you care about. Screenshots for documentation:
`npm run e2e:screenshots` (tagged `@screenshots`).

CI runs the same commands (`.github/workflows/ci.yml`); it needs no paid services and no
large downloads beyond the Python/npm dependency tree and the Playwright Chromium binary.

## 7. Production checklist

Before calling any deployment "live":

- [ ] `FORECASTOPS_COOKIE_SECURE=true` and the app served over TLS.
- [ ] `FORECASTOPS_ALLOWED_ORIGINS` set to the real web origin only.
- [ ] Demo password changed; demo users disabled or removed.
- [ ] `FORECASTOPS_ENVIRONMENT=production`, log level `INFO`.
- [ ] Managed Postgres with `pg_dump` schedule; `data` volume on durable storage.
- [ ] Redis with persistence (`appendonly yes`) and a supervised RQ worker.
- [ ] Rate limiting moved to a shared store if running more than one API replica.
- [ ] Retention and audit-export policy reviewed with whoever owns compliance.
