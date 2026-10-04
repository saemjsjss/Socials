import type { MetadataRoute } from "next";

/** Plain backdrop behind the avatar clips (sampled from the idle clip), used for the splash screen and theme. */
const AVATAR_BACKDROP = "#dbc7c7";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Jeannie",
    short_name: "Jeannie",
    description: "Jeannie, your bilingual (English / 한국어) personal AI companion.",
    lang: "ko",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: AVATAR_BACKDROP,
    theme_color: AVATAR_BACKDROP,
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
