import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Speed up dev compilation by telling Next.js these packages
  // can be tree-shaken at the module level (avoids re-exporting everything).
  experimental: {
    optimizePackageImports: ["recharts", "lucide-react"],
    proxyTimeout: 300_000,                  // 5 minutes — for slow AI calls
    middlewareClientMaxBodySize: "60mb",    // raise upload cap from 10 MB default
    serverActions: {
      bodySizeLimit: "60mb",               // also for server actions
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;