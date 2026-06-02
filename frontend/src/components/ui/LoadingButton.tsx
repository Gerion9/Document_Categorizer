import React, { ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";

interface LoadingButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean;
  loadingLabel?: string;
  spinnerClassName?: string;
  hideContentWhenLoading?: boolean;
}

export const LoadingButton = React.forwardRef<HTMLButtonElement, LoadingButtonProps>(
  (
    {
      loading = false,
      loadingLabel,
      disabled,
      children,
      className = "",
      spinnerClassName = "h-4 w-4",
      hideContentWhenLoading = false,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading;

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        aria-busy={loading || undefined}
        className={`inline-flex items-center justify-center gap-2 ${className}`}
        {...props}
      >
        {loading && (
          <Loader2
            aria-hidden="true"
            className={`animate-spin shrink-0 ${spinnerClassName}`}
          />
        )}
        {!(loading && hideContentWhenLoading) &&
          (loading && loadingLabel ? loadingLabel : children)}
      </button>
    );
  }
);

LoadingButton.displayName = "LoadingButton";
