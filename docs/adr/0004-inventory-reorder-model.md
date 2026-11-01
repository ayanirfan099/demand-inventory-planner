# 0004 — Periodic-review reorder point with an empirical residual sigma

- **Status:** accepted
- **Date:** 2026-10-30

## Context

The product must suggest order quantities without inventing supplier facts. It has: the
forecast, holdout residuals, and whatever the planner enters (lead time, review period,
service level, on-hand, MOQ, pack size). It does **not** have lead-time history, unit costs,
shelf life or supplier constraints.

## Decision

One documented periodic-review policy (`services/api/app/services/inventory.py`):

```
W                 = lead_time_days + review_period_days
forecast_demand   = Σ forecasts over W   (mean daily rate extrapolated beyond the horizon)
sigma_d           = sample std (ddof=1) of the model's holdout residuals for the series
safety_stock      = z(service_level) · sigma_d · sqrt(W)
reorder_point     = forecast_demand + safety_stock
projected_on_hand = on_hand − forecast_demand
shortage          = max(0, reorder_point − on_hand)
suggested_qty     = ceil(max(shortage, MOQ) / pack_size) · pack_size   (0 if no shortage)
```

Every assumption is returned with the suggestion and shown in the UI: `W`, the extrapolated
day count, `sigma_d` and where it came from, the z value, and a plain statement of what is
*not* modelled. Nothing is ordered automatically — the artefact is a suggestion a planner can
override, and each status change writes an audit event.

## Consequences

- `sigma_d = 0` for a series with fewer than two residuals, so safety stock collapses to 0
  rather than being fabricated; `extrapolated_days > 0` is visible, so a short horizon cannot
  quietly understate demand.
- Lead-time variability is ignored: `sigma_d` is demand dispersion only. Any real lead-time
  distribution would need supplier data we refuse to invent.
- Because everything is recomputed per policy change and stored, a suggestion is auditable
  against the run and policy it came from.

## Rejected

- **Defaulting supplier costs or lead times.** Fabrication that looks like insight.
- **Continuous-review (s, S) or multi-echelon models.** Not supported by the available data,
  and the extra parameters would be pure invention.
- **Ordering automatically.** The product is decision support.
