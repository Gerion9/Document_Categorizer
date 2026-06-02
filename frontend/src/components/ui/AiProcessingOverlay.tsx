import { NovaBreathingLogo } from "./NovaBreathingLogo";
import { SkeletonBlock } from "./SkeletonBlock";

interface AiProcessingOverlayProps {
  message?: string;
  className?: string;
}

export function AiProcessingOverlay({
  message = "Generando redacción automática…",
  className = "",
}: AiProcessingOverlayProps) {
  return (
    <div
      className={`pointer-events-auto absolute inset-0 z-20 flex flex-col items-center justify-start gap-5 bg-white/80 p-6 backdrop-blur-[2px] ${className}`}
      role="status"
      aria-live="polite"
    >
      <NovaBreathingLogo size="lg" label={message} />
      <p className="text-sm font-medium text-accent-600 text-center max-w-sm">{message}</p>
      <div className="w-full max-w-lg space-y-2.5 mt-2">
        <SkeletonBlock className="h-4 w-3/4" />
        <SkeletonBlock className="h-3 w-full" />
        <SkeletonBlock className="h-3 w-full" />
        <SkeletonBlock className="h-3 w-11/12" />
        <SkeletonBlock className="h-3 w-4/5" />
        <SkeletonBlock className="h-3 w-5/6" />
      </div>
    </div>
  );
}
