import { defineConfig, devices } from "@playwright/test";

const WEB = process.env.FORECASTOPS_WEB_URL ?? "http://127.0.0.1:3000";
const API = process.env.FORECASTOPS_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // The app is served through a proxied host in hosted previews; ignore HTTPS errors.
    ignoreHTTPSErrors: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.FORECASTOPS_E2E_NO_SERVER
    ? undefined
    : {
        command: "npm run e2e:serve",
        url: WEB,
        reuseExistingServer: true,
        timeout: 180_000,
        env: { FORECASTOPS_API_URL: API },
      },
});
