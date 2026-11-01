"""Drift tests: every constant in this package must still describe the real code.

The point of ``forecastops_contracts`` is to be a single readable statement of the
cross-component contract. A constant that silently disagrees with the code it describes is
worse than no constant, so each value here is checked against the module that enforces it.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.errors import AppError
from forecastops_contracts import (
    ALERT_RULE_KEYS,
    API_ERROR_CODES,
    DATASET_ERROR_CODES,
    JOB_FAILURE_CODES,
    JOB_STATUSES,
    LIMITS,
    METRIC_KEYS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    STUDY_MODES,
)
from forecastops_forecasting import study
from forecastops_forecasting.features import MIN_HISTORY_DAYS
from forecastops_forecasting.metrics import METRIC_KEYS as LIBRARY_METRIC_KEYS
from forecastops_forecasting.schema import (
    MAX_HORIZON_DAYS,
    MAX_ROWS,
    MAX_SERIES,
)
from forecastops_forecasting.schema import (
    OPTIONAL_COLUMNS as LIBRARY_OPTIONAL,
)
from forecastops_forecasting.schema import (
    REQUIRED_COLUMNS as LIBRARY_REQUIRED,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_SOURCES = [
    *sorted((REPO_ROOT / "services" / "api" / "app").rglob("*.py")),
    *sorted((REPO_ROOT / "packages" / "forecasting" / "src").rglob("*.py")),
]


def _source_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in PYTHON_SOURCES)


def _subclasses(cls):
    for child in cls.__subclasses__():
        yield child
        yield from _subclasses(child)


def test_upload_contract_matches_library():
    assert REQUIRED_COLUMNS == LIBRARY_REQUIRED
    assert OPTIONAL_COLUMNS == LIBRARY_OPTIONAL


def test_metric_keys_match_library():
    assert METRIC_KEYS == LIBRARY_METRIC_KEYS


def test_study_modes_are_the_ones_the_library_emits():
    assert set(STUDY_MODES) == {study.STUDY_MODE_HOLDOUT, study.STUDY_MODE_ROLLING_ORIGIN}


def test_limits_match_the_library_and_the_api_defaults():
    # Read the declared field defaults, not a constructed Settings: the test env sets
    # smaller limits on purpose and must not be able to redefine the documented contract.
    settings = Settings.model_fields
    assert LIMITS["max_rows"] == MAX_ROWS
    assert LIMITS["max_series"] == MAX_SERIES
    assert LIMITS["max_horizon_days"] == MAX_HORIZON_DAYS
    assert LIMITS["max_validation_folds"] == study.MAX_VALIDATION_FOLDS
    assert LIMITS["min_history_days"] == MIN_HISTORY_DAYS
    assert LIMITS["max_upload_bytes"] == settings["max_upload_bytes"].default
    assert LIMITS["max_upload_rows"] == settings["max_upload_rows"].default
    assert LIMITS["max_series"] == settings["max_series"].default
    assert LIMITS["max_horizon_days"] == settings["max_horizon_days"].default
    assert LIMITS["max_holdout_days"] == settings["max_holdout_days"].default
    assert LIMITS["job_timeout_seconds"] == settings["job_timeout_seconds"].default


def test_api_error_codes_match_the_error_hierarchy():
    declared = {cls.code for cls in _subclasses(AppError)} | {AppError.code}
    assert set(API_ERROR_CODES) == declared


def test_domain_error_codes_appear_in_the_code_that_raises_them():
    source = _source_text()
    missing = [code for code in DATASET_ERROR_CODES if code not in source]
    assert not missing, f"dataset error codes no longer referenced anywhere: {missing}"


def test_job_failure_codes_are_used_somewhere():
    source = _source_text()
    missing = [code for code in JOB_FAILURE_CODES if code not in source]
    assert not missing, f"job failure codes no longer referenced anywhere: {missing}"


def test_job_statuses_are_the_persisted_lifecycle():
    source = _source_text()
    missing = [status for status in JOB_STATUSES if f'"{status}"' not in source]
    assert not missing, f"job statuses no longer referenced anywhere: {missing}"


def test_alert_rule_keys_are_the_dedupe_key_prefixes():
    source = (REPO_ROOT / "services" / "api" / "app" / "services" / "alerts.py").read_text(encoding="utf-8")
    for rule in ALERT_RULE_KEYS:
        assert f'f"{rule}:' in source, f"alert rule {rule!r} has no dedupe key {rule}:… in alerts.py"


def test_the_openapi_snapshot_matches_the_app():
    """packages/contracts/openapi.json is what reviewers and clients read offline."""

    from app.main import create_app

    committed = json.loads((REPO_ROOT / "packages" / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    current = json.loads(json.dumps(create_app().openapi(), sort_keys=True))
    assert committed == current, "openapi.json is stale; run scripts/export-openapi.py"
