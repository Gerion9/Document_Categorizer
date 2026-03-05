/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#1e3a5f",
          700: "#172e4a",
          800: "#0f1f35",
          900: "#0a1525",
        },
        glass: {
          border: "rgba(255, 255, 255, 0.4)",
          highlight: "rgba(255, 255, 255, 0.8)",
          fill: "rgba(255, 255, 255, 0.5)",
        }
      },
      boxShadow: {
        glass: "0 8px 32px 0 rgba(31, 38, 135, 0.07)",
        "glass-lg": "0 8px 32px 0 rgba(31, 38, 135, 0.15)",
        "glass-inner": "inset 0 1px 1px 0 rgba(255, 255, 255, 0.5)",
      },
      backgroundImage: {
        "glass-gradient": "linear-gradient(135deg, rgba(255, 255, 255, 0.6) 0%, rgba(255, 255, 255, 0.2) 100%)",
        "glass-gradient-hover": "linear-gradient(135deg, rgba(255, 255, 255, 0.8) 0%, rgba(255, 255, 255, 0.3) 100%)",
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
      },
      animation: {
        shimmer: "shimmer 1.5s infinite",
        "glass-shine": "glass-shine 3s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
