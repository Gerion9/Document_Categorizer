import { GlassSurface, GlassSurfaceProps } from "./GlassSurface";

export function GlassCard({ className = "", children, ...props }: GlassSurfaceProps) {
  return (
    <GlassSurface
      filterId="glass-card"
      className={`rounded-2xl p-5 hover:shadow-glass-lg hover:-translate-y-0.5 transition-[box-shadow,transform] duration-300 ${className}`}
      {...props}
    >
      {children}
    </GlassSurface>
  );
}

