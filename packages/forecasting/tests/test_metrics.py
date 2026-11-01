"""Metric definitions, including the awkward zero-demand cases."""

from __future__ import annotations

import numpy as np
import pytest
from forecastops_forecasting.metrics import (
    aggregate_metrics,
    forecast_metrics,
    seasonal_naive_scale,
)


def test_known_values():
    metrics = forecast_metrics([10, 10, 10, 10], [8, 12, 10, 10])
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(2 ** 0.5)
    assert metrics["wape"] == pytest.approx(0.1)
    assert metrics["bias"] == pytest.approx(0.0)


def test_all_zero_actuals_return_none_wape_not_zero_or_infinity():
    metrics = forecast_metrics([0, 0, 0], [0, 3, 0])
    assert metrics["wape"] is None
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["mase"] is None


def test_mase_is_none_for_a_flat_series():
    flat = [5.0] * 40
    scale = seasonal_naive_scale(flat)
    assert scale is None
    assert forecast_metrics(flat[:7], flat[:7], mase_denominator=scale)["mase"] is None


def test_seasonal_naive_scale_uses_seven_day_differences():
    values = [1, 2, 3, 4, 5, 6, 7, 4, 4, 4, 4, 4, 4, 4]
    # |y_t - y_{t-7}| for t=7..13: 3, 2, 1, 0, 1, 2, 3 -> mean 12/7
    assert seasonal_naive_scale(values) == pytest.approx(12 / 7)


def test_aggregate_wape_pools_numerators_and_denominators():
    large = forecast_metrics([100, 100], [90, 90])  # WAPE 0.1, n=2
    small = forecast_metrics([1, 1], [0, 0])  # WAPE 1.0, n=2
    aggregate = aggregate_metrics([large, small])
    # Pooled: (20 + 2) / (200 + 2), not the (incorrect) mean of 0.1 and 1.0.
    assert aggregate["wape"] == pytest.approx(22 / 202)
    assert aggregate["n"] == 4


def test_aggregate_handles_all_undefined_wape():
    rows = [forecast_metrics([0, 0], [1, 2]), forecast_metrics([0, 0], [0, 0])]
    aggregate = aggregate_metrics(rows)
    assert aggregate["wape"] is None
    assert aggregate["mae"] == pytest.approx(0.75)


def test_shape_and_finiteness_are_validated():
    with pytest.raises(ValueError):
        forecast_metrics([1, 2], [1])
    with pytest.raises(ValueError):
        forecast_metrics([], [])
    with pytest.raises(ValueError):
        forecast_metrics([1, np.nan], [1, 1])
