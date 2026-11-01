"""Data-contract tests for the demand frame."""

from __future__ import annotations

import pandas as pd
import pytest
from forecastops_forecasting.schema import (
    DemandValidationError,
    normalize_demand,
    read_demand_csv,
)


def _frame(rows):
    return pd.DataFrame(rows, columns=["date", "store", "item", "sales"])


def _contiguous(store="s1", item="i1", days=30, start="2024-01-01", value=10):
    dates = pd.date_range(start, periods=days, freq="D")
    return _frame([{"date": d.date().isoformat(), "store": store, "item": item, "sales": value} for d in dates])


def test_duplicate_rows_are_summed_and_reported():
    base = _contiguous(days=30)
    duplicate = pd.DataFrame(
        [
            {"date": "2024-01-05", "store": "s1", "item": "i1", "sales": 3},
            {"date": "2024-01-05", "store": "s1", "item": "i1", "sales": 4},
        ]
    )
    clean, report = normalize_demand(pd.concat([base, duplicate], ignore_index=True))
    assert report.duplicate_rows_summed == 2
    row = clean[(clean["date"] == pd.Timestamp("2024-01-05"))].iloc[0]
    assert row["sales"] == 17  # 10 recorded + 3 + 4
    assert any("duplicate" in warning for warning in report.warnings)


def test_negative_sales_rows_are_rejected_without_failing_the_upload():
    frame = _contiguous(days=30)
    frame.loc[0, "sales"] = -5
    clean, report = normalize_demand(frame)
    assert report.rejected_rows == 1
    assert report.rejected_examples[0]["reason"] == "negative_sales"
    assert (clean["sales"] >= 0).all()
    assert any("negative" in warning.lower() for warning in report.warnings)


def test_missing_calendar_days_are_filled_with_zero_and_counted():
    frame = _contiguous(days=30)
    frame = frame[~frame["date"].isin(["2024-01-10", "2024-01-11"])]
    clean, report = normalize_demand(frame)
    assert report.missing_dates_filled == 2
    filled = clean[clean["date"].isin([pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-11")])]
    assert (filled["sales"] == 0).all()
    assert len(clean) == 30


def test_unparseable_rows_are_rejected_and_explained():
    frame = _contiguous(days=30)
    frame.loc[3, "date"] = "not-a-date"
    _, report = normalize_demand(frame)
    assert report.rejected_rows == 1
    assert report.rejected_examples[0]["reason"] == "invalid_date"


def test_missing_required_column_raises_contract_error():
    frame = _contiguous(days=30).drop(columns=["sales"])
    with pytest.raises(DemandValidationError) as excinfo:
        normalize_demand(frame)
    assert excinfo.value.code == "missing_columns"


def test_column_aliases_and_ignored_columns_are_supported():
    frame = _contiguous(days=30).rename(columns={"sales": "demand", "store": "location"})
    frame["notes"] = "ignored"
    clean, report = normalize_demand(frame)
    assert list(clean.columns) == ["date", "store", "item", "sales"]
    assert "notes" in report.ignored_columns


def test_row_limit_is_enforced():
    frame = _contiguous(days=30)
    with pytest.raises(DemandValidationError) as excinfo:
        normalize_demand(frame, max_rows=10)
    assert excinfo.value.code == "too_many_rows"


def test_series_limit_is_enforced():
    frames = [_contiguous(store=f"s{index}", days=30) for index in range(3)]
    with pytest.raises(DemandValidationError) as excinfo:
        normalize_demand(pd.concat(frames, ignore_index=True), max_series=2)
    assert excinfo.value.code == "too_many_series"


def test_short_history_is_rejected():
    with pytest.raises(DemandValidationError) as excinfo:
        normalize_demand(_contiguous(days=10))
    assert excinfo.value.code == "insufficient_history"


def test_csv_parsing_handles_bom_and_semicolons():
    text = "\ufeffdate;store;item;sales\n"
    for offset in range(30):
        text += f"{pd.Timestamp('2024-01-01') + pd.Timedelta(days=offset):%Y-%m-%d};s1;i1;4\n"
    clean, report = read_demand_csv(text.encode("utf-8"))
    assert report.series_count == 1
    assert clean["sales"].sum() == 120


def test_csv_size_and_parse_errors_are_typed():
    with pytest.raises(DemandValidationError) as excinfo:
        read_demand_csv(b"")
    assert excinfo.value.code == "empty_dataset"
    with pytest.raises(DemandValidationError) as excinfo:
        read_demand_csv(b"\xff\xfe\x00bad")
    assert excinfo.value.code in {"encoding_error", "parse_error", "empty_dataset"}


def test_on_hand_is_carried_through_when_present():
    frame = _contiguous(days=30)
    frame["on_hand"] = 42
    clean, report = normalize_demand(frame)
    assert report.on_hand_present is True
    assert set(clean["on_hand"].unique()) == {42}
