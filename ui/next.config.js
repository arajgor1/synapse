/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Proxy gateway calls during dev — UI on :3000, gateway on :8000
  async rewrites() {
    const gatewayUrl =
      process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8000";
    return [
      { source: "/api/gateway/:path*", destination: `${gatewayUrl}/:path*` },
    ];
  },
};

module.exports = nextConfig;
