import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",

        // App shell (dark surface)
        bg: "hsl(var(--bg))",
        bg2: "hsl(var(--bg2))",
        panel: "hsl(var(--panel))",
        "panel-2": "hsl(var(--panel-2))",
        line: "hsl(var(--line))",
        "line-2": "hsl(var(--line-2))",
        ink: "hsl(var(--text))",
        dim: "hsl(var(--dim))",
        faint: "hsl(var(--faint))",

        // Semantic accents (identical on both surfaces except teal/coral)
        teal: "hsl(var(--teal))",
        amber: "hsl(var(--amber))",
        "brand-green": "hsl(var(--green))",
        gemini: "hsl(var(--gemini))",
        mistral: "hsl(var(--mistral))",
        groq: "hsl(var(--groq))",

        // Landing (light surface)
        paper: "hsl(var(--paper))",
        "text-ink": "hsl(var(--ink))",
        "ink-dim": "hsl(var(--ink-dim))",
        "paper-line": "hsl(var(--paper-line))",
        card: "hsl(var(--card))",
        "teal-landing": "hsl(var(--teal-landing))",
        "teal-landing-dark": "hsl(var(--teal-landing-dark))",
        coral: "hsl(var(--coral))",
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
        display: ["Space Grotesk", "sans-serif"],
        "landing-display": ["Instrument Sans", "sans-serif"],
        "landing-body": ["Geist", "sans-serif"],
        "landing-mono": ["Geist Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
