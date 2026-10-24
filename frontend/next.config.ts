import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // A production build can sit beside a running dev server (NEXT_DIST_DIR=.next-prod).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Pages import a handful of icons from a library of thousands; load only those.
  experimental: { optimizePackageImports: ["@phosphor-icons/react"] },
  // Locally stored creatives are served by the backend (STORAGE_BACKEND=local).
  async rewrites() {
    return [{ source: "/files/:path*", destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/files/:path*` }];
  },
};

export default config;
