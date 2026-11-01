# Architecture decision records

Short, dated records of the decisions that shape ForecastOps. Each one states the context,
the decision, the consequences and what was rejected. They describe *this* repository, not a
production system.

| # | Decision |
| --- | --- |
| [0001](0001-monorepo-and-separation.md) | Monorepo with a framework-free forecasting library |
| [0002](0002-async-jobs-rq-not-celery.md) | RQ on Redis for async jobs (not Celery), with a DB-poller fallback |
| [0003](0003-forecast-protocol-and-metrics.md) | Rolling-origin selection, untouched chronological holdout, fixed multi-step forecasts |
| [0004](0004-inventory-reorder-model.md) | Periodic-review reorder point with an empirical residual sigma |
| [0005](0005-session-auth-and-tenancy.md) | Server-side sessions, centralized authorization, 404 for cross-tenant access |
| [0006](0006-quality-gates.md) | Lint, types, unit, integration and browser tests as merge gates |
