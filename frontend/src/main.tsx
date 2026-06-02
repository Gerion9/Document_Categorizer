import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import { TooltipProvider } from "./components/ui/Tooltip";
import { LiquidGlassFilters } from "./components/glass/LiquidGlassFilter";
import App from "./App";
import "./index.css";

const params = new URLSearchParams(window.location.search);
const token = params.get("token");
if (token) {
  sessionStorage.setItem("auth_token", token);
  window.history.replaceState({}, "", window.location.pathname);
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TooltipProvider delayDuration={200}>
        <LiquidGlassFilters />
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            className:
              "!rounded-xl !border !border-white/60 !bg-white/95 !text-gray-800 !text-sm !font-medium !shadow-glass-lg !backdrop-blur-md",
            success: {
              iconTheme: { primary: "#1e3a5f", secondary: "#eff6ff" },
            },
            error: {
              iconTheme: { primary: "#dc2626", secondary: "#fef2f2" },
            },
          }}
        />
        <App />
      </TooltipProvider>
    </BrowserRouter>
  </React.StrictMode>
);