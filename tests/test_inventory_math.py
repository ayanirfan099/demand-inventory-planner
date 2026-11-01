"""Reorder policy arithmetic: formula, rounding, boundaries and zero-demand behaviour."""

from __future__ import annotations

import math

import pytest
from app.services.inventory import (
    ReorderInputs,
    compute_reorder,
    round_order_quantity,
    service_factor,
)


def inputs(**overrides) -> ReorderInputs:
    defaults = {
        "on_hand": 100.0,
        "daily_forecast": tuple([10.0] * 28),
        "lead_time_days": 14,
        "review_period_days": 7,
        "service_level": 0.95,
        "min_order_qty": 0,
        "pack_size": 1,
        "residual_sigma": 2.0,
    }
    defaults.update(overrides)
    return ReorderInputs(**defaults)


def test_formula_matches_the_documented_definition():
    result = compute_reorder(inputs())
    window = 21
    expected_demand = 10.0 * window
    expected_safety = service_factor(0.95) * 2.0 * math.sqrt(window)
    assert result.forecast_demand == pytest.approx(expected_demand)
    assert result.safety_stock == pytest.approx(expected_safety, rel=1e-3)
    assert result.reorder_point == pytest.approx(expected_demand + expected_safety, rel=1e-3)
    assert result.projected_on_hand == pytest.approx(100.0 - expected_demand)
    assert result.shortage == pytest.approx(expected_demand + expected_safety - 100.0, rel=1e-3)


def test_service_factor_matches_the_normal_quantile():
    assert service_factor(0.5) == pytest.approx(0.0, abs=1e-9)
    assert service_factor(0.95) == pytest.approx(1.6449, abs=1e-4)
    assert service_factor(0.99) == pytest.approx(2.3263, abs=1e-4)
    with pytest.raises(ValueError):
        service_factor(0.49)
    with pytest.raises(ValueError):
        service_factor(0.9995)


def test_safety_stock_scales_with_the_square_root_of_the_window():
    short = compute_reorder(inputs(lead_time_days=7, review_period_days=7))
    long = compute_reorder(inputs(lead_time_days=21, review_period_days=7))
    assert long.safety_stock / short.safety_stock == pytest.approx(math.sqrt(2), rel=1e-3)


def test_no_shortage_means_no_order():
    result = compute_reorder(inputs(on_hand=10_000))
    assert result.shortage == 0
    assert result.suggested_qty == 0


def test_zero_demand_produces_no_order():
    result = compute_reorder(inputs(daily_forecast=tuple([0.0] * 28), on_hand=5, residual_sigma=0.0))
    assert result.forecast_demand == 0
    assert result.safety_stock == 0
    assert result.reorder_point == 0
    assert result.suggested_qty == 0


def test_negative_on_hand_is_treated_as_zero_projection_but_not_clamped():
    result = compute_reorder(inputs(on_hand=-20))
    assert result.projected_on_hand < 0
    assert result.shortage == pytest.approx(result.reorder_point + 20)


def test_pack_size_rounds_up_never_down():
    result = compute_reorder(inputs(pack_size=12, on_hand=0))
    assert result.suggested_qty % 12 == 0
    assert result.suggested_qty >= result.suggested_qty_raw
    assert result.suggested_qty - result.suggested_qty_raw < 12


def test_minimum_order_quantity_is_applied_before_pack_rounding():
    assert round_order_quantity(1, min_order_qty=50, pack_size=6) == 54
    assert round_order_quantity(51, min_order_qty=50, pack_size=6) == 54
    assert round_order_quantity(0, min_order_qty=50, pack_size=6) == 0
    assert round_order_quantity(0.0001, pack_size=5) == 5


def test_invalid_pack_size_is_rejected():
    with pytest.raises(ValueError):
        round_order_quantity(10, pack_size=0)


def test_lead_time_boundaries():
    zero_lead = compute_reorder(inputs(lead_time_days=0, review_period_days=7))
    assert zero_lead.window_days == 7
    assert zero_lead.forecast_demand == pytest.approx(70.0)
    with pytest.raises(ValueError):
        compute_reorder(inputs(lead_time_days=-1))
    with pytest.raises(ValueError):
        compute_reorder(inputs(review_period_days=0))


def test_horizon_shorter_than_window_is_extrapolated_and_flagged():
    result = compute_reorder(inputs(daily_forecast=tuple([10.0] * 7), lead_time_days=14, review_period_days=7))
    assert result.extrapolated_days == 14
    assert result.forecast_demand == pytest.approx(210.0)


def test_empty_forecast_is_rejected():
    with pytest.raises(ValueError):
        compute_reorder(inputs(daily_forecast=()))
