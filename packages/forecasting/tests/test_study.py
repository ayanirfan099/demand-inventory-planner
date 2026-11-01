"""End-to-end study protocol tests: split, reproducibility, selection, guards."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from forecastops_forecasting.generator import generate_demo_demand
from forecastops_forecasting.study import StudyConfig, StudyError, run_forecast_study


@pytest.fixture(scope="module")
def demo_frame() -> pd.DataFrame:
    return generate_demo_demand(
        days=120,
        seed=99,
        stores=("s1", "s2"),
        items=("i1", "i2"),
        end_date=date(2025, 6, 30),
    )


@pytest.fixture(scope="module")
def study(demo_frame: pd.DataFrame) -> dict:
    config = StudyConfig(horizon_days=7, holdout_days=7, validation_folds=1, seed=5)
    return run_forecast_study(demo_frame, config)


def test_both_models_and_baseline_are_reported(study: dict):
    keys = [run["model_key"] for run in study["runs"]]
    assert keys == ["seasonal_naive", "hist_gradient_boosting"]
    assert study["selected_model"] in keys


def test_chronological_split_does_not_overlap_training(study: dict):
    for run in study["runs"]:
        assert run["holdout"]["train_end"] < run["holdout"]["test_start"]
    assert study["dataset"]["date_max"] == study["runs"][0]["holdout"]["test_end"]


def test_validation_folds_end_before_the_holdout(study: dict):
    holdout_start = study["runs"][0]["holdout"]["test_start"]
    for run in study["runs"]:
        for fold in run["validation_folds"]:
            assert fold["test_end"] < holdout_start


def test_holdout_points_cover_each_series_day(study: dict):
    run = study["runs"][0]
    config = study["config"]
    expected = study["dataset"]["series_count"] * config["holdout_days"]
    assert len(run["holdout_points"]) == expected
    assert len(run["forecast_points"]) == study["dataset"]["series_count"] * config["horizon_days"]


def test_forecast_starts_the_day_after_the_last_observation(study: dict):
    run = study["runs"][0]
    first_forecast = min(point["date"] for point in run["forecast_points"])
    assert first_forecast > study["dataset"]["date_max"]
    assert pd.Timestamp(first_forecast) == pd.Timestamp(study["dataset"]["date_max"]) + pd.Timedelta(days=1)


def test_bands_are_ordered_and_non_negative(study: dict):
    for point in study["runs"][0]["forecast_points"]:
        assert 0 <= point["lower"] <= point["upper"]
        assert point["forecast"] >= 0


def test_study_is_reproducible_for_a_fixed_seed(demo_frame: pd.DataFrame):
    config = StudyConfig(horizon_days=7, holdout_days=7, validation_folds=0, seed=11)
    first = run_forecast_study(demo_frame, config)
    second = run_forecast_study(demo_frame, config)
    assert first["runs"] == second["runs"]


def test_metric_aggregate_matches_pooled_per_series_errors(study: dict):
    for run in study["runs"]:
        per_series = run["metrics"]["per_series"]
        pooled = sum(row["abs_error"] for row in per_series) / sum(row["abs_actual"] for row in per_series)
        assert run["metrics"]["aggregate"]["wape"] == pytest.approx(pooled)


def test_baseline_is_required():
    with pytest.raises(StudyError) as excinfo:
        StudyConfig(model_keys=("hist_gradient_boosting",)).validate()
    assert excinfo.value.code == "baseline_required"


def test_horizon_bounds_are_enforced():
    with pytest.raises(StudyError):
        StudyConfig(horizon_days=1000).validate()
    with pytest.raises(StudyError):
        StudyConfig(holdout_days=0).validate()


def test_insufficient_history_is_a_typed_error():
    dates = pd.date_range("2025-01-01", periods=30, freq="D")
    short = pd.DataFrame(
        {
            "date": [d.date().isoformat() for d in dates],
            "store": "s1",
            "item": "i1",
            "sales": 5,
        }
    )
    with pytest.raises(StudyError) as excinfo:
        run_forecast_study(short, StudyConfig(horizon_days=14, holdout_days=14, validation_folds=1))
    assert excinfo.value.code == "insufficient_history"


def test_progress_reports_monotonic_percentages(demo_frame: pd.DataFrame):
    events: list[tuple[int, str]] = []
    run_forecast_study(
        demo_frame,
        StudyConfig(horizon_days=3, holdout_days=3, validation_folds=0),
        progress=lambda pct, message: events.append((pct, message)),
    )
    percentages = [pct for pct, _ in events]
    assert percentages == sorted(percentages)
    assert percentages[-1] >= 90
