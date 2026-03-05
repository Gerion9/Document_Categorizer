import React from "react";
import { GlassSurface, GlassSurfaceProps } from "./GlassSurface";

export function GlassCard({ className = "", children, ...props }: GlassSurfaceProps) {
  return (
    <GlassSurface
      filterId="glass-card"
      className={`rounded-2xl p-5 hover:shadow-glass-lg transition-shadow duration-300 ${className}`}
      {...props}
    >
      {children}
    </GlassSurface>
  );
}

