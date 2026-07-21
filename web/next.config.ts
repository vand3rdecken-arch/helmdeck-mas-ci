import type { NextConfig } from "next";

// The Python daemon (port 8140) stays the backend/runner; Next serves the UI
// and proxies /backend/* to it so the session cookie is same-origin.
const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/backend/:path*", destination: "http://localhost:8140/:path*" },
    ];
  },
};

export default nextConfig;
