import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Noto_Sans_KR, Orbitron } from "next/font/google";
import { ServiceWorkerRegister } from "@/components/ServiceWorkerRegister";
import "./globals.css";

const display = Orbitron({ subsets: ["latin"], display: "swap", variable: "--font-display" });
const mono = JetBrains_Mono({ subsets: ["latin"], display: "swap", variable: "--font-mono" });
const sans = Inter({ subsets: ["latin"], display: "swap", variable: "--font-sans" });
// Korean glyphs ship as many unicode-range slices; load them lazily instead of preloading.
const korean = Noto_Sans_KR({ display: "swap", variable: "--font-kr", preload: false });

export const metadata: Metadata = {
  title: "Jeannie · Tactical AI",
  description:
    "Jeannie is a bilingual (English / 한국어) multimodal personal AI with a neon-pink tactical HUD: live search, vision, voice and smart-home control.",
  applicationName: "Jeannie",
  icons: { icon: "/favicon.ico" },
};

export const viewport: Viewport = {
  // Phones default to the avatar screen (light backdrop, see manifest.ts); everything else gets the dark HUD.
  themeColor: [
    { media: "(orientation: portrait) and (max-width: 480px) and (pointer: coarse)", color: "#dbc7c7" },
    { color: "#0A050A" },
  ],
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${mono.variable} ${sans.variable} ${korean.variable}`}
      suppressHydrationWarning
    >
      <body className="bg-void font-sans text-petal-soft antialiased">
        {children}
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}
