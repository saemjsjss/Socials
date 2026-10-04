import type { Config } from "tailwindcss";

// "Pink Overdrive" palette. Use these tokens instead of raw hex values in components.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: {
          DEFAULT: "#0A050A", // deep void background
          800: "#120712", // raised void (panels)
          700: "#1A0B1A",
        },
        neon: {
          DEFAULT: "#FF007F", // neon hot pink (primary)
          deep: "#FF1493",
          hot: "#FF69B4",
        },
        petal: {
          DEFAULT: "#F472B6", // rose-gold accent
          soft: "#FBCFE8", // soft pink accent / body text
        },
        glow: "rgba(255, 0, 127, 0.4)", // cyber glow borders
      },
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["var(--font-sans)", "var(--font-kr)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 20px rgba(255, 0, 127, 0.45)",
        "glow-sm": "0 0 8px rgba(255, 0, 127, 0.5)",
        "glow-lg": "0 0 60px rgba(255, 0, 127, 0.35)",
        "inner-glow": "inset 0 0 24px rgba(255, 0, 127, 0.18)",
      },
      keyframes: {
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        flicker: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.72" },
        },
      },
      animation: {
        scan: "scan 3s linear infinite",
        flicker: "flicker 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
