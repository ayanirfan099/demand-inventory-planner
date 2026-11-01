"""Leakage checklist as executable tests.

Each test encodes a claim from ``docs/leakage-checklist.md``.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from forecastops_forecasting.features import (
    FEATURES,
    build_series_training_frame,
    make_feature_row,
)


def _series(days: int = 40, seed: int = 3) -> tuple[pd.DatetimeIndex, np.ndarray]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    return dates, np.round(rng.uniform(0, 50, size=days), 3)


def test_training_features_ignore_the_target_day_value():
    dates, values = _series()
    base = build_series_training_frame(dates, values, "s1", "i1")
    perturbed_values = values.copy()
    perturbed_values[25] = 9999.0
    perturbed = build_series_training_frame(dates, perturbed_values, "s1", "i1")

    # Only rows for the perturbed date *and later* may change: the row for day 25 itself
    # uses days 24, 18, 11 and the rolling mean of days 18-24.
    pd.testing.assert_frame_equal(base.loc[:24, FEATURES], perturbed.loc[:24, FEATURES])
    assert perturbed.loc[25, "lag_1"] == pytest.approx(values[24])
    assert perturbed.loc[26, "lag_1"] == pytest.approx(9999.0)


def test_rolling_mean_excludes_the_current_day():
    dates, values = _series()
    frame = build_series_training_frame(dates, values, "s1", "i1")
    for index in (10, 20, 30):
        expected = values[index - 7 : index].mean()
        assert frame.loc[index, "rolling_mean_7"] == pytest.approx(expected)


def test_inference_row_matches_training_row_definition():
    dates, values = _series()
    frame = build_series_training_frame(dates, values, "s1", "i1")
    target = dates[-1].date()
    row = make_feature_row(values[:-1], target, "s1", "i1")

    last = frame.iloc[-1]
    assert row["lag_1"] == pytest.approx(last["lag_1"])
    assert row["lag_7"] == pytest.approx(last["lag_7"])
    assert row["lag_14"] == pytest.approx(last["lag_14"])
    assert row["rolling_mean_7"] == pytest.approx(last["rolling_mean_7"])
    assert row["day_of_week"] == target.weekday()
    assert row["day_of_year"] == target.timetuple().tm_yday


def test_feature_row_rejects_insufficient_history():
    with pytest.raises(ValueError):
        make_feature_row([1.0, 2.0, 3.0], date(2024, 1, 20), "s1", "i1")


def test_calendar_features_do_not_depend_on_demand():
    _, values = _series()
    first = make_feature_row(values[:20], date(2024, 3, 4), "s1", "i1")
    second = make_feature_row(np.zeros(20), date(2024, 3, 4), "s1", "i1")
    assert first["day_of_week"] == second["day_of_week"]
    assert first["month"] == second["month"]
