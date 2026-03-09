import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        neon: "#00ff88",
        cyan: "#00d4ff",
        surface: "rgba(255,255,255,0.03)",
      },
      fontFamily: {
        mono: ["var(--font-mono)", "monospace"],
      },
      animation: {
        pulse_slow: "pulse 3s cubic-bezier(0.4,0,0.6,1) infinite",
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.4s ease-out",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
      backgroundImage: {
        "dot-grid":
          "radial-gradient(circle, rgba(0,255,136,0.08) 1px, transparent 1px)",
      },
      backgroundSize: {
        "dot-grid": "28px 28px",
      },
    },
  },
  plugins: [],
};
export default config;
