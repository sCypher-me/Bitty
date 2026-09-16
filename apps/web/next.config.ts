import type { NextConfig } from "next";
const apiOrigin=process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
const lanHost=process.env.BITTY_LAN_HOST;
const nextConfig:NextConfig={
  output:"standalone",
  reactStrictMode:true,
  allowedDevOrigins:["127.0.0.1","localhost",...(lanHost?[lanHost]:[])],
  async rewrites(){return [{source:"/api/v1/:path*",destination:`${apiOrigin}/api/v1/:path*`}];},
};
export default nextConfig;
