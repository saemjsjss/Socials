/** @type {import('next').NextConfig} */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  // The HUD needs the camera (CameraScanner) and microphone (voice input) on its own origin only.
  { key: "Permissions-Policy", value: "camera=(self), microphone=(self), geolocation=()" },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // `ws` (Edge-TTS client) has optional native add-ons; keep it out of the server bundle.
  serverExternalPackages: ["ws"],
  // Which deployment this build is for (Vercel sets VERCEL_ENV at build time): gates the
  // preview-only emote picker so it can never render on production.
  env: { NEXT_PUBLIC_DEPLOY_ENV: process.env.VERCEL_ENV || "local" },
  // transformers.js (the device's question embedder, a Web Worker) runs on WASM in the
  // browser; its Node-only backends must never be bundled.
  webpack(config) {
    config.resolve.alias = { ...config.resolve.alias, "sharp$": false, "onnxruntime-node$": false };
    return config;
  },
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
