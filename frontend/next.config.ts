import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Bundles the server and only the node_modules it actually imports into
  // .next/standalone, so the production image does not need a node_modules
  // layer. Ignored by `next dev`.
  output: "standalone",
  // Dev only. Next refuses cross-origin requests to the dev server unless the
  // origin is listed, which is exactly what happens the moment you open the
  // app from a phone on the same Wi-Fi or through a tunnel. Set DEV_ORIGINS to
  // a comma-separated list to add more.
  allowedDevOrigins: [
    ...(process.env.DEV_ORIGINS?.split(",").map((o) => o.trim()) ?? []),
    "192.168.0.0/16",
    "10.0.0.0/8",
    "*.trycloudflare.com",
    "*.ngrok-free.app",
    "*.ts.net",
  ],
  // The service worker must be served from the origin root to control the
  // whole scope, and it must never be cached or an update can strand users on
  // an old one.
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      {
        source: "/manifest.webmanifest",
        headers: [{ key: "Cache-Control", value: "public, max-age=3600" }],
      },
    ];
  },
  // Proxying keeps the API same-origin in the browser, which means the
  // service worker can cache API responses and push subscriptions do not need
  // a CORS exception.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
