"""Deterministic synthetic demo demand.

The generator is seeded and reproducible: the same ``seed``, ``stores``, ``items``,
``days`` and ``end_date`` always produce the same numbers. It produces plausible-looking
weekly/annual seasonality with promo spikes and zero-demand days so that the pipeline is
exercised realistically — but every number is synthetic and no metric derived from it is
evidence of real-world forecasting skill.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

DEMO_STORES = ("north-dock", "river-bend", "harbour-hill")
DEMO_ITEMS = ("coffee-beans", "paper-cups", "oat-milk", "cold-brew")
DEMO_DAYS = 365
DEMO_SEED = 20240517


def generate_demo_demand(
    *,
    days: int = DEMO_DAYS,
    seed: int = DEMO_SEED,
    stores: tuple[str, ...] = DEMO_STORES,
    items: tuple[str, ...] = DEMO_ITEMS,
    end_date: date | None = None,
    include_on_hand: bool = True,
) -> pd.DataFrame:
    """Return a tidy synthetic demand frame with ``date, store, item, sales[, on_hand]``."""

    if days < 60:
        raise ValueError("demo data needs at least 60 days to allow a holdout")
    if not stores or not items:
        raise ValueError("at least one store and one item are required")

    rng = np.random.default_rng(seed)
    end = end_date or date.today()
    start = end - timedelta(days=days - 1)
    dates = pd.date_range(start, end, freq="D")
    day_offsets = np.arange(days)

    rows: list[dict[str, object]] = []
    for store_index, store in enumerate(stores):
        for item_index, item in enumerate(items):
            base = 18 + 26 * rng.random() + 6 * store_index
            weekly = 1 + 0.28 * np.sin(2 * np.pi * (day_offsets % 7) / 7 + item_index)
            weekend = np.where(pd.Index(day_offsets).to_numpy() % 7 >= 5, 1.18, 1.0)
            annual = 1 + 0.16 * np.sin(2 * np.pi * day_offsets / 365.25 + store_index)
            growth = 1 + 0.10 * day_offsets / days
            noise = rng.normal(1.0, 0.12, size=days)
            promos = np.zeros(days)
            promo_starts = rng.choice(np.arange(20, days - 12), size=3, replace=False)
            for promo_start in promo_starts:
                length = int(rng.integers(3, 6))
                promos[promo_start : promo_start + length] = rng.uniform(0.35, 0.8)

            demand = base * weekly * weekend * annual * growth * noise * (1 + promos)
            demand = np.clip(np.round(demand), 0, None)

            # Slow-moving items get genuine zero days; this is the regime where WAPE and
            # MASE need explicit handling and where aggregate metrics hide weak series.
            if item_index % 4 == 3:
                zero_days = rng.random(days) < 0.18
                demand = np.where(zero_days, 0, demand)

            on_hand_levels = None
            if include_on_hand:
                recent = demand[-21:]
                cover = rng.uniform(0.35, 1.6)
                on_hand_levels = max(0.0, float(np.round(recent.mean() * 21 * cover)))

            for offset in range(days):
                row: dict[str, object] = {
                    "date": dates[offset].date().isoformat(),
                    "store": store,
                    "item": item,
                    "sales": int(demand[offset]),
                }
                if on_hand_levels is not None:
                    row["on_hand"] = round(on_hand_levels)
                rows.append(row)

    frame = pd.DataFrame(rows)
    return frame.sort_values(["store", "item", "date"]).reset_index(drop=True)
