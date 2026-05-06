import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0b0d10",
          panel: "#13161b",
          panel2: "#1a1e25",
        },
        line: "#262b35",
        muted: "#6a7280",
        text: {
          primary: "#e6e8ec",
          secondary: "#a1a8b3",
        },
        accent: {
          blue: "#5b8fff",
          green: "#4ade80",
          amber: "#f59e0b",
          red: "#ef4444",
        },
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};
export default config;
