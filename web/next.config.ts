import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // every photo and cover url in the database comes from deezer (stage 5 stores urls only).
    // next/image only resizes images from hosts listed here, so a random url can't use our server
    remotePatterns: [new URL("https://cdn-images.dzcdn.net/images/**")],
  },
};

export default nextConfig;
