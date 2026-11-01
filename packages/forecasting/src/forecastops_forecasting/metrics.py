"""Forecast metrics with explicit zero-demand behaviour.

Definitions (all on the evaluation window only):

* **MAE** — mean absolute error, in units of demand.
* **RMSE** — root mean squared error, in units of demand; penalises large misses.
* **WAPE** — sum(|error|) / sum(|actual|). Returned as ``None`` when total actual demand is
  zero, because the ratio is undefined; we never substitute 0 or infinity.
* **MASE** — MAE divided by the in-sample seasonal-naive (lag-7) MAE of the *training*
  window. ``None`` when that scale is zero (a perfectly flat, deterministic series) or
  when the series has too little history.
* **Bias** — mean(error), signed, to expose systematic over/under-forecasting.

An aggregate WAPE is produced from the summed numerator and denominator across series —
never as an unweighted mean of per-series WAPE, which would let tiny series dominate.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

METRIC_KEYS = ("mae", "rmse", "wape", "mase", "bias")


def _as_arrays(actual: Sequence[float], predicted: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(actual, dtype=float).ravel()
    p = np.asarray(predicted, dtype=float).ravel()
    if y.shape != p.shape:
        raise ValueError("actual and predicted must have the same shape")
    if y.size == 0:
        raise ValueError("actual and predicted must be non-empty")
    if not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError("actual and predicted must be finite")
    return y, p


def seasonal_naive_scale(values: Sequence[float], season: int = 7) -> float | None:
    """In-sample MASE denominator: mean |y_t - y_{t-season}| over the training window."""

    series = np.asarray(values, dtype=float)
    if series.size <= season:
        return None
    errors = np.abs(series[season:] - series[:-season])
    if errors.size == 0:
        return None
    scale = float(errors.mean())
    return scale if scale > 0 else None


def mase_scale(values: Sequence[float], season: int = 7) -> float | None:
    """Alias kept for readability at call sites."""

    return seasonal_naive_scale(values, season=season)


def forecast_metrics(
    actual: Sequence[float],
    predicted: Sequence[float],
    *,
    mase_denominator: float | None = None,
) -> dict[str, float | None]:
    """Compute MAE, RMSE, WAPE, MASE and bias for one evaluation window."""

    y, p = _as_arrays(actual, predicted)
    errors = np.abs(y - p)
    total_actual = float(np.abs(y).sum())
    mae = float(errors.mean())
    return {
        "mae": mae,
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "wape": float(errors.sum() / total_actual) if total_actual > 0 else None,
        "mase": float(mae / mase_denominator) if mase_denominator and mase_denominator > 0 else None,
        "bias": float(np.mean(p - y)),
        # Kept alongside the public metrics so aggregates can pool numerators and
        # denominators instead of averaging ratios.
        "n": int(y.size),
        "abs_error": float(errors.sum()),
        "abs_actual": total_actual,
    }


def aggregate_metrics(rows: Sequence[dict[str, float | None]]) -> dict[str, float | None]:
    """Combine per-window metric dicts into an aggregate (n-weighted for MAE/RMSE/MASE)."""

    if not rows:
        return dict.fromkeys(METRIC_KEYS)
    total_n = sum(int(row.get("n") or 0) for row in rows) or len(rows)

    def weighted(key: str) -> float | None:
        pairs: list[tuple[float, int]] = []
        for row in rows:
            value = row.get(key)
            if value is None:
                continue
            pairs.append((float(value), int(row.get("n") or 1)))
        if not pairs:
            return None
        weight = sum(item_weight for _, item_weight in pairs)
        return float(sum(value * item_weight for value, item_weight in pairs) / weight) if weight else None

    return {
        "mae": weighted("mae"),
        "rmse": weighted("rmse"),
        "wape": _combined_wape(rows),
        "mase": weighted("mase"),
        "bias": weighted("bias"),
        "n": total_n,
    }


def _combined_wape(rows: Sequence[dict[str, float | None]]) -> float | None:
    """WAPE from summed absolute error and demand, not an average of ratios."""

    numerator = 0.0
    denominator = 0.0
    for row in rows:
        abs_error = row.get("abs_error")
        abs_actual = row.get("abs_actual")
        if abs_error is not None:
            numerator += float(abs_error)
        if abs_actual is not None:
            denominator += float(abs_actual)
    if denominator <= 0:
        return None
    return float(numerator / denominator)
