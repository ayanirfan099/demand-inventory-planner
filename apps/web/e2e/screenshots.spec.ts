import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

/**
 * Generates the screenshots referenced by the README.
 * Run with: npm run e2e:screenshots (requires `npx playwright install chromium`).
 * Tagged so the regular CI suite can skip it.
 */
test.describe("documentation screenshots @screenshots", () => {
  test("capture dashboard, run detail and planning views", async ({ page }) => {
    await signIn(page);

    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "../../docs/screenshots/dashboard.png", fullPage: false });

    await page.goto("/forecasts");
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "../../docs/screenshots/forecasts.png", fullPage: false });

    const runLink = page.getByRole("link", { name: "Open →" }).first();
    if (await runLink.isVisible()) {
      await runLink.click();
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: "../../docs/screenshots/run-detail.png", fullPage: false });
    }

    await page.goto("/planning");
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "../../docs/screenshots/planning.png", fullPage: false });

    await page.goto("/upload");
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "../../docs/screenshots/import.png", fullPage: false });

    expect(true).toBe(true);
  });
});
