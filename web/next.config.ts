import type { NextConfig } from "next";
import path from "path";

// The Python daemon (port 8140) stays the backend/runner; Next serves the UI
// and proxies /backend/* to it so the session cookie is same-origin.
const nextConfig: NextConfig = {
  // self-contained server build (.next/standalone/server.js) so the desktop
  // Electron app can run the UI with no node_modules install on the user's PC.
  output: "standalone",
  // pin the trace root to this app dir, else Next infers a parent (Downloads)
  // and nests the standalone output under Downloads/swarmdeck/web/server.js.
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    return [
      { source: "/backend/:path*", destination: "http://localhost:8140/:path*" },
    ];
  },
};

export default nextConfig;
