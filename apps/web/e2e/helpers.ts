import type { Page } from "@playwright/test";

export const DEMO_EMAIL = process.env.FORECASTOPS_E2E_EMAIL ?? "demo@forecastops.example";
export const DEMO_PASSWORD = process.env.FORECASTOPS_E2E_PASSWORD ?? "planning-demo-2024";

export async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_EMAIL);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");
  await page.getByRole("heading", { name: /demand planning at a glance/i }).waitFor();
}

export function demoCsv(): string {
  const rows = ["date,store,item,sales,on_hand"];
  const start = new Date("2025-01-01T00:00:00Z");
  for (let day = 0; day < 140; day += 1) {
    const date = new Date(start.getTime() + day * 86_400_000).toISOString().slice(0, 10);
    for (const store of ["e2e-north", "e2e-south"]) {
      for (const item of ["e2e-latte", "e2e-mocha"]) {
        const base = 20 + (store === "e2e-north" ? 5 : 0) + (item === "e2e-mocha" ? 3 : 0);
        const weekly = Math.round(base * (1 + 0.3 * Math.sin((day % 7) / 1.1)));
        rows.push(`${date},${store},${item},${weekly},${weekly * 24}`);
      }
    }
  }
  return `${rows.join("\n")}\n`;
}
