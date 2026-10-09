import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f4f7f6",
          900: "#0e1b18",
          950: "#08110f",
        },
        sage: {
          400: "#7dba9a",
          500: "#2f6f5e",
          600: "#245a4c",
        },
      },
    },
  },
  plugins: [],
};

export default config;
