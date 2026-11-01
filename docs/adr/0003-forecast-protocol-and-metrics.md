# 0003 — Rolling-origin selection, untouched holdout, fixed multi-step forecasts

- **Status:** accepted
- **Date:** 2026-10-30

## Context

The predecessor project scored one-step rolling forecasts and selected a model on the same
window it reported. Both inflate results: one-step rolling forecasts assume the truth is
known behind every step, and selection-on-test makes the reported number an optimistically
biased estimate. A planning tool that quietly does this is worse than no tool.

## Decision

1. **Rolling-origin validation for selection only.** Folds end strictly before the holdout
   (`origin = holdout_start - 1 - horizon_days * (folds - i)`). Selection metric: mean WAPE,
   MAE as tie-break.
2. **Chronological holdout, scored once, never used for selection.** All headline metrics
   come from it.
3. **Final forecast refit on all data** for `horizon_days`, mode
   `fixed_multi_step_recursive` — the model consumes its own predictions inside the horizon.
4. **Lag-7 seasonal naive is mandatory** so every ML number has a reference on the same
   split.
5. **Leakage-free features only**: `lag_1/7/14`, `rolling_mean_7` shifted so the window ends
   at `d-1`, plus calendar terms and store/item indicators.
6. **Honest undefineds**: WAPE is `None` when total actual demand is zero; MASE is `None`
   when the in-sample scale is zero. Undefined is never rendered as 0.
7. **Aggregates pool numerators/denominators**; per-series metrics are always returned so an
   average cannot hide a broken series.

## Consequences

- Reported metrics are lower than one-step rolling numbers would be, and that is the point.
  The UI states the mode next to the numbers.
- Some datasets are rejected (`insufficient_history`) rather than silently shortened.
- Running with `validation_folds = 0` is allowed for speed but recorded as a limitation.
- Bands derived from holdout residuals are labelled empirical, not prediction intervals.

## Rejected

- **Selecting on the holdout.** Convenient and wrong.
- **Reporting only one-step rolling metrics.** Flattering and misleading for planning.
- **A deep learning model.** Unjustifiable at this data scale and far harder to bound.
- **AutoML / large hyper-parameter sweeps.** Not bounded, not reproducible in 300 s, and
  would invite tuning on the test range.
