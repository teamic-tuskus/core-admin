import type { NextConfig } from "next";

const configuredApiBase = process.env.NEXT_PUBLIC_COREADMIN_API_BASE || "https://api.tuskus.com/api/v1";
const remoteApiBase = configuredApiBase.replace(/\/$/, "");
const enableLocalApiProxy = process.env.NODE_ENV !== "production";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "export",
  images: {
    unoptimized: true,
  },
  ...(enableLocalApiProxy
    ? {
        async rewrites() {
          return [
            {
              source: "/__coreadmin_api/:path*",
              destination: `${remoteApiBase}/:path*`,
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
