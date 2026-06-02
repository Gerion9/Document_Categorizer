import React, { ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";

interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "ai";
  size?: "xs" | "sm" | "md" | "lg";
  isActive?: boolean;
  fullWidth?: boolean;
  iconOnly?: boolean;
  loading?: boolean;
  loadingLabel?: string;
}

export const GlassButton = React.forwardRef<HTMLButtonElement, GlassButtonProps>(
  (
    {
      className = "",
      variant = "secondary",
      size = "md",
      isActive = false,
      fullWidth = false,
      iconOnly = false,
      loading = false,
      loadingLabel,
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading;
    const spinnerSize =
      iconOnly
        ? size === "lg"
          ? "h-5 w-5"
          : size === "xs"
            ? "h-3.5 w-3.5"
            : "h-4 w-4"
        : size === "lg"
          ? "h-5 w-5"
          : size === "sm" || size === "xs"
            ? "h-3.5 w-3.5"
            : "h-4 w-4";
    const baseStyle =
      "relative inline-flex shrink-0 items-center justify-center font-semibold transition-[background-image,box-shadow,border-color,color,opacity,transform] duration-300 ease-out overflow-hidden focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]";

    const sizeClass = iconOnly
      ? size === "xs"
        ? "h-8 w-8 !rounded-full p-0"
        : size === "sm"
          ? "h-9 w-9 !rounded-full p-0"
          : size === "lg"
            ? "h-12 w-12 !rounded-full p-0"
            : "h-10 w-10 !rounded-full p-0"
      : size === "sm"
        ? "px-4 py-2 text-xs rounded-full"
        : size === "lg"
          ? "px-7 py-3.5 text-base rounded-full"
          : "px-5 py-2.5 text-sm rounded-full";

    const contentGap = iconOnly
      ? ""
      : size === "sm"
        ? "gap-1.5"
        : size === "lg"
          ? "gap-2.5"
          : "gap-2";

    const activeClass =
      "border border-brand-600 bg-brand-600 text-white hover:border-brand-700 hover:bg-brand-700 hover:text-white shadow-md";

    const variantClass =
      variant === "ai"
        ? isActive
          ? activeClass
          : "cta-ai"
        : variant === "primary"
          ? "cta-primary"
          : variant === "danger"
            ? "rounded-full text-white bg-red-600 hover:bg-red-500 shadow-md"
            : variant === "ghost"
              ? isActive
                ? activeClass
                : "text-brand-700 bg-brand-50/80 border border-brand-100 hover:bg-brand-100 hover:text-brand-800 shadow-sm"
              : isActive
                ? activeClass
                : "text-brand-700 bg-nova-snow border border-brand-100 hover:bg-brand-50 hover:border-brand-200 shadow-sm";

    const widthClass = fullWidth ? "w-full" : "";
    const showInnerHighlight = variant === "primary" || variant === "ai" || isActive;

    return (
      <button
        ref={ref}
        data-icon-only={iconOnly ? "true" : undefined}
        disabled={isDisabled}
        aria-busy={loading || undefined}
        className={`${baseStyle} ${sizeClass} ${widthClass} ${variantClass} ${className}`}
        {...props}
      >
        {showInnerHighlight && (
          <div
            className="absolute inset-0 rounded-[inherit] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.22)] pointer-events-none"
            aria-hidden="true"
          />
        )}
        {variant === "ai" && !isActive && (
          <div className="absolute inset-0 glass-edge-top pointer-events-none" aria-hidden="true" />
        )}
        <span className={`relative z-10 flex items-center justify-center ${contentGap}`}>
          {loading && (
            <Loader2
              aria-hidden="true"
              className={`animate-spin shrink-0 ${spinnerSize}`}
            />
          )}
          {!(loading && iconOnly) &&
            (loading && loadingLabel ? loadingLabel : children)}
        </span>
      </button>
    );
  }
);
GlassButton.displayName = "GlassButton";
