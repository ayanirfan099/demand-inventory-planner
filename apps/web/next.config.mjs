/** @type {import('next').NextConfig} */
const API_ORIGIN = process.env.FORECASTOPS_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  // The browser only ever talks to this origin; Next proxies to the API server-side.
  // That keeps session cookies first-party and avoids CORS entirely.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/healthz", destination: `${API_ORIGIN}/healthz` },
    ];
  },
  // Dev-server host allowlist so the hosted preview origin can reach the dev server.
  allowedDevOrigins: ["*.e2b.app", "localhost:3000", "127.0.0.1:3000"],
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
