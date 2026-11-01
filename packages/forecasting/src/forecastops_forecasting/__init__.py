"""ForecastOps forecasting core.

Public surface:

* :mod:`schema` — canonical demand frame validation, gap filling and quality reporting.
* :mod:`features` — leakage-aware lag / rolling / calendar feature construction.
* :mod:`metrics` — MAE, RMSE, WAPE, MASE with explicit zero-demand behaviour.
* :mod:`models` — seasonal-naive baseline and a bounded gradient-boosting model.
* :mod:`study` — chronological holdout, rolling-origin validation and the full run bundle.
* :mod:`generator` — deterministic synthetic demo data.

Nothing in this package claims real-world forecasting performance. All metrics produced
from the bundled synthetic generator are labelled as synthetic smoke results.
"""

from .features import (
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    build_training_frame,
    make_feature_row,
)
from .generator import generate_demo_demand
from .metrics import forecast_metrics, mase_scale, seasonal_naive_scale
from .models import MODEL_KEYS, build_estimator
from .schema import (
    REQUIRED_COLUMNS,
    DemandValidationError,
    normalize_demand,
    read_demand_csv,
)
from .study import (
    STUDY_MODE_HOLDOUT,
    STUDY_MODE_ROLLING_ORIGIN,
    StudyConfig,
    StudyError,
    run_forecast_study,
)

__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURES",
    "MODEL_KEYS",
    "NUMERIC_FEATURES",
    "REQUIRED_COLUMNS",
    "STUDY_MODE_HOLDOUT",
    "STUDY_MODE_ROLLING_ORIGIN",
    "DemandValidationError",
    "StudyConfig",
    "StudyError",
    "build_estimator",
    "build_training_frame",
    "forecast_metrics",
    "generate_demo_demand",
    "make_feature_row",
    "mase_scale",
    "normalize_demand",
    "read_demand_csv",
    "run_forecast_study",
    "seasonal_naive_scale",
]
__version__ = "0.1.0"
