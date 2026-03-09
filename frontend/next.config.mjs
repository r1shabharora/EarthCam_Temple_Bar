/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    YOUTUBE_VIDEO_ID: process.env.YOUTUBE_VIDEO_ID ?? "3nyPER2kzqk",
  },
};

export default nextConfig;
