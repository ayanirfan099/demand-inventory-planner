"""Leakage-aware feature construction.

Two entry points produce *identical* feature definitions:

* :func:`build_training_frame` — supervision rows built from a wide date x series matrix.
* :func:`make_feature_row` — the same row built from a history vector at forecast time.

Every demand-derived feature is shifted by at least one day, so the value for target
date ``d`` never uses ``sales[d]``. The calendar features are deterministic from ``d``
and do not leak demand information.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

LAGS = (1, 7, 14)
ROLLING_WINDOW = 7
NUMERIC_FEATURES = [
    "lag_1",
    "lag_7",
    "lag_14",
    "rolling_mean_7",
    "day_of_week",
    "month",
    "day_of_year",
]
CATEGORICAL_FEATURES = ["store", "item"]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# A supervision row needs lag_14 plus a 7-day shifted rolling mean, i.e. 14 prior days.
MIN_HISTORY_DAYS = max(max(LAGS), ROLLING_WINDOW) + 1


def _day_of_week(dates) -> pd.Index:
    return dates.day_of_week if hasattr(dates, "day_of_week") else dates.dayofweek


def _day_of_year(dates) -> pd.Index:
    return dates.day_of_year if hasattr(dates, "day_of_year") else dates.dayofyear


def _calendar_features(target: date) -> dict[str, int]:
    return {
        "day_of_week": target.weekday(),
        "month": target.month,
        "day_of_year": target.timetuple().tm_yday,
    }


def make_feature_row(history: Sequence[float], target: date, store: str, item: str) -> dict[str, Any]:
    """Build one feature row for ``target`` from strictly earlier demand.

    ``history`` must contain the series' daily values up to the day before ``target``.
    """

    values = np.asarray(history, dtype=float)
    if values.size < MIN_HISTORY_DAYS:
        raise ValueError(f"need at least {MIN_HISTORY_DAYS} prior days of history")

    row: dict[str, Any] = {
        "store": store,
        "item": item,
        "lag_1": float(values[-1]),
        "lag_7": float(values[-7]),
        "lag_14": float(values[-14]),
        "rolling_mean_7": float(values[-7:].mean()),
    }
    row.update(_calendar_features(target))
    return row


def build_series_training_frame(
    dates: pd.DatetimeIndex,
    values: np.ndarray,
    store: str,
    item: str,
) -> pd.DataFrame:
    """Supervision rows for a single series, using only shifted demand."""

    series = pd.Series(values, index=dates, dtype=float)
    frame = pd.DataFrame({"date": dates, "y": series.to_numpy(dtype=float)})
    frame["store"] = store
    frame["item"] = item
    for lag in LAGS:
        frame[f"lag_{lag}"] = series.shift(lag).to_numpy(dtype=float)
    rolling = series.shift(1).rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean()
    frame["rolling_mean_7"] = rolling.to_numpy(dtype=float)
    frame["day_of_week"] = _day_of_week(dates)
    frame["month"] = dates.month
    frame["day_of_year"] = _day_of_year(dates)
    return frame


def build_training_frame(wide: pd.DataFrame) -> pd.DataFrame:
    """Build the stacked supervision frame from a wide ``date x series`` demand matrix.

    Columns are series keys of the form ``store||item``.
    """

    frames = [
        build_series_training_frame(wide.index, wide[key].to_numpy(dtype=float), *key.split("||"))
        for key in wide.columns
    ]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=[*FEATURES, "y"])
    combined = combined.sort_values(["store", "item", "date"]).reset_index(drop=True)
    if combined.empty:
        raise ValueError(
            "not enough history to build features; each series needs at least "
            f"{MIN_HISTORY_DAYS} days before the first forecast date"
        )
    return combined


def next_forecast_dates(last_observed: date, horizon_days: int) -> list[date]:
    """Calendar dates covered by a fixed multi-step forecast."""

    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    return [last_observed + timedelta(days=step) for step in range(1, horizon_days + 1)]
