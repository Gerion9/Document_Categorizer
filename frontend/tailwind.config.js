/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        heading: [
          "Outfit",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        surface: "#e8f1f8",
        nova: {
          deep: "#143457",
          gold: "#bd9655",
          "gold-light": "#e3c48e",
          ice: "#e8f1f8",
          slate: "#0a1c30",
          snow: "#ffffff",
        },
        brand: {
          50: "#e8f1f8",
          100: "#d4e4f0",
          200: "#b8d0e4",
          300: "#8fb3d0",
          400: "#5a8ab8",
          500: "#2d5a85",
          600: "#143457",
          700: "#102a47",
          800: "#0a1c30",
          900: "#061220",
        },
        accent: {
          50: "#faf5eb",
          100: "#f3e8d4",
          200: "#e3c48e",
          300: "#d4ad6a",
          400: "#c9a060",
          500: "#bd9655",
          600: "#a68145",
          700: "#8a6a38",
          800: "#6e542c",
          900: "#523f21",
        },
        glass: {
          border: "rgba(255, 255, 255, 0.4)",
          highlight: "rgba(255, 255, 255, 0.8)",
          fill: "rgba(232, 241, 248, 0.65)",
        },
      },
      boxShadow: {
        glass: "0 8px 32px 0 rgba(10, 28, 48, 0.08)",
        "glass-lg": "0 8px 32px 0 rgba(10, 28, 48, 0.16)",
        "glass-inner": "inset 0 1px 1px 0 rgba(255, 255, 255, 0.5)",
        nova: "0 12px 40px rgba(10, 28, 48, 0.25)",
        gold: "0 4px 20px rgba(189, 150, 85, 0.35)",
      },
      backgroundImage: {
        "glass-gradient":
          "linear-gradient(to bottom left, rgba(255, 255, 255, 0.72) 0%, rgba(232, 241, 248, 0.45) 100%)",
        "glass-gradient-hover":
          "linear-gradient(to bottom left, rgba(255, 255, 255, 0.88) 0%, rgba(232, 241, 248, 0.55) 100%)",
        "nova-horizon":
          "linear-gradient(to bottom left, #2d5a85 0%, #143457 52%, #0a1c30 100%)",
        "glow-gold": "linear-gradient(to bottom left, #bd9655 0%, #e3c48e 100%)",
        "glass-edge":
          "linear-gradient(to bottom left, rgba(255, 255, 255, 0.1) 0%, rgba(255, 255, 255, 0) 100%)",
      },
      backdropBlur: {
        glass: "12px",
        "glass-md": "16px",
        "glass-lg": "24px",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "glass-shine": {
          "0%": { backgroundPosition: "200% center" },
          "100%": { backgroundPosition: "-200% center" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.5s infinite",
        "glass-shine": "glass-shine 3s linear infinite",
        "fade-in": "fade-in 0.35s ease-out forwards",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
