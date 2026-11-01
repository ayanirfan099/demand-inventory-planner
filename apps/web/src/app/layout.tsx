import type { Metadata, Viewport } from "next";

import { SessionProvider } from "@/components/SessionProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "ForecastOps — Demand & Inventory Planning",
    template: "%s · ForecastOps",
  },
  description:
    "Leakage-aware demand forecasting with baseline comparison, chronological evaluation and reorder decision support. Demo data is synthetic.",
  applicationName: "ForecastOps",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0d2b45",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
