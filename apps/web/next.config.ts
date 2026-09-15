import type { NextConfig } from "next";
const apiOrigin=process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
const nextConfig:NextConfig={
  output:"standalone",
  reactStrictMode:true,
  allowedDevOrigins:["127.0.0.1","localhost"],
  async rewrites(){return [{source:"/api/v1/:path*",destination:`${apiOrigin}/api/v1/:path*`}];},
};
export default nextConfig;
