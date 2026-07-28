import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  experimental: { optimizePackageImports: ["lucide-react"] },
  async rewrites() {
    const apiProxy = (process.env.SIGNAL_INDEX_API_PROXY ?? "http://localhost:8000/api/v1").replace(/\/$/, "");
    return [{ source: "/api/v1/:path*", destination: `${apiProxy}/:path*` }];
  },
};

export default config;
