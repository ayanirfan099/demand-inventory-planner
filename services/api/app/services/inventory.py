"""Reorder decision support.

This module implements one documented, configurable periodic-review policy. It never
places orders: it produces suggestions with the arithmetic and assumptions attached so a
planner can audit them.

Formula
-------
Let ``W = lead_time_days + review_period_days`` (the exposure window), ``mu_d`` the mean
daily forecast over that window and ``sigma_d`` the standard deviation of the selected
model's holdout residuals for the series.

    forecast_demand   = sum of daily forecasts over W
    safety_stock      = z(service_level) * sigma_d * sqrt(W)
    reorder_point     = forecast_demand + safety_stock
    projected_on_hand = on_hand - forecast_demand
    shortage          = max(0, reorder_point - on_hand)
    suggested_qty     = round_up_to_pack(max(shortage, min_order_qty))   when shortage > 0

Assumptions that are explicitly *not* modelled: supplier lead-time variability, minimum
order quantities per supplier, price breaks, shelf life, capacity, and demand censored by
stockouts. ``z`` is the normal quantile implied by the chosen service level; the service
level is a planning input, not a guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import Session as OrmSession

from ..models import (
    ForecastPoint,
    ForecastRun,
    InventoryPolicy,
    ReorderSuggestion,
    SeriesDefinition,
)
from . import alerts, audit

MIN_SERVICE_LEVEL = 0.5
MAX_SERVICE_LEVEL = 0.999
MAX_LEAD_TIME_DAYS = 365
MAX_REVIEW_PERIOD_DAYS = 180


@dataclass(frozen=True)
class ReorderInputs:
    on_hand: float
    daily_forecast: tuple[float, ...]
    lead_time_days: int
    review_period_days: int
    service_level: float
    min_order_qty: int = 0
    pack_size: int = 1
    residual_sigma: float = 0.0
    horizon_days: int | None = None

    @property
    def window_days(self) -> int:
        return self.lead_time_days + self.review_period_days


@dataclass(frozen=True)
class ReorderResult:
    window_days: int
    forecast_demand: float
    safety_stock: float
    reorder_point: float
    projected_on_hand: float
    shortage: float
    suggested_qty_raw: float
    suggested_qty: int
    service_factor: float
    extrapolated_days: int


def service_factor(service_level: float) -> float:
    """Normal quantile for a service level, e.g. 0.95 -> 1.645."""

    if not MIN_SERVICE_LEVEL <= service_level < MAX_SERVICE_LEVEL:
        raise ValueError(f"service_level must be in [{MIN_SERVICE_LEVEL}, {MAX_SERVICE_LEVEL})")
    return NormalDist().inv_cdf(service_level)


def round_order_quantity(raw: float, *, min_order_qty: int = 0, pack_size: int = 1) -> int:
    """Apply the minimum order quantity, then round up to whole packs."""

    if pack_size < 1:
        raise ValueError("pack_size must be at least 1")
    if raw <= 0:
        return 0
    quantity = max(raw, float(min_order_qty))
    packs = math.ceil(quantity / pack_size)
    return int(packs * pack_size)


def compute_reorder(inputs: ReorderInputs) -> ReorderResult:
    if inputs.lead_time_days < 0:
        raise ValueError("lead_time_days must be non-negative")
    if inputs.review_period_days < 1:
        raise ValueError("review_period_days must be at least 1")
    if inputs.window_days < 1:
        raise ValueError("the planning window must include at least one day")
    if inputs.pack_size < 1:
        raise ValueError("pack_size must be at least 1")

    window = inputs.window_days
    daily = [max(0.0, float(value)) for value in inputs.daily_forecast]
    if not daily:
        raise ValueError("at least one forecast day is required")

    covered = min(window, len(daily))
    extrapolated_days = window - covered
    forecast_demand = float(sum(daily[:covered]))
    if extrapolated_days > 0:
        # Beyond the forecast horizon we assume the mean forecasted daily rate continues.
        # This is an assumption, recorded on the suggestion.
        mean_daily = sum(daily) / len(daily)
        forecast_demand += mean_daily * extrapolated_days

    z = service_factor(inputs.service_level)
    safety_stock = z * max(0.0, inputs.residual_sigma) * math.sqrt(window)
    reorder_point = forecast_demand + safety_stock
    projected_on_hand = inputs.on_hand - forecast_demand
    shortage = max(0.0, reorder_point - inputs.on_hand)
    suggested_raw = shortage
    suggested = round_order_quantity(
        suggested_raw, min_order_qty=inputs.min_order_qty, pack_size=inputs.pack_size
    )
    return ReorderResult(
        window_days=window,
        forecast_demand=round(forecast_demand, 4),
        safety_stock=round(safety_stock, 4),
        reorder_point=round(reorder_point, 4),
        projected_on_hand=round(projected_on_hand, 4),
        shortage=round(shortage, 4),
        suggested_qty_raw=round(suggested_raw, 4),
        suggested_qty=suggested,
        service_factor=round(z, 4),
        extrapolated_days=extrapolated_days,
    )


def _series_forecasts(db: OrmSession, run_id: int, horizon_days: int) -> dict[int, list[float]]:
    rows = db.execute(
        select(ForecastPoint.series_id, ForecastPoint.target_date, ForecastPoint.forecast)
        .where(ForecastPoint.run_id == run_id, ForecastPoint.kind == "forecast")
        .order_by(ForecastPoint.target_date)
    ).all()
    by_series: dict[int, list[float]] = {}
    dates: dict[int, int] = {}
    for series_id, _target, forecast in rows:
        series_dates = dates.setdefault(series_id, 0)
        if series_dates >= horizon_days:
            continue
        dates[series_id] = series_dates + 1
        by_series.setdefault(series_id, []).append(float(forecast))
    return by_series


def _residual_sigma(db: OrmSession, run_id: int) -> dict[int, float]:
    rows = db.execute(
        select(ForecastPoint.series_id, ForecastPoint.actual, ForecastPoint.forecast).where(
            ForecastPoint.run_id == run_id, ForecastPoint.kind == "holdout"
        )
    ).all()
    residuals: dict[int, list[float]] = {}
    for series_id, actual, forecast in rows:
        if actual is None:
            continue
        residuals.setdefault(series_id, []).append(float(actual) - float(forecast))
    sigma: dict[int, float] = {}
    for series_id, values in residuals.items():
        # Sample standard deviation; a single observation carries no dispersion information.
        sigma[series_id] = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return sigma


def generate_suggestions(
    db: Session,
    *,
    org_id: int,
    user_id: int | None,
    policy: InventoryPolicy,
    run: ForecastRun,
) -> list[ReorderSuggestion]:
    """Compute and persist reorder suggestions for every series in the run's dataset."""

    forecasts = _series_forecasts(db, run.id, policy.lead_time_days + policy.review_period_days + 1)
    sigma = _residual_sigma(db, run.id)
    series_rows = db.scalars(
        select(SeriesDefinition)
        .where(SeriesDefinition.dataset_id == policy.dataset_id)
        .order_by(SeriesDefinition.store, SeriesDefinition.item)
    ).all()

    # Supersede open suggestions from earlier runs of the same policy: the newest
    # computation is the only one a planner should act on.
    previous_open = db.scalars(
        select(ReorderSuggestion).where(
            ReorderSuggestion.policy_id == policy.id, ReorderSuggestion.status == "open"
        )
    ).all()
    for suggestion in previous_open:
        suggestion.status = "dismissed"

    created: list[ReorderSuggestion] = []
    for series in series_rows:
        daily = forecasts.get(series.id)
        if not daily:
            continue
        on_hand = float(series.on_hand if series.on_hand is not None else 0)
        result = compute_reorder(
            ReorderInputs(
                on_hand=on_hand,
                daily_forecast=tuple(daily),
                lead_time_days=policy.lead_time_days,
                review_period_days=policy.review_period_days,
                service_level=policy.service_level,
                min_order_qty=policy.min_order_qty,
                pack_size=policy.pack_size,
                residual_sigma=sigma.get(series.id, 0.0),
            )
        )
        assumptions = {
            "formula": "reorder_point = sum(forecast over lead+review) + z * sigma_holdout * sqrt(lead+review)",
            "planning_window_days": result.window_days,
            "lead_time_days": policy.lead_time_days,
            "review_period_days": policy.review_period_days,
            "service_level": policy.service_level,
            "service_factor_z": result.service_factor,
            "residual_sigma_daily": round(sigma.get(series.id, 0.0), 4),
            "forecast_run_id": run.id,
            "model": run.model_key,
            "on_hand_source": "dataset snapshot" if series.on_hand is not None else "missing (treated as 0)",
            "extrapolated_days_beyond_horizon": result.extrapolated_days,
            "min_order_qty": policy.min_order_qty,
            "pack_size": policy.pack_size,
            "not_modelled": [
                "supplier lead-time variability",
                "price breaks and capacity",
                "shelf life and spoilage",
                "demand censored by stockouts",
            ],
            "service_level_is_not_a_guarantee": True,
        }
        suggestion = ReorderSuggestion(
            org_id=org_id,
            policy_id=policy.id,
            series_id=series.id,
            run_id=run.id,
            status="open",
            horizon_days=result.window_days,
            on_hand=on_hand,
            forecast_demand=result.forecast_demand,
            safety_stock=result.safety_stock,
            reorder_point=result.reorder_point,
            target_level=result.reorder_point,
            projected_on_hand=result.projected_on_hand,
            shortage=result.shortage,
            suggested_qty_raw=result.suggested_qty_raw,
            suggested_qty_rounded=result.suggested_qty,
            assumptions=assumptions,
            created_by_id=user_id,
        )
        db.add(suggestion)
        created.append(suggestion)
        if result.suggested_qty > 0:
            alerts.raise_low_stock(
                db,
                org_id=org_id,
                policy_id=policy.id,
                series_id=series.id,
                store=series.store,
                item=series.item,
                projected_on_hand=result.projected_on_hand,
                safety_stock=result.safety_stock,
                suggested_qty=result.suggested_qty,
            )

    db.flush()
    audit.record(
        db,
        org_id=org_id,
        action="reorder_suggestions.generated",
        entity_type="inventory_policy",
        entity_id=policy.id,
        actor_user_id=user_id,
        payload={
            "policy_snapshot": {
                "lead_time_days": policy.lead_time_days,
                "review_period_days": policy.review_period_days,
                "service_level": policy.service_level,
                "min_order_qty": policy.min_order_qty,
                "pack_size": policy.pack_size,
            },
            "run_id": run.id,
            "series_evaluated": len(created),
            "series_with_order": sum(1 for item in created if item.suggested_qty_rounded > 0),
            "total_units_suggested": sum(item.suggested_qty_rounded for item in created),
        },
    )
    return created
