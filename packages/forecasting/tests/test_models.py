"""Model parameter bounds and the baseline's arithmetic."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from forecastops_forecasting.models import (
    MODEL_KEYS,
    SeasonalNaiveModel,
    build_estimator,
    validate_model_params,
)


def test_baseline_predicts_lag_seven_clipped_at_zero():
    features = pd.DataFrame({"lag_7": [5.0, -2.0, 11.5]})
    predictions = SeasonalNaiveModel().predict(features)
    assert predictions.tolist() == [5.0, 0.0, 11.5]


def test_baseline_requires_the_lag_column():
    with pytest.raises(ValueError):
        SeasonalNaiveModel().predict(pd.DataFrame({"lag_1": [1.0]}))


def test_unknown_model_key_is_rejected():
    with pytest.raises(ValueError):
        build_estimator("random_forest")


def test_hyper_parameters_are_bounded():
    with pytest.raises(ValueError):
        validate_model_params("hist_gradient_boosting", {"max_iter": 10_000})
    with pytest.raises(ValueError):
        validate_model_params("hist_gradient_boosting", {"max_iter": 10})
    with pytest.raises(ValueError):
        validate_model_params("hist_gradient_boosting", {"not_a_parameter": 1})
    with pytest.raises(ValueError):
        validate_model_params("hist_gradient_boosting", {"max_iter": "many"})


def test_defaults_are_materialised():
    params = validate_model_params("hist_gradient_boosting", None)
    assert params["max_iter"] == 150
    assert set(params) >= {"learning_rate", "max_leaf_nodes", "l2_regularization", "min_samples_leaf"}


def test_model_keys_include_the_baseline():
    assert "seasonal_naive" in MODEL_KEYS


def test_gradient_boosting_is_deterministic_for_a_given_seed():
    rng = np.random.default_rng(0)
    features = pd.DataFrame(
        {
            "store": ["s1"] * 60 + ["s2"] * 60,
            "item": ["i1"] * 120,
            "lag_1": rng.uniform(0, 20, 120),
            "lag_7": rng.uniform(0, 20, 120),
            "lag_14": rng.uniform(0, 20, 120),
            "rolling_mean_7": rng.uniform(0, 20, 120),
            "day_of_week": np.tile(np.arange(7), 18)[:120],
            "month": 1,
            "day_of_year": np.arange(120),
        }
    )
    target = features["lag_1"] + rng.normal(0, 1, 120)
    first = build_estimator("hist_gradient_boosting", {"max_iter": 60}, seed=7).fit(features, target)
    second = build_estimator("hist_gradient_boosting", {"max_iter": 60}, seed=7).fit(features, target)
    assert np.allclose(first.predict(features), second.predict(features))
