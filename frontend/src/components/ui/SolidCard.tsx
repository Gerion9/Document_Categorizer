import { HTMLAttributes } from "react";

interface SolidCardProps extends HTMLAttributes<HTMLDivElement> {
  reading?: boolean;
}

export function SolidCard({
  className = "",
  reading = false,
  children,
  ...props
}: SolidCardProps) {
  return (
    <div
      className={`${reading ? "reading-surface" : "solid-panel"} rounded-2xl ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
