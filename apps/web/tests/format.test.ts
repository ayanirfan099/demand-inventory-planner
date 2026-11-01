import { describe, expect, it } from "vitest";

import {
  METRIC_DEFINITIONS,
  bytesToSize,
  formatDate,
  formatNumber,
  formatPercent,
  relativeToBaseline,
} from "@/lib/format";

describe("formatting helpers", () => {
  it("renders undefined ratios as n/a rather than zero", () => {
    // WAPE is undefined when total actual demand is zero; the UI must not imply 0% error.
    expect(formatPercent(null)).toBe("n/a");
    expect(formatPercent(undefined)).toBe("n/a");
    expect(formatNumber(Number.NaN)).toBe("n/a");
  });

  it("formats percentages and numbers deterministically", () => {
    expect(formatPercent(0.1875)).toBe("18.8%");
    expect(formatPercent(0.5, 0)).toBe("50%");
    expect(formatNumber(1234.567)).toBe("1,234.6");
    expect(formatNumber(0)).toBe("0");
  });

  it("keeps dates stable in UTC so a run window never shifts a day", () => {
    expect(formatDate("2025-01-01")).toBe("01 Jan 2025");
    expect(formatDate(null)).toBe("—");
  });

  it("describes improvement against the baseline with the right sign", () => {
    expect(relativeToBaseline(0.8)).toBe("−20.0% vs baseline");
    expect(relativeToBaseline(1.2)).toBe("+20.0% vs baseline");
    expect(relativeToBaseline(null)).toBe("n/a");
  });

  it("describes byte sizes", () => {
    expect(bytesToSize(512)).toBe("512 B");
    expect(bytesToSize(2048)).toBe("2.0 KB");
    expect(bytesToSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });

  it("defines every metric shown in the UI", () => {
    for (const key of ["mae", "rmse", "wape", "mase", "bias"]) {
      expect(METRIC_DEFINITIONS[key].definition.length).toBeGreaterThan(20);
    }
  });
});
