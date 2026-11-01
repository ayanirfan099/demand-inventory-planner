# Forecasting methodology

This document is the contract between the forecasting code
(`packages/forecasting/src/forecastops_forecasting/`), the API that persists its output, and
the UI that explains it. If the code and this document disagree, the code is the bug.

**Scope statement.** Every metric shown in this product comes from a single chronological
holdout on one uploaded (or seeded, synthetic) dataset. It is decision support, not a
benchmark, and it says nothing about how the same model would behave on another retailer's
demand. The seeded demo dataset is deterministic and fictional.

---

## 1. Study protocol

```
validated demand
      │
      ▼
wide date × series matrix (continuous calendar, gaps = 0 demand, counted)
      │
      ├──▶ rolling-origin validation (folds ending BEFORE the holdout)
      │        └── selection signal: mean WAPE per model
      │
      ├──▶ chronological holdout (scored exactly once, never used to select)
      │
      └──▶ final forecast: refit on all observed data → horizon_days ahead
```

### 1.1 Rolling-origin validation (selection only)

For fold *i* of `validation_folds`, the forecast origin is

```
origin = holdout_start - 1 - horizon_days * (validation_folds - i)
```

so the last validation window ends strictly before the holdout begins. Each fold refits the
model from scratch on data up to `origin`, forecasts `horizon_days` ahead, and scores the
window. Folds whose origin would fall inside the minimum history are skipped (and the
response records what ran, so a silently skipped fold is visible).

`validation_folds = 0` is permitted for speed, and then the run says so in its limitations:
selection falls back to the holdout ordering, which is a weaker guarantee. The UI displays
the fold count and each fold's origin next to the metrics.

### 1.2 Chronological holdout (reporting only)

The holdout is the last `holdout_days` of the dataset. Each model is refit on everything
before it and asked to forecast the whole holdout window in one shot. The holdout is scored
once and is **not** an input to model selection, feature choice or hyper-parameters. This
split exists so the headline metrics are not the same numbers that chose the model.

### 1.3 Final forecast

The selected model is refit on **all** observed data and forecasts `horizon_days` into the
future. Those points are the ones an inventory plan consumes.

### 1.4 Forecast mode: fixed multi-step recursive

All reported forecasts are mode `fixed_multi_step_recursive`:

- one fit per origin;
- horizon steps produced in sequence;
- step 1 uses real lagged observations, step ≥ 2 uses the model's own earlier predictions
  as the lag/rolling inputs, so **error compounds with horizon**.

This is deliberately not the same as a one-step rolling evaluation (where every step is
scored with the truth behind it). One-step rolling numbers flatter a model; this product
does not report them as if they were plans. The API returns `forecast_mode` and a
human-readable `forecast_mode_label` with every run, and the run page repeats it.

---

## 2. Leakage rules

`packages/forecasting/src/forecastops_forecasting/features.py` builds features through two
entry points that share **one** definition:

| Path | When it runs | Input |
| --- | --- | --- |
| `build_training_frame` | training | wide matrix, vectors sliced up to the origin |
| `make_feature_row` | inference | a single series' history up to the day before the target |

Every demand-derived feature is shifted by at least one day:

| Feature | Definition | Why it cannot leak |
| --- | --- | --- |
| `lag_1` | `sales[d-1]` | strictly earlier |
| `lag_7` | `sales[d-7]` | strictly earlier |
| `lag_14` | `sales[d-14]` | strictly earlier |
| `rolling_mean_7` | mean of `sales[d-7 .. d-1]` (`shift(1)` then rolling) | window ends at `d-1` |
| `day_of_week`, `month`, `day_of_year` | derived from `d` | calendar only, no demand |
| `store`, `item` | one-hot identifiers | identity, not demand |

`MIN_HISTORY_DAYS = 15` (`max(LAGS) + 1`) is required before the first supervision row
exists, so a dataset shorter than `holdout_days + MIN_HISTORY_DAYS + 2` is rejected with
`insufficient_history` instead of being fudged.

Rebuilding a training row and an inference row for the same date and series produces the
same feature values; that equality is unit-tested
(`packages/forecasting/tests/test_features.py`).

---

## 3. Models

Both models consume the identical feature matrix — the only difference is the mapping, which
is what makes the comparison meaningful.

### 3.1 Seasonal naive baseline (mandatory)

- Key: `seasonal_naive`, label "Seasonal naive (lag-7 baseline)".
- Rule: `ŷ(t) = y(t - season)`, `season` default 7, allowed 1–14.
- No fitting. The study refuses to run without it (`baseline_required`), because a model
  without a reference cannot be judged.

### 3.2 Histogram gradient boosting (the documented ML model)

- Key: `hist_gradient_boosting`.
- `Pipeline(ColumnTransformer(OneHotEncoder for store/item, passthrough numeric),
  HistGradientBoostingRegressor)`.
- Hyper-parameters are bounded so an API caller cannot request an unbounded job:

| Parameter | Default | Allowed |
| --- | --- | --- |
| `learning_rate` | 0.08 | 0.01 – 0.30 |
| `max_iter` | 150 | 50 – 400 |
| `max_leaf_nodes` | 31 | 7 – 63 |
| `l2_regularization` | 1.0 | 0 – 10 |
| `min_samples_leaf` | 20 | 5 – 100 |

Unknown parameters are rejected, not ignored. Predictions are clipped at zero (demand
cannot be negative), and a non-finite prediction fails the job with `model_failure` rather
than writing a `NaN` into the plan.

### 3.3 Empirical bands

The run also reports 10th/90th residual quantiles per series computed from that model's own
holdout residuals, with a pooled fallback when a series has fewer than five residuals. These
are **descriptive empirical bands**, not calibrated prediction intervals, and both the API
(`band_label`) and the UI label them that way.

---

## 4. Metrics

All metrics live in `metrics.py` and are defined on the evaluation window only.

| Metric | Definition | Zero-demand behaviour |
| --- | --- | --- |
| MAE | mean(\|actual − forecast\|) | 0 when every actual and forecast is 0 — always defined |
| RMSE | sqrt(mean((actual − forecast)²)) | 0 in the same case — always defined |
| WAPE | Σ\|error\| / Σ\|actual\| | **`None`** when Σ\|actual\| = 0 (the ratio is undefined); never 0, never ∞ |
| MASE | MAE / in-sample lag-7 MAE of the **training** window | **`None`** when that scale is 0 (a flat series) or history is too short |
| Bias | mean(forecast − actual), signed | 0 is a real value; positive means over-forecasting |

`n` (evaluation points) is returned with every metric block so a ratio can always be
interpreted against its sample size.

### 4.1 Aggregates

The aggregate WAPE is `Σ|error| / Σ|actual|` pooled over series — not an unweighted mean of
per-series ratios, which would let tiny series dominate. MAE, RMSE and MASE are pooled
n-weighted the same way. Per-series rows are always returned alongside the aggregate, and
the UI shows both: a good average must not be able to hide a broken series.

### 4.2 Selection rule

Reported verbatim with every run:

> Lowest mean WAPE across rolling-origin validation folds (MAE as a tie-break when WAPE is
> undefined). Fold windows end before the chronological holdout, so the holdout never
> influences model choice.

`comparison.rows[].relative_wape_vs_baseline` is `wape / baseline_wape` — below 1.0 means
the model beat seasonal naive on the same holdout.

---

## 5. Reproducibility

- One `seed` per study; it is persisted with the job and echoed in the run payload.
- `Sync`-free: no randomness outside the estimator's `random_state`.
- Same input, same config, same seed → same forecast. The job's `input_version_id`,
  resolved config and model params are stored, so a run can be re-derived.
- Nothing is tuned on the holdout. Tuning happens by changing the config and re-running,
  which produces a *new* run with its own holdout; the old numbers are not overwritten.

---

## 6. Provenance: what was reused, adapted or rewritten

The predecessor study (a personal retail-forecasting notebook project) informed this
library. Nothing was copied blindly; where the old code was a notebook-shaped
one-step experiment, it was rewritten.

| Component | Decision | Note |
| --- | --- | --- |
| Upload/validation contract, rejection report, gap-fill accounting | **Rewritten** | The old notebooks trusted their inputs; this product must not. |
| Wide-matrix leakage-safe feature builder | **Adapted** | Same shift/rolling discipline, now shared by training and inference paths. |
| Metrics | **Extended** | Added bias, pooled aggregate WAPE, explicit `None` for undefined MASE/WAPE. |
| Rolling-origin validation | **New** | The predecessor selected on its test window. |
| Fixed multi-step recursive forecasting | **New** | The predecessor scored one-step rolling forecasts. |
| Deterministic synthetic generator | **New** | Needed a licence-clean, reproducible demo dataset. |
| Bounded model wrapper + parameter validation | **New** | A public API cannot accept unbounded training requests. |

---

## 7. Limitations (also returned by the API with every run)

1. Fixed multi-step recursive forecasts compound error with horizon.
2. Metrics describe this dataset and this split only; they are not a benchmark.
3. The lag-7 baseline is always included; a model that does not beat it should not be
   trusted for planning.
4. No promotions, prices, holidays, stockouts or censored demand are modelled. Demand lost
   to a stockout cannot be recovered from sales data.
5. Gaps inside an observed series are treated as zero demand and counted; a series that was
   simply not carried yet will drag its own metrics.
6. Empirical bands are not calibrated intervals.
