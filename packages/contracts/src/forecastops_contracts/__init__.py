"""Contract constants shared by the API, the worker and the web app.

This package is the single readable statement of the things that must agree across
components: the upload contract, metric names, alert rule keys, job failure codes and the
resource limits. It deliberately holds **no logic** — a constant that drifts is worse than no
constant, so ``tests/test_contracts.py`` cross-checks every value here against the code that
actually enforces it (imported, not copied).

Values are re-exported rather than re-defined where the owning module is importable without
side effects; strings that only exist in SQL/docs are declared here and asserted by grep.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ALERT_RULE_KEYS",
    "API_ERROR_CODES",
    "DATASET_ERROR_CODES",
    "JOB_FAILURE_CODES",
    "JOB_STATUSES",
    "LIMITS",
    "METRIC_KEYS",
    "OPTIONAL_COLUMNS",
    "REQUIRED_COLUMNS",
    "STUDY_MODES",
]

# --- Upload contract ---------------------------------------------------------------------
# Canonical CSV header. Aliases (demand/units/qty -> sales, sku/product -> item,
# location/shop -> store) are mapped in forecastops_forecasting.schema.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = ("date", "store", "item", "sales")
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = ("on_hand",)

# --- Metrics -----------------------------------------------------------------------------
# Must match forecastops_forecasting.metrics.METRIC_KEYS.
METRIC_KEYS: Final[tuple[str, ...]] = ("mae", "rmse", "wape", "mase", "bias")

# --- Study modes -------------------------------------------------------------------------
STUDY_MODES: Final[tuple[str, ...]] = (
    "fixed_multi_step_recursive",
    "rolling_origin_validation",
)

# --- HTTP error codes --------------------------------------------------------------------
API_ERROR_CODES: Final[tuple[str, ...]] = (
    "bad_request",
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict",
    "payload_too_large",
    "rate_limited",
    "service_unavailable",
)

DATASET_ERROR_CODES: Final[tuple[str, ...]] = (
    "invalid_dataset",
    "missing_columns",
    "no_valid_rows",
    "empty_dataset",
    "encoding_error",
    "parse_error",
    "too_many_rows",
    "too_many_series",
    "unsupported_file_type",
    "preview_expired",
)

# --- Job lifecycle -----------------------------------------------------------------------
JOB_STATUSES: Final[tuple[str, ...]] = ("queued", "running", "succeeded", "failed", "cancelled")

# Terminal values of ForecastJob.failure_code. ``queue_unavailable`` means the job never ran;
# every other code means it ran and failed. Cancellation is a *status*, not a failure code.
JOB_FAILURE_CODES: Final[tuple[str, ...]] = (
    "queue_unavailable",
    "timeout",
    "invalid_dataset",
    "dataset_unavailable",
    "worker_error",
    "insufficient_history",
    "model_failure",
)

# --- Alerts ------------------------------------------------------------------------------
# Dedupe keys are ``{rule}:{scope}`` so a rule fires at most once per object.
ALERT_RULE_KEYS: Final[tuple[str, ...]] = (
    "low_stock",
    "high_error",
    "stale_dataset",
    "failed_job",
)

# --- Resource limits ---------------------------------------------------------------------
# Mirrors packages/forecasting/src/forecastops_forecasting/schema.py (library values) and
# services/api/app/config.py settings defaults. Both are asserted by the drift test.
LIMITS: Final[dict[str, int]] = {
    "max_rows": 200_000,
    "max_upload_rows": 200_000,
    "max_series": 200,
    "max_horizon_days": 90,
    "max_holdout_days": 90,
    "max_validation_folds": 5,
    "min_history_days": 15,
    "max_upload_bytes": 5 * 1024 * 1024,
    "job_timeout_seconds": 300,
}
