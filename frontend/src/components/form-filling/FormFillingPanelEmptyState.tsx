import type { ReactNode } from "react";

type EmptyStateProps = {
  icon?: React.ElementType;
  title?: string;
  description?: string;
  className?: string;
  withBorder?: boolean;
  tone?: "default" | "danger";
  action?: ReactNode;
  role?: "status" | "alert";
  ariaLive?: "off" | "polite" | "assertive";
};

export function EmptyState({
  icon: Icon,
  title,
  description,
  className = "",
  withBorder = true,
  tone = "default",
  action,
  role = "status",
  ariaLive = "polite",
}: EmptyStateProps) {
  const isDanger = tone === "danger";

  return (
    <div
      role={role}
      aria-live={ariaLive}
      className={`flex h-full flex-col items-center justify-center rounded-2xl p-6 text-center ${
        withBorder
          ? isDanger
            ? "border border-dashed border-red-200 bg-red-50/70"
            : "border border-dashed border-gray-200 bg-gray-50"
          : ""
      } ${className}`}
    >
      <div className={`space-y-2 ${isDanger ? "text-red-700" : "text-gray-500"}`}>
        {Icon && (
          <Icon
            aria-hidden="true"
            className={`mx-auto h-10 w-10 ${isDanger ? "text-red-300" : "text-gray-300"}`}
          />
        )}
        {title && (
          <p className={`text-sm font-medium ${isDanger ? "text-red-800" : "text-gray-700"}`}>
            {title}
          </p>
        )}
        {description && (
          <p className={`text-sm ${isDanger ? "text-red-700" : "text-gray-500"}`}>
            {description}
          </p>
        )}
        {action && <div className="pt-2">{action}</div>}
      </div>
    </div>
  );
}
