import { NovaMark } from "./NovaMark";

interface NovaBreathingLogoProps {
  className?: string;
  size?: "sm" | "md" | "lg";
  label?: string;
}

const sizeClasses = {
  sm: { wrap: "h-8 w-8" },
  md: { wrap: "h-10 w-10" },
  lg: { wrap: "h-14 w-14" },
};

export function NovaBreathingLogo({
  className = "",
  size = "md",
  label = "NOVA procesando con IA",
}: NovaBreathingLogoProps) {
  const s = sizeClasses[size];

  return (
    <div
      className={`nova-breathing-logo relative inline-flex shrink-0 ${s.wrap} ${className}`}
      role="status"
      aria-label={label}
    >
      <div className={`nova-breathing-glow absolute inset-0 rounded-full`} aria-hidden="true" />
      <NovaMark className="relative z-10 h-full w-full rounded-full" />
      <span className="sr-only">{label}</span>
    </div>
  );
}
