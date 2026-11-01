/** Display helpers. Numbers stay honest: undefined ratios render as "n/a", never 0. */

// A fixed locale keeps numbers and dates identical between the server snapshot, the
// browser and the test suite (the UI itself is English-only).
const LOCALE = "en-GB";

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toLocaleString(LOCALE, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function formatUnits(value: number | null | undefined): string {
  return formatNumber(value, 0);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(LOCALE, { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(LOCALE, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function relativeToBaseline(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  const improvement = (1 - value) * 100;
  const sign = improvement >= 0 ? "−" : "+";
  return `${sign}${Math.abs(improvement).toFixed(1)}% vs baseline`;
}

export function bytesToSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const METRIC_DEFINITIONS: Record<string, { label: string; definition: string }> = {
  mae: {
    label: "MAE",
    definition: "Mean absolute error in units of demand. Easy to read, but does not distinguish small and large series.",
  },
  rmse: {
    label: "RMSE",
    definition: "Root mean squared error. Penalises large misses more than MAE; same units as demand.",
  },
  wape: {
    label: "WAPE",
    definition:
      "Weighted absolute percentage error: total absolute error ÷ total actual demand. Comparable across series; undefined (n/a) when the actual demand in the window is zero.",
  },
  mase: {
    label: "MASE",
    definition:
      "MAE divided by the seasonal-naive (lag-7) error measured on the training window. Below 1 means better than the naive seasonal benchmark on that scale; n/a when the series is perfectly flat.",
  },
  bias: {
    label: "Bias",
    definition: "Mean(forecast − actual). Positive means systematic over-forecasting, negative means under-forecasting.",
  },
};

export const HORIZON_NOTICE =
  "Forecasts are fixed multi-step recursive: day 1 uses real history, later days consume the model's own predictions, so uncertainty grows with the horizon.";
