import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // next build writes a self-contained server to .next/standalone (only the node_modules it
  // actually uses), which keeps the docker image small. see web/Dockerfile
  output: "standalone",
  images: {
    // every photo and cover url in the database comes from deezer (stage 5 stores urls only).
    // next/image only resizes images from hosts listed here, so a random url can't use our server
    remotePatterns: [new URL("https://cdn-images.dzcdn.net/images/**")],
  },
};

export default nextConfig;
