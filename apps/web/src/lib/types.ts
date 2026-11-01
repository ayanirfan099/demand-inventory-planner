/** Types mirror the serialisers in services/api/app/serializers.py. */

export type Role = "owner" | "analyst" | "viewer";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface OrgRef {
  id: number;
  name: string;
  slug: string;
}

export interface SessionResponse {
  user: { id: number; email: string; display_name: string; is_demo: boolean };
  organizations: (OrgRef & { role: Role; membership_id: number })[];
  active_org: OrgRef | null;
  role: Role | null;
  session: { expires_at: string };
}

export interface QualityReport {
  row_count_in: number;
  row_count_out: number;
  series_count: number;
  date_min: string | null;
  date_max: string | null;
  duplicate_rows_summed: number;
  zero_demand_days: number;
  missing_dates_filled: number;
  on_hand_present: boolean;
  warnings: string[];
  ignored_columns: string[];
  rejected_rows: number;
  rejected_examples: { row_number: number; reason: string }[];
  synthetic?: boolean;
  notice?: string;
}

export interface DatasetVersion {
  id: number;
  version: number;
  fingerprint: string;
  fingerprint_short: string;
  row_count: number;
  series_count: number;
  date_min: string;
  date_max: string;
  byte_size: number;
  created_at: string;
  quality: QualityReport;
}

export interface DatasetSummary {
  id: number;
  name: string;
  description: string | null;
  source: string;
  original_filename: string | null;
  created_at: string;
  current_version: DatasetVersion | null;
}

export interface SeriesRow {
  id: number;
  store: string;
  item: string;
  on_hand: number | null;
  on_hand_updated_at: string | null;
}

export interface DatasetDetail {
  dataset: DatasetSummary;
  versions: DatasetVersion[];
  series: SeriesRow[];
}

export interface Job {
  id: number;
  dataset_id: number;
  dataset_version_id: number;
  status: JobStatus;
  stage: string | null;
  progress: number;
  horizon_days: number;
  holdout_days: number;
  validation_folds: number;
  seed: number;
  model_keys: string[];
  model_params: Record<string, Record<string, number>>;
  attempt: number;
  parent_job_id: number | null;
  failure_code: string | null;
  failure_message: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
}

export interface Metrics {
  mae?: number | null;
  rmse?: number | null;
  wape?: number | null;
  mase?: number | null;
  bias?: number | null;
}

export interface RunSummary {
  id: number;
  job_id: number;
  model_key: string;
  label: string;
  is_selected: boolean;
  forecast_mode: string;
  horizon_days: number;
  train_start: string | null;
  train_end: string | null;
  test_start: string | null;
  test_end: string | null;
  metrics: Metrics;
  created_at: string;
  job_status?: JobStatus;
}

export interface RunDetail extends RunSummary {
  forecast_mode_label: string;
  model_config: { params: Record<string, number>; seed: number; requires_fit: boolean };
  seed: number;
  dataset_version_id: number;
  validation_folds: { origin: string; test_start: string | null; test_end: string; metrics: Metrics }[];
  limitations: string[];
}

export interface RunDetailResponse {
  run: RunDetail;
  job: {
    id: number;
    status: JobStatus;
    horizon_days: number;
    holdout_days: number;
    validation_folds: number;
    seed: number;
    created_at: string;
  };
  dataset: {
    id: number | null;
    name: string | null;
    source: string | null;
    version: number | null;
    fingerprint: string | null;
    date_min: string | null;
    date_max: string | null;
    quality: QualityReport;
  };
  series: SeriesRow[];
  per_series_metrics: (Metrics & { series_id: number; store: string; item: string; on_hand: number | null })[];
  weak_series: (Metrics & { series_id: number; store: string; item: string; on_hand: number | null })[];
  selection_rule: string;
  notices: string[];
}

export interface Point {
  date: string;
  horizon_step: number;
  kind: "forecast" | "holdout";
  forecast: number;
  actual: number | null;
  lower: number | null;
  upper: number | null;
  series_id: number;
  store: string;
  item: string;
}

export interface PointsResponse {
  run: { id: number; model_key: string; label: string; kind: string };
  points: Point[];
  total_by_date: { date: string; forecast_total: number }[];
  truncated: boolean;
}

export interface ComparisonRow {
  run_id: number;
  model_key: string;
  label: string;
  is_selected: boolean;
  metrics: Metrics;
  relative_wape_vs_baseline: number | null;
}

export interface ResidualsResponse {
  residuals: {
    date: string;
    series_id: number;
    store: string | null;
    item: string | null;
    actual: number;
    forecast: number;
    error: number;
    abs_error: number;
  }[];
  summary: {
    mean_error: number;
    mean_abs_error: number;
    over_forecast_share: number;
    bins: { lower: number; upper: number; count: number }[];
  };
}

export interface InventoryPolicy {
  id: number;
  dataset_id: number;
  name: string;
  lead_time_days: number;
  review_period_days: number;
  planning_window_days: number;
  service_level: number;
  min_order_qty: number;
  pack_size: number;
  notes: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Suggestion {
  id: number;
  policy_id: number;
  policy_name?: string;
  run_id: number;
  status: string;
  series_id: number;
  store: string | null;
  item: string | null;
  horizon_days: number;
  on_hand: number;
  forecast_demand: number;
  safety_stock: number;
  reorder_point: number;
  target_level: number;
  projected_on_hand: number;
  shortage: number;
  suggested_qty_raw: number;
  suggested_qty: number;
  assumptions: {
    formula: string;
    planning_window_days: number;
    lead_time_days: number;
    review_period_days: number;
    service_level: number;
    service_factor_z: number;
    residual_sigma_daily: number;
    forecast_run_id: number;
    model: string;
    on_hand_source: string;
    extrapolated_days_beyond_horizon: number;
    min_order_qty: number;
    pack_size: number;
    not_modelled: string[];
    service_level_is_not_a_guarantee: boolean;
  };
  created_at: string;
}

export interface AlertRow {
  id: number;
  kind: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  status: string;
  dataset_id: number | null;
  job_id: number | null;
  run_id: number | null;
  series_id: number | null;
  created_at: string;
  acknowledged_at: string | null;
}

export interface AlertsResponse {
  alerts: AlertRow[];
  counts: Record<string, number>;
  thresholds: { high_error_wape: number };
}

export interface AuditRow {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor_user_id: number | null;
  payload: Record<string, unknown>;
  request_id: string | null;
  created_at: string;
}

export interface PreviewResponse {
  preview_id: string;
  valid: boolean;
  quality: QualityReport;
  fingerprint: string;
  columns: string[];
  sample_rows: Record<string, string | number | null>[];
  series_preview: { store: string; item: string; days: number; total: number; mean: number; zero_days: number }[];
  series_total: number;
  limits: {
    max_rows: number;
    max_series: number;
    max_bytes: number;
    required_columns: string[];
    optional_columns: string[];
  };
  policy: Record<string, string>;
  original_filename: string;
}
