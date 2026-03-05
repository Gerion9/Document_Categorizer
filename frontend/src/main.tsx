import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import { TooltipProvider } from "./components/ui/Tooltip";
import { LiquidGlassFilters } from "./components/glass/LiquidGlassFilter";
import App from "./App";
import "./index.css";

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

