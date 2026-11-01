"""Bounded forecasting models: a seasonal-naive baseline and a gradient-boosting model.

Both models consume the same feature matrix, which keeps the comparison honest: the only
difference between them is how they map identical, leakage-safe inputs to a prediction.

Hyper-parameters are validated against explicit bounds so that an API caller cannot ask
the worker for an unbounded training job.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .features import CATEGORICAL_FEATURES, NUMERIC_FEATURES

MODEL_KEYS = ("seasonal_naive", "hist_gradient_boosting")

MODEL_LABELS = {
    "seasonal_naive": "Seasonal naive (lag-7 baseline)",
    "hist_gradient_boosting": "Histogram gradient boosting",
}

MODEL_DESCRIPTIONS = {
    "seasonal_naive": (
        "Predicts demand for a date as the demand observed on the same weekday one week "
        "earlier. Costs almost nothing to compute and is the reference every model must beat."
    ),
    "hist_gradient_boosting": (
        "Gradient-boosted trees over lag, rolling-mean and calendar features with one-hot "
        "store/item indicators. A bounded, tabular model — no deep learning, no tuning on the "
        "final test range."
    ),
}

# name -> (default, minimum, maximum)
GBM_PARAM_BOUNDS: dict[str, tuple[float, float, float]] = {
    "learning_rate": (0.08, 0.01, 0.3),
    "max_iter": (150, 50, 400),
    "max_leaf_nodes": (31, 7, 63),
    "l2_regularization": (1.0, 0.0, 10.0),
    "min_samples_leaf": (20, 5, 100),
}
SEASONAL_NAIVE_SEASON = 7


def validate_model_params(model_key: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Return a fully-specified, in-bounds parameter dict for a model key."""

    if model_key not in MODEL_KEYS:
        raise ValueError(f"unknown model '{model_key}'; expected one of {', '.join(MODEL_KEYS)}")
    params = dict(params or {})
    if model_key == "seasonal_naive":
        unknown = set(params) - {"season"}
        if unknown:
            raise ValueError(f"seasonal_naive accepts only 'season'; got {', '.join(sorted(unknown))}")
        season = params.get("season", SEASONAL_NAIVE_SEASON)
        if isinstance(season, bool) or not isinstance(season, int) or not 1 <= season <= 14:
            raise ValueError("season must be an integer between 1 and 14")
        return {"season": season}

    unknown = set(params) - set(GBM_PARAM_BOUNDS)
    if unknown:
        raise ValueError(f"unknown hyper-parameter(s): {', '.join(sorted(unknown))}")
    resolved: dict[str, Any] = {}
    for name, (default, low, high) in GBM_PARAM_BOUNDS.items():
        value = params.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        if not low <= float(value) <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        resolved[name] = int(value) if name in {"max_iter", "max_leaf_nodes", "min_samples_leaf"} else float(value)
    return resolved


class SeasonalNaiveModel:
    """Lag-7 reference model: ``y_hat(t) = y(t - 7)``."""

    requires_fit = False

    def __init__(self, season: int = SEASONAL_NAIVE_SEASON, *, seed: int = 0):
        self.season = season
        self.seed = seed

    def fit(self, features: pd.DataFrame, target: pd.Series) -> SeasonalNaiveModel:  # noqa: ARG002 - API symmetry
        return self

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        column = f"lag_{self.season}"
        if column not in features.columns:
            raise ValueError(f"seasonal naive requires the '{column}' feature")
        values = features[column].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("seasonal naive received a missing lag value")
        return np.maximum(values, 0.0)


class GradientBoostingModel:
    """One-hot store/item + numeric features -> histogram gradient boosting."""

    requires_fit = True

    def __init__(self, params: dict[str, Any] | None = None, *, seed: int = 42):
        self.params = validate_model_params("hist_gradient_boosting", params)
        self.seed = seed
        self._pipeline: Pipeline | None = None

    def _build(self) -> Pipeline:
        preprocess = ColumnTransformer(
            [
                (
                    "categories",
                    OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                    CATEGORICAL_FEATURES,
                ),
                ("numeric", "passthrough", NUMERIC_FEATURES),
            ]
        )
        estimator = HistGradientBoostingRegressor(
            learning_rate=self.params["learning_rate"],
            max_iter=self.params["max_iter"],
            max_leaf_nodes=self.params["max_leaf_nodes"],
            l2_regularization=self.params["l2_regularization"],
            min_samples_leaf=self.params["min_samples_leaf"],
            random_state=self.seed,
        )
        return Pipeline([("preprocess", preprocess), ("estimator", estimator)])

    def fit(self, features: pd.DataFrame, target: pd.Series) -> GradientBoostingModel:
        self._pipeline = self._build()
        self._pipeline.fit(features, target)
        return self

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if self._pipeline is None:
            raise RuntimeError("model must be fitted before predict")
        return np.maximum(self._pipeline.predict(features), 0.0)


def build_estimator(model_key: str, params: dict[str, Any] | None = None, *, seed: int = 42):
    """Factory used by the worker and by tests."""

    if model_key == "seasonal_naive":
        resolved = validate_model_params(model_key, params)
        return SeasonalNaiveModel(season=int(resolved["season"]), seed=seed)
    if model_key == "hist_gradient_boosting":
        return GradientBoostingModel(params, seed=seed)
    raise ValueError(f"unknown model '{model_key}'")


def describe_estimator(model_key: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": model_key,
        "label": MODEL_LABELS[model_key],
        "description": MODEL_DESCRIPTIONS[model_key],
        "params": params,
    }
