"""Reproducible forecasting study: validation, chronological holdout and final forecast.

Protocol
--------
1. Build a wide ``date x series`` matrix from validated demand.
2. **Rolling-origin validation** (optional, bounded): for each of ``validation_folds``
   windows ending *before* the holdout, refit each model on data before the origin and
   forecast ``horizon_days`` ahead. This is the only information used to pick a model.
3. **Chronological holdout**: refit on everything before the holdout, forecast the holdout
   window once, and score it. The holdout is never used for selection.
4. **Final forecast**: refit on all observed data and forecast ``horizon_days`` past the end.

Forecast mode
-------------
All reported forecasts are **fixed multi-step recursive** forecasts: the model is fitted
once per origin and then asked for ``horizon_days`` consecutive days. For step 1 the lag
features are real observations; for later steps they contain the model's own earlier
predictions, so errors compound. This is deliberately *not* the same as the one-step
rolling forecasts in the predecessor project, and metrics are labelled accordingly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .features import FEATURES, MIN_HISTORY_DAYS, make_feature_row
from .metrics import aggregate_metrics, forecast_metrics, seasonal_naive_scale
from .models import MODEL_LABELS, build_estimator, validate_model_params
from .schema import MAX_HORIZON_DAYS, MAX_SERIES, normalize_demand

STUDY_MODE_HOLDOUT = "fixed_multi_step_recursive"
STUDY_MODE_ROLLING_ORIGIN = "rolling_origin_validation"

FORECAST_MODE_LABEL = (
    "Fixed multi-step recursive forecast: one fit per origin, horizon steps produced in "
    "sequence using the model's own earlier predictions as lag inputs."
)

MIN_VALIDATION_FOLDS = 0
MAX_VALIDATION_FOLDS = 5


class StudyError(ValueError):
    """Raised when a dataset cannot support the requested study."""

    def __init__(self, message: str, *, code: str = "study_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StudyConfig:
    horizon_days: int = 14
    holdout_days: int = 14
    validation_folds: int = 2
    seed: int = 42
    model_keys: tuple[str, ...] = ("seasonal_naive", "hist_gradient_boosting")
    model_params: dict[str, dict[str, Any]] = field(default_factory=dict)

    def validate(self) -> StudyConfig:
        if not 1 <= self.horizon_days <= MAX_HORIZON_DAYS:
            raise StudyError(f"horizon_days must be between 1 and {MAX_HORIZON_DAYS}", code="invalid_horizon")
        if not 1 <= self.holdout_days <= 90:
            raise StudyError("holdout_days must be between 1 and 90", code="invalid_holdout")
        if not MIN_VALIDATION_FOLDS <= self.validation_folds <= MAX_VALIDATION_FOLDS:
            raise StudyError(
                f"validation_folds must be between {MIN_VALIDATION_FOLDS} and {MAX_VALIDATION_FOLDS}",
                code="invalid_folds",
            )
        if not self.model_keys:
            raise StudyError("at least one model must be requested", code="invalid_models")
        if len(set(self.model_keys)) != len(self.model_keys):
            raise StudyError("duplicate model keys requested", code="invalid_models")
        if "seasonal_naive" not in self.model_keys:
            raise StudyError(
                "the seasonal-naive baseline must be included so results stay comparable",
                code="baseline_required",
            )
        if not isinstance(self.seed, int) or not 0 <= self.seed <= 2**31 - 1:
            raise StudyError("seed must be an integer between 0 and 2^31-1", code="invalid_seed")
        for key in self.model_keys:
            validate_model_params(key, self.model_params.get(key))
        return self


ProgressFn = Callable[[int, str], None]


def _noop_progress(_pct: int, _message: str) -> None:
    return None


def _wide_matrix(clean: pd.DataFrame) -> pd.DataFrame:
    clean = clean.copy()
    clean["series_key"] = clean["store"].astype(str) + "||" + clean["item"].astype(str)
    wide = clean.pivot(index="date", columns="series_key", values="sales").sort_index()
    # Reindex onto a continuous calendar so lag arithmetic is day-accurate.
    full_index = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
    wide = wide.reindex(full_index).fillna(0.0)
    wide.index.name = "date"
    return wide


def _fit_model(
    model_key: str,
    params: dict[str, Any],
    seed: int,
    wide: pd.DataFrame,
    last_index: int,
) -> Any:
    """Fit on every row up to and including ``last_index``."""

    from .features import build_series_training_frame

    train_width = wide.iloc[: last_index + 1]
    frames = [
        build_series_training_frame(train_width.index, train_width[key].to_numpy(dtype=float), *key.split("||"))
        for key in train_width.columns
    ]
    stacked = pd.concat(frames, ignore_index=True).dropna(subset=[*FEATURES, "y"])
    if stacked.empty:
        raise StudyError(
            "Not enough history to train: each series needs at least "
            f"{MIN_HISTORY_DAYS} days before the first forecast date.",
            code="insufficient_history",
        )
    model = build_estimator(model_key, params, seed=seed)
    model.fit(stacked[FEATURES], stacked["y"].to_numpy(dtype=float))
    return model


def _recursive_forecast(
    model: Any,
    history: np.ndarray,
    last_observed: date,
    horizon_days: int,
    store: str,
    item: str,
) -> list[float]:
    values = list(np.asarray(history, dtype=float))
    predictions: list[float] = []
    for step in range(horizon_days):
        target = last_observed + timedelta(days=step + 1)
        row = make_feature_row(values, target, store, item)
        frame = pd.DataFrame([row], columns=FEATURES)
        raw = float(model.predict(frame)[0])
        if not np.isfinite(raw):
            raise StudyError("model produced a non-finite prediction", code="model_failure")
        prediction = max(0.0, raw)
        predictions.append(prediction)
        values.append(prediction)
    return predictions


def _forecast_window(
    model: Any,
    wide: pd.DataFrame,
    origin_index: int,
    horizon_days: int,
) -> dict[str, list[float]]:
    """Forecast ``horizon_days`` after ``origin_index`` for every series."""

    out: dict[str, list[float]] = {}
    last_observed = wide.index[origin_index].date()
    for key in wide.columns:
        store, item = key.split("||")
        history = wide[key].iloc[: origin_index + 1].to_numpy(dtype=float)
        out[key] = _recursive_forecast(model, history, last_observed, horizon_days, store, item)
    return out


def _score_window(
    wide: pd.DataFrame,
    origin_index: int,
    predictions: dict[str, list[float]],
    mase_denominators: dict[str, float | None],
    series_meta: dict[str, tuple[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score predictions against observed demand; returns (aggregate, per-series rows)."""

    per_series: list[dict[str, Any]] = []
    aggregate_inputs: list[dict[str, float | None]] = []
    for key, preds in predictions.items():
        store, item = series_meta[key]
        rows = []
        for step, prediction in enumerate(preds):
            index = origin_index + 1 + step
            if index >= len(wide):
                continue
            actual = float(wide[key].iloc[index])
            rows.append((wide.index[index].date(), actual, prediction))
        if not rows:
            continue
        actuals = [row[1] for row in rows]
        forecasts = [row[2] for row in rows]
        metrics = forecast_metrics(actuals, forecasts, mase_denominator=mase_denominators.get(key))
        per_series.append(
            {
                "series_key": key,
                "store": store,
                "item": item,
                **{k: v for k, v in metrics.items() if k not in {"abs_error", "abs_actual"}},
                "abs_error": metrics["abs_error"],
                "abs_actual": metrics["abs_actual"],
                "mean_actual": float(np.mean(actuals)),
            }
        )
        aggregate_inputs.append(metrics)
    aggregate = aggregate_metrics(aggregate_inputs)
    return aggregate, per_series


def _residual_bands(
    holdout_predictions: dict[str, list[float]],
    wide: pd.DataFrame,
    origin_index: int,
) -> dict[str, tuple[float, float]]:
    """Empirical 10th/90th residual quantiles per series from the holdout window.

    These are *descriptive*: they come from the holdout residuals of the same model. They
    are not calibrated prediction intervals and the UI labels them as an empirical band.
    """

    pooled: list[float] = []
    per_series: dict[str, list[float]] = {}
    for key, preds in holdout_predictions.items():
        residuals = []
        for step, prediction in enumerate(preds):
            index = origin_index + 1 + step
            if index >= len(wide):
                continue
            residuals.append(float(wide[key].iloc[index]) - prediction)
        per_series[key] = residuals
        pooled.extend(residuals)

    def quantiles(values: list[float]) -> tuple[float, float]:
        if len(values) < 5:
            return (0.0, 0.0)
        return (float(np.quantile(values, 0.1)), float(np.quantile(values, 0.9)))

    pooled_band = quantiles(pooled)
    return {key: quantiles(values) if len(values) >= 5 else pooled_band for key, values in per_series.items()}


def run_forecast_study(
    frame: pd.DataFrame,
    config: StudyConfig | None = None,
    *,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Run the complete study and return a JSON-serialisable bundle."""

    config = (config or StudyConfig()).validate()
    emit = progress or _noop_progress
    emit(2, "Validating demand data")

    clean, quality = normalize_demand(frame, max_series=MAX_SERIES)
    wide = _wide_matrix(clean)
    total_days = len(wide)
    required_days = config.holdout_days + MIN_HISTORY_DAYS + 2
    if total_days < required_days:
        raise StudyError(
            f"Dataset spans {total_days} days; this configuration needs at least {required_days} "
            f"({config.holdout_days} holdout days + {MIN_HISTORY_DAYS} history days).",
            code="insufficient_history",
        )

    holdout_start = total_days - config.holdout_days
    series_meta: dict[str, tuple[str, str]] = {key: tuple(key.split("||")) for key in wide.columns}

    # MASE denominators come from the training window only (never the scored window).
    mase_denominators: dict[str, float | None] = {
        key: seasonal_naive_scale(wide[key].iloc[:holdout_start].to_numpy(dtype=float)) for key in wide.columns
    }

    models: list[dict[str, Any]] = []
    anchors: dict[str, int] = {}

    for position, model_key in enumerate(config.model_keys):
        params = validate_model_params(model_key, config.model_params.get(model_key))
        emit(10 + position * 5, f"Running rolling-origin validation for {MODEL_LABELS[model_key]}")
        folds: list[dict[str, Any]] = []
        for fold in range(config.validation_folds):
            # The last validation day must stay strictly before the holdout start.
            origin = holdout_start - 1 - config.horizon_days * (config.validation_folds - fold)
            if origin < MIN_HISTORY_DAYS + 2:
                continue
            model = _fit_model(model_key, params, config.seed, wide, origin)
            predictions = _forecast_window(model, wide, origin, config.horizon_days)
            aggregate, _ = _score_window(wide, origin, predictions, mase_denominators, series_meta)
            folds.append(
                {
                    "origin": wide.index[origin].date().isoformat(),
                    "train_end": wide.index[origin].date().isoformat(),
                    "test_start": wide.index[origin + 1].date().isoformat()
                    if origin + 1 < total_days
                    else None,
                    "test_end": wide.index[min(origin + config.horizon_days, total_days - 1)].date().isoformat(),
                    "metrics": {k: aggregate.get(k) for k in ("mae", "rmse", "wape", "mase", "bias")},
                }
            )
        models.append({"model_key": model_key, "params": params, "folds": folds})
        anchors[model_key] = holdout_start

    emit(35, "Fitting on the training window and scoring the chronological holdout")

    holdout_origin = holdout_start - 1
    results: list[dict[str, Any]] = []
    for position, entry in enumerate(models):
        model_key = entry["model_key"]
        params = entry["params"]
        model = _fit_model(model_key, params, config.seed, wide, holdout_origin)
        holdout_predictions = _forecast_window(model, wide, holdout_origin, config.holdout_days)
        aggregate, per_series = _score_window(
            wide, holdout_origin, holdout_predictions, mase_denominators, series_meta
        )
        holdout_points = []
        for key, preds in holdout_predictions.items():
            store, item = series_meta[key]
            for step, prediction in enumerate(preds):
                index = holdout_origin + 1 + step
                if index >= total_days:
                    continue
                holdout_points.append(
                    {
                        "series_key": key,
                        "store": store,
                        "item": item,
                        "date": wide.index[index].date().isoformat(),
                        "actual": round(float(wide[key].iloc[index]), 4),
                        "forecast": round(float(prediction), 4),
                    }
                )

        bands = _residual_bands(holdout_predictions, wide, holdout_origin)

        # Final production forecast: refit on the full observed range.
        final_model = _fit_model(model_key, params, config.seed, wide, total_days - 1)
        last_observed = wide.index[-1].date()
        forecast_points = []
        for key in wide.columns:
            store, item = series_meta[key]
            history = wide[key].to_numpy(dtype=float)
            series_predictions = _recursive_forecast(
                final_model, history, last_observed, config.horizon_days, store, item
            )
            lower_q, upper_q = bands.get(key, (0.0, 0.0))
            for step, prediction in enumerate(series_predictions):
                forecast_points.append(
                    {
                        "series_key": key,
                        "store": store,
                        "item": item,
                        "date": (last_observed + timedelta(days=step + 1)).isoformat(),
                        "forecast": round(float(prediction), 4),
                        "lower": round(max(0.0, prediction + lower_q), 4),
                        "upper": round(max(0.0, prediction + upper_q), 4),
                    }
                )

        results.append(
            {
                "model_key": model_key,
                "label": MODEL_LABELS[model_key],
                "params": params,
                "requires_fit": model_key != "seasonal_naive",
                "forecast_mode": STUDY_MODE_HOLDOUT,
                "forecast_mode_label": FORECAST_MODE_LABEL,
                "seed": config.seed,
                "holdout": {
                    "train_start": wide.index[0].date().isoformat(),
                    "train_end": wide.index[holdout_origin].date().isoformat(),
                    "test_start": wide.index[holdout_start].date().isoformat(),
                    "test_end": wide.index[-1].date().isoformat(),
                    "test_days": config.holdout_days,
                },
                "metrics": {
                    "aggregate": {k: aggregate.get(k) for k in ("mae", "rmse", "wape", "mase", "bias", "n")},
                    "per_series": per_series,
                },
                "holdout_points": holdout_points,
                "forecast_points": forecast_points,
                "validation_folds": entry["folds"],
            }
        )
        emit(35 + int(50 * (position + 1) / len(models)), f"Scored {MODEL_LABELS[model_key]}")

    selected = _select_model(results)
    emit(92, "Selecting model and finalising artifacts")

    baseline = next((r for r in results if r["model_key"] == "seasonal_naive"), None)
    return {
        "config": {
            "horizon_days": config.horizon_days,
            "holdout_days": config.holdout_days,
            "validation_folds": config.validation_folds,
            "seed": config.seed,
            "model_keys": list(config.model_keys),
            "model_params": {entry["model_key"]: entry["params"] for entry in results},
        },
        "selected_model": selected,
        "selection_rule": (
            "Lowest mean WAPE across rolling-origin validation folds (MAE as a tie-break when WAPE "
            "is undefined). Fold windows end before the chronological holdout, so the holdout never "
            "influences model choice."
        ),
        "comparison": _comparison_summary(results, baseline),
        "quality": quality.as_dict(),
        "dataset": {
            "date_min": quality.date_min,
            "date_max": quality.date_max,
            "series_count": quality.series_count,
            "days": total_days,
        },
        "runs": results,
        "limitations": _limitations(config, quality.as_dict()),
    }


def _select_model(results: list[dict[str, Any]]) -> str:
    scored: list[tuple[float, float, str]] = []
    for run in results:
        folds = run.get("validation_folds") or []
        wapes = [f["metrics"]["wape"] for f in folds if f["metrics"].get("wape") is not None]
        maes = [f["metrics"]["mae"] for f in folds if f["metrics"].get("mae") is not None]
        if folds and (wapes or maes):
            primary = float(np.mean(wapes)) if wapes else float("inf")
            secondary = float(np.mean(maes)) if maes else float("inf")
            scored.append((primary, secondary, run["model_key"]))
        else:
            aggregate = run["metrics"]["aggregate"].get("wape")
            fallback = run["metrics"]["aggregate"].get("mae") or float("inf")
            selected_score = float(aggregate) if aggregate is not None else float(fallback)
            scored.append((selected_score, float(fallback), run["model_key"]))
    scored.sort()
    return scored[0][2] if scored else "seasonal_naive"


def _comparison_summary(results: list[dict[str, Any]], baseline: dict[str, Any] | None) -> dict[str, Any]:
    baseline_wape = (baseline or {}).get("metrics", {}).get("aggregate", {}).get("wape")
    rows = []
    for run in results:
        aggregate = run["metrics"]["aggregate"]
        wape = aggregate.get("wape")
        rows.append(
            {
                "model_key": run["model_key"],
                "label": run["label"],
                "wape": wape,
                "mae": aggregate.get("mae"),
                "rmse": aggregate.get("rmse"),
                "mase": aggregate.get("mase"),
                "relative_wape_vs_baseline": (
                    float(wape / baseline_wape) if wape is not None and baseline_wape not in (None, 0) else None
                ),
            }
        )
    return {"rows": rows, "baseline_model": "seasonal_naive"}


def _limitations(config: StudyConfig, quality: dict[str, Any]) -> list[str]:
    notes = [
        "All forecasts are fixed multi-step recursive forecasts: after the first step the model consumes "
        "its own predictions, so error compounds with horizon.",
        "Metrics are computed on a chronological holdout from the same dataset. They describe this dataset "
        "only and are not a benchmark on real retail demand.",
        "The seasonal-naive lag-7 baseline is always included; a model that does not beat it should not be "
        "trusted for planning.",
        "No promotions, prices, holidays or stockouts are modelled. Unobserved demand lost to stockouts "
        "cannot be recovered from sales alone.",
    ]
    if config.validation_folds == 0:
        notes.append(
            "Rolling-origin validation was disabled for this run; model selection fell back to the holdout ordering."
        )
    if quality.get("missing_dates_filled"):
        notes.append(f"{quality['missing_dates_filled']} missing calendar day(s) were treated as zero demand.")
    if quality.get("zero_demand_days"):
        share = quality["zero_demand_days"] / max(quality.get("row_count_out") or 1, 1)
        if share > 0.25:
            notes.append(f"Zero demand is {share:.0%} of series-days; WAPE and MASE are unstable in that regime.")
    return notes
