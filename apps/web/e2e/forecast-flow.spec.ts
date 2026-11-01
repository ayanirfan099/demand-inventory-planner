import { expect, test } from "@playwright/test";

import { demoCsv, signIn } from "./helpers";

test.describe("forecast workflow", () => {
  test("login → upload CSV → run forecast → inspect charts → reorder suggestions → export", async ({ page }) => {
    await signIn(page);

    // --- Upload + validate -----------------------------------------------------------
    await page.goto("/upload");
    await expect(page.getByRole("heading", { name: /import demand data/i })).toBeVisible();

    await page.getByLabel("Choose a CSV file").setInputFiles({
      name: "e2e-demand.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(demoCsv(), "utf-8"),
    });

    await expect(page.getByRole("heading", { name: /review the validation report/i })).toBeVisible();
    // The validator must report series count and accepted rows before anything is saved.
    // The KPI renders the count and the hint in sibling elements, so assert on the card.
    const seriesKpi = page.locator(".kpi").filter({ hasText: "store × item combinations" });
    await expect(seriesKpi).toBeVisible();
    await expect(seriesKpi.locator(".kpi-value")).toHaveText("4");
    await expect(page.getByText(/no data-quality warnings/i)).toBeVisible();

    await page.locator("#dataset-name").fill("E2E demand");
    await page.getByRole("button", { name: /confirm import/i }).click();
    await expect(page.getByText(/import complete/i)).toBeVisible();

    // --- Run a forecast -------------------------------------------------------------
    await page.goto("/forecasts");
    await page.getByLabel("Dataset", { exact: true }).selectOption({ label: "E2E demand (v1)" });
    await page.getByLabel(/forecast horizon/i).fill("10");
    await page.getByLabel(/holdout window/i).fill("14");
    await page.getByRole("button", { name: /start forecast/i }).click();

    // The launcher polls the job and navigates to the selected run when it finishes.
    await page.waitForURL(/\/forecasts\/\d+$/, { timeout: 120_000 });
    await expect(page.getByRole("heading", { name: /actual versus forecast/i })).toBeVisible();

    // --- Inspect metrics and charts -------------------------------------------------
    for (const metric of ["WAPE", "MAE", "RMSE", "MASE", "Bias"]) {
      await expect(page.locator(".kpi-label", { hasText: metric }).first()).toBeVisible();
    }

    await expect(page.getByRole("table").filter({ hasText: /Seasonal naive/i })).toBeVisible();
    await expect(page.getByText(/fixed multi-step recursive/i).first()).toBeVisible();
    await expect(page.getByText(/not a real-world benchmark/i).first()).toBeVisible();

    // Switching to the forward view must plot the planning horizon with its band.
    await page.getByRole("button", { name: "Forward" }).click();
    await expect(page.locator(".chart-insight").filter({ hasText: /Forward plan for the next/i })).toBeVisible();

    // Filtering to a single series must change the chart summary text.
    await page.getByRole("button", { name: "Holdout" }).click();
    const seriesButton = page.getByRole("button", { name: /e2e-mocha @ e2e-north/i }).first();
    if (await seriesButton.isVisible()) {
      await seriesButton.click();
      await expect(page.getByText(/e2e-mocha @ e2e-north/).first()).toBeVisible();
    }

    // --- Export a report ------------------------------------------------------------
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: /report json/i }).first().click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^report-run\d+-.+\.json$/);

    // --- Reorder suggestions --------------------------------------------------------
    await page.goto("/planning");
    await page.getByLabel("Policy name").fill("E2E weekly review");
    await page.getByLabel(/minimum order quantity/i).fill("12");
    await page.getByLabel(/pack size/i).fill("6");
    await page.getByRole("button", { name: /create policy/i }).click();
    await expect(page.getByText(/policy "E2E weekly review" created/i).first()).toBeVisible();

    await page.getByRole("button", { name: /generate suggestions/i }).click();
    await expect(page.getByText(/generated \d+ suggestions/i).first()).toBeVisible();
    await expect(page.getByRole("table").filter({ hasText: /reorder point/i }).first()).toBeVisible();
    await expect(page.getByText(/decision support, not purchasing/i).first()).toBeVisible();

    // --- Alerts reflect the generated exposure --------------------------------------
    await page.goto("/alerts");
    await expect(page.getByRole("heading", { name: "Alerts" })).toBeVisible();
    await expect(page.locator(".kpi-label", { hasText: "Open" }).first()).toBeVisible();
  });

  test("a viewer sees a read-only workspace", async ({ page, browser }) => {
    const viewerContext = await browser.newContext();
    const viewerPage = await viewerContext.newPage();
    await viewerPage.goto("/login");
    await viewerPage.getByLabel("Email").fill("viewer@forecastops.example");
    await viewerPage.getByLabel("Password").fill("viewer-demo-2024");
    await viewerPage.getByRole("button", { name: /sign in/i }).click();
    await viewerPage.waitForURL("**/dashboard");

    await viewerPage.goto("/upload");
    await expect(viewerPage.getByText(/read-only role/i)).toBeVisible();

    await viewerPage.goto("/forecasts");
    await expect(viewerPage.getByText(/your role is read-only/i)).toBeVisible();

    await viewerContext.close();
    await page.goto("/login");
  });
});
