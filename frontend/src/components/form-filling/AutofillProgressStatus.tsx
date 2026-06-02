interface AutofillProgressStatusProps {
  message: string;
  progress: number;
  progressAriaLabel?: string;
}

export function AutofillProgressStatus({
  message,
  progress,
  progressAriaLabel = "AI autofill progress",
}: AutofillProgressStatusProps) {
  const clampedProgress = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex max-w-sm flex-col items-end gap-1.5"
    >
      <span className="text-right text-sm font-medium leading-snug text-accent-600">
        {message || "Processing questions..."}
      </span>
      <div className="flex w-44 shrink-0 items-center gap-2.5">
        <span className="w-8 shrink-0 text-xs tabular-nums text-brand-500">
          {clampedProgress}%
        </span>
        <div
          className="ai-progress-track h-2 min-w-0 flex-1"
          role="progressbar"
          aria-label={progressAriaLabel}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={clampedProgress}
        >
          <div
            className="ai-progress-bar"
            style={{ width: `${clampedProgress}%` }}
          />
        </div>
      </div>
    </div>
  );
}
