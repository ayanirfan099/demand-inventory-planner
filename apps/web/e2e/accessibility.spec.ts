import { expect, test } from "@playwright/test";

import { auditPage } from "./axe";
import { signIn } from "./helpers";

/** Every page a signed-in demo user can reach. The run detail page is audited by the flow spec,
 *  where a real run exists, so charts and dense tables are covered too. */
const PAGES: [label: string, path: string][] = [
  ["dashboard", "/dashboard"],
  ["datasets", "/datasets"],
  ["import", "/upload"],
  ["forecasts", "/forecasts"],
  ["planning", "/planning"],
  ["alerts", "/alerts"],
  ["audit", "/audit"],
];

test.describe("accessibility", () => {
  test("the login screen passes a WCAG 2.1 AA audit", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    const failures = await auditPage(page, "login");
    expect(failures, `WCAG violations on /login:\n${failures.join("\n")}`).toEqual([]);
  });

  test("every signed-in page passes a WCAG 2.1 AA audit", async ({ page }) => {
    await signIn(page);

    const failures: string[] = [];
    for (const [label, path] of PAGES) {
      await page.goto(path);
      // Pages fetch their data client-side after the session resolves; auditing too early would
      // check an empty skeleton and pass for the wrong reason.
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main")).toBeVisible();
      failures.push(...(await auditPage(page, label)));
    }

    expect(failures, `WCAG violations:\n${failures.join("\n")}`).toEqual([]);
  });
});
