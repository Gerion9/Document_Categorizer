import React, { HTMLAttributes } from "react";
import { supportsLiquidGlass } from "../../lib/liquid-glass/featureDetection";

export interface GlassSurfaceProps extends HTMLAttributes<HTMLDivElement> {
  filterId?: string;
  fallbackClassName?: string;
  children: React.ReactNode;
  as?: React.ElementType;
  contentClassName?: string;
  [key: string]: any;
}

export const GlassSurface = React.forwardRef<HTMLElement, GlassSurfaceProps>(
  (
    {
      filterId = "glass-panel",
      fallbackClassName = "glass-fallback",
      className = "",
      contentClassName = "relative z-10 h-full",
      children,
      as: Component = "div",
      style,
      ...props
    },
    ref
  ) => {
    const isSupported = supportsLiquidGlass();
    
    const glassStyle = isSupported ? { ...style, backdropFilter: `url(#${filterId})`, WebkitBackdropFilter: `url(#${filterId})` } : style;
    const baseClass = isSupported ? "bg-white/10" : fallbackClassName;

    return (
      <Component
        ref={ref}
        style={glassStyle}
        className={`${baseClass} shadow-glass border border-glass-border overflow-hidden relative ${className}`}
        {...props}
      >
        <div className="absolute inset-0 rounded-inherit border-t border-l border-white/40 pointer-events-none mix-blend-overlay"></div>
        <div className={contentClassName}>{children}</div>
      </Component>
    );
  }
);
GlassSurface.displayName = "GlassSurface";

