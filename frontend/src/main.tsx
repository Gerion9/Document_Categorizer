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
    <BrowserRouter>
      <TooltipProvider delayDuration={200}>
        <LiquidGlassFilters />
        <Toaster position="top-right" />
        <App />
      </TooltipProvider>
    </BrowserRouter>
  </React.StrictMode>
);

