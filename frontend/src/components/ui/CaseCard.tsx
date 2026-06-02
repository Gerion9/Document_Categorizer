import { HTMLAttributes } from "react";

interface CaseCardProps extends HTMLAttributes<HTMLDivElement> {}

export function CaseCard({ className = "", children, ...props }: CaseCardProps) {
  return (
    <div className={`case-card group/card flex h-full flex-col ${className}`} {...props}>
      <div className="case-card-decoration pointer-events-none" aria-hidden="true">
        <div className="case-card-accent" />
        <div className="case-card-edge" />
      </div>
      <div className="relative z-10 flex flex-col flex-1 min-h-0">{children}</div>
    </div>
  );
}
