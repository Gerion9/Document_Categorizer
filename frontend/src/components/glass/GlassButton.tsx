import React, { ButtonHTMLAttributes } from "react";
import { supportsLiquidGlass } from "../../lib/liquid-glass/featureDetection";

interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}

export const GlassButton = React.forwardRef<HTMLButtonElement, GlassButtonProps>(
  ({ className = "", variant = "secondary", children, ...props }, ref) => {
    const isSupported = supportsLiquidGlass();
    
    const baseStyle = "relative inline-flex items-center justify-center px-4 py-2 text-sm font-medium transition-all duration-200 rounded-xl overflow-hidden focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed";
    
    let variantClass = "";
    let filterId = "glass-button";

    if (variant === "primary") {
      variantClass = "text-white bg-brand-600 hover:bg-brand-500 shadow-md";
    } else if (variant === "danger") {
      variantClass = "text-white bg-red-600 hover:bg-red-500 shadow-md";
    } else if (variant === "ghost") {
      variantClass = "text-gray-600 hover:bg-gray-100 hover:text-gray-900";
    } else {
      // Secondary / Glass
      variantClass = isSupported 
        ? "text-gray-700 bg-white/20 hover:bg-white/30 border border-glass-border shadow-glass hover:shadow-glass-lg" 
        : "text-gray-700 glass-fallback hover:bg-white/60";
    }

    const glassStyle = (isSupported && variant === "secondary") 
      ? { backdropFilter: `url(#${filterId})`, WebkitBackdropFilter: `url(#${filterId})` } 
      : {};

    return (
      <button
        ref={ref}
        style={glassStyle}
        className={`${baseStyle} ${variantClass} ${className}`}
        {...props}
      >
        {variant === "secondary" && (
          <div className="absolute inset-0 rounded-xl border-t border-l border-white/50 pointer-events-none mix-blend-overlay"></div>
        )}
        <span className="relative z-10 flex items-center gap-2">{children}</span>
      </button>
    );
  }
);
GlassButton.displayName = "GlassButton";

