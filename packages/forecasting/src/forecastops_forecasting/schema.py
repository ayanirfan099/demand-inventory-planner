"""Canonical demand frame: validation, normalisation and quality reporting.

The ingestion contract is deliberately small so that a reviewer can reason about it:

    date,store,item,sales[,on_hand]

``sales`` is daily units sold for the (store, item) pair on ``date``. When several
rows exist for the same key the quantities are summed (transaction-style exports).
Missing calendar days *inside* an observed series are treated as zero-demand days;
the count of such days is always reported so the assumption is visible downstream.

This module never executes uploaded content: it only parses text into a dataframe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls
from io import StringIO
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("date", "store", "item", "sales")
OPTIONAL_COLUMNS = ("on_hand",)
COLUMN_ALIASES = {
    "demand": "sales",
    "quantity": "sales",
    "qty": "sales",
    "units": "sales",
    "sku": "item",
    "product": "item",
    "location": "store",
    "shop": "store",
}

# Bounds enforced by both the API and this module. Kept conservative so that a single
# forecast job can never exhaust worker memory.
MAX_ROWS = 200_000
MAX_SERIES = 200
MAX_HORIZON_DAYS = 90
MIN_HISTORY_DAYS = 28


class DemandValidationError(ValueError):
    """Raised when an uploaded demand frame violates the data contract."""

    def __init__(self, message: str, *, code: str = "invalid_dataset", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class NormalizationReport:
    """Machine-readable summary of what ingestion did to the raw frame."""

    row_count_in: int = 0
    row_count_out: int = 0
    series_count: int = 0
    date_min: str | None = None
    date_max: str | None = None
    duplicate_rows_summed: int = 0
    zero_demand_days: int = 0
    missing_dates_filled: int = 0
    on_hand_present: bool = False
    warnings: list[str] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    rejected_rows: int = 0
    rejected_examples: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_count_in": self.row_count_in,
            "row_count_out": self.row_count_out,
            "series_count": self.series_count,
            "date_min": self.date_min,
            "date_max": self.date_max,
            "duplicate_rows_summed": self.duplicate_rows_summed,
            "zero_demand_days": self.zero_demand_days,
            "missing_dates_filled": self.missing_dates_filled,
            "on_hand_present": self.on_hand_present,
            "warnings": list(self.warnings),
            "ignored_columns": list(self.ignored_columns),
            "rejected_rows": self.rejected_rows,
            "rejected_examples": list(self.rejected_examples),
        }


def _canonical_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for column in frame.columns:
        key = str(column).strip().lower().replace(" ", "_").replace("-", "_")
        renamed[column] = COLUMN_ALIASES.get(key, key)
    out = frame.rename(columns=renamed)
    ignored = [c for c in out.columns if c not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS]
    out = out.drop(columns=ignored, errors="ignore")
    return out


def normalize_demand(
    frame: pd.DataFrame,
    *,
    max_rows: int = MAX_ROWS,
    max_series: int = MAX_SERIES,
    fill_missing_dates: bool = True,
) -> tuple[pd.DataFrame, NormalizationReport]:
    """Validate and canonicalise a raw demand frame.

    Returns ``(clean_frame, report)`` where ``clean_frame`` has exactly the columns
    ``date, store, item, sales`` (plus ``on_hand`` when supplied by every series) and one
    row per series/day, sorted by series then date.
    """

    if not isinstance(frame, pd.DataFrame):
        raise DemandValidationError("Expected a tabular frame.")
    if frame.empty:
        raise DemandValidationError("The file contains no data rows.", code="empty_dataset")

    report = NormalizationReport(row_count_in=len(frame))
    if len(frame) > max_rows:
        raise DemandValidationError(
            f"Dataset has {len(frame):,} rows which exceeds the {max_rows:,} row limit.",
            code="too_many_rows",
        )

    original_columns = list(frame.columns)
    out = _canonical_columns(frame)
    report.ignored_columns = [
        str(c) for c in original_columns if str(c).strip().lower().replace(" ", "_") not in
        REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    ]
    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise DemandValidationError(
            "Missing required column(s): " + ", ".join(missing) + ". Expected date, store, item, sales.",
            code="missing_columns",
            details={"missing": missing, "found": [str(c) for c in original_columns]},
        )

    on_hand_present = "on_hand" in out.columns

    # Coerce with explicit null detection so bad rows can be counted and rejected
    # rather than silently dropping or crashing inside the model.
    out = out.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=False)
    out["sales"] = pd.to_numeric(out["sales"], errors="coerce")
    out["store"] = out["store"].astype("string").str.strip()
    out["item"] = out["item"].astype("string").str.strip()
    if on_hand_present:
        out["on_hand"] = pd.to_numeric(out["on_hand"], errors="coerce")

    invalid_date = out["date"].isna()
    invalid_sales = out["sales"].isna()
    negative_sales = out["sales"].notna() & (out["sales"] < 0)
    empty_key = out["store"].isna() | out["item"].isna() | (out["store"].str.len() == 0) | (out["item"].str.len() == 0)
    bad_mask = invalid_date | invalid_sales | negative_sales | empty_key
    report.rejected_rows = int(bad_mask.sum())
    if report.rejected_rows:
        bad = out[bad_mask]
        examples = []
        for index, _row in bad.head(5).iterrows():
            reason = (
                "invalid_date" if invalid_date.loc[index]
                else "negative_sales" if negative_sales.loc[index]
                else "missing_store_or_item" if empty_key.loc[index]
                else "invalid_sales"
            )
            examples.append({"row_number": int(index) + 2, "reason": reason})
        report.rejected_examples = examples
        out = out[~bad_mask]
        if out.empty:
            raise DemandValidationError(
                "No valid rows remained after validation.",
                code="no_valid_rows",
                details={"rejected_examples": examples},
            )

    if negative_sales.any():
        # Returns are only modelled when explicitly enabled; this build does not model
        # them, so negative demand is a hard contract violation for the affected rows.
        report.warnings.append(
            f"{int(negative_sales.sum())} row(s) had negative sales and were rejected. "
            "Returns are not modelled in this version."
        )
    if invalid_date.any() or invalid_sales.any():
        report.warnings.append(
            f"{int((invalid_date | invalid_sales).sum())} row(s) had unparseable dates or sales and were rejected."
        )

    out["date"] = out["date"].dt.normalize()
    out = out.dropna(subset=["store", "item", "sales", "date"])

    # Normalise to calendar dates, dropping any timezone offset that survived parsing.
    date_min = out["date"].min().date()
    date_max = out["date"].max().date()
    full_index = pd.date_range(date_min, date_max, freq="D", name="date")

    grouped = out.groupby(["store", "item", "date"], as_index=False, sort=True)
    aggregated = grouped.agg(sales=("sales", "sum"), **({"on_hand": ("on_hand", "last")} if on_hand_present else {}))
    report.duplicate_rows_summed = int(len(out) - len(aggregated))

    series_pairs = aggregated[["store", "item"]].drop_duplicates()
    report.series_count = len(series_pairs)
    if report.series_count > max_series:
        raise DemandValidationError(
            f"Dataset defines {report.series_count:,} store/item series which exceeds the {max_series:,} limit.",
            code="too_many_series",
        )

    if fill_missing_dates:
        frames = []
        for (store, item), chunk in aggregated.groupby(["store", "item"], sort=False):
            series = chunk.set_index("date").reindex(full_index)
            missing_days = int(series["sales"].isna().sum())
            if missing_days:
                report.missing_dates_filled += missing_days
            series["sales"] = series["sales"].fillna(0.0)
            series["store"] = store
            series["item"] = item
            if on_hand_present:
                # On-hand is a snapshot, not a flow: forward-fill then back-fill.
                series["on_hand"] = chunk.set_index("date")["on_hand"].reindex(full_index).ffill().bfill()
            frames.append(series.reset_index())
        aggregated = pd.concat(frames, ignore_index=True)
    else:
        aggregated["store"] = aggregated["store"].astype(str)
        aggregated["item"] = aggregated["item"].astype(str)
        report.missing_dates_filled = 0

    if report.missing_dates_filled:
        report.warnings.append(
            f"{report.missing_dates_filled:,} calendar day(s) with no recorded row were filled with zero demand. "
            "This assumes no sales rather than lost data."
        )
    if report.duplicate_rows_summed:
        report.warnings.append(
            f"{report.duplicate_rows_summed:,} duplicate series/date row(s) were summed into daily demand."
        )

    aggregated["store"] = aggregated["store"].astype(str)
    aggregated["item"] = aggregated["item"].astype(str)
    aggregated["sales"] = aggregated["sales"].astype(float)
    aggregated = aggregated.sort_values(["store", "item", "date"]).reset_index(drop=True)

    observed_days = int(aggregated["date"].nunique())
    if observed_days < MIN_HISTORY_DAYS:
        raise DemandValidationError(
            f"Dataset spans {observed_days} day(s); at least {MIN_HISTORY_DAYS} days of history are required.",
            code="insufficient_history",
        )

    report.row_count_out = len(aggregated)
    report.date_min = date_min.isoformat()
    report.date_max = date_max.isoformat()
    report.zero_demand_days = int((aggregated["sales"] == 0).sum())
    report.on_hand_present = on_hand_present
    zero_share = report.zero_demand_days / max(report.row_count_out, 1)
    if zero_share > 0.4:
        report.warnings.append(
            f"{zero_share:.0%} of series-days have zero demand, which makes WAPE and MASE unstable. "
            "Review the weak-series table before trusting aggregate metrics."
        )

    return aggregated, report


def read_demand_csv(
    raw: bytes | str,
    *,
    encoding: str = "utf-8-sig",
    max_rows: int = MAX_ROWS,
) -> tuple[pd.DataFrame, NormalizationReport]:
    """Parse a CSV upload into a clean, normalised demand frame.

    Parsing is bounded and uses pandas' C parser only; no uploaded content is executed.
    """

    if isinstance(raw, bytes):
        if len(raw) == 0:
            raise DemandValidationError("The uploaded file is empty.", code="empty_dataset")
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:  # pragma: no cover - depends on upload bytes
            raise DemandValidationError("The file is not valid UTF-8 text.", code="encoding_error") from exc
    else:
        text = raw

    sample = text[:8192]
    try:
        separator = ";" if sample.count(";") > sample.count(",") else ","
        frame = pd.read_csv(
            StringIO(text),
            sep=separator,
            nrows=max_rows + 1,  # read one extra row so the row limit is enforced here too
            skipinitialspace=True,
        )
    except pd.errors.EmptyDataError as exc:
        raise DemandValidationError("The file contains no parseable rows.", code="empty_dataset") from exc
    except (pd.errors.ParserError, ValueError) as exc:
        raise DemandValidationError("The file could not be parsed as CSV.", code="parse_error") from exc

    return normalize_demand(frame, max_rows=max_rows)


def frame_to_records(frame: pd.DataFrame, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Serialise a clean frame for preview responses (dates as ISO strings)."""

    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    if limit is not None:
        out = out.head(limit)
    return out.replace({np.nan: None}).to_dict(orient="records")


def iso(value: Any) -> str | None:
    """Convert a pandas timestamp/date to an ISO date string."""

    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    timestamp = pd.Timestamp(value)
    return timestamp.date().isoformat()


def to_date(value: Any) -> date_cls:
    return pd.Timestamp(value).date()
