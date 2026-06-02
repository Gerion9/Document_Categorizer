import { CaseCard } from "./CaseCard";
import { SkeletonBlock } from "./SkeletonBlock";

interface LoadingSkeletonProps {
  rows?: number;
  className?: string;
}

export function LoadingSkeleton({
  rows = 6,
  className = "",
}: LoadingSkeletonProps) {
  return (
    <div
      className={`grid gap-6 sm:grid-cols-2 lg:grid-cols-3 ${className}`}
      role="status"
      aria-label="Cargando expedientes"
    >
      {Array.from({ length: rows }).map((_, index) => (
        <CaseCard key={index} className="flex flex-col px-6 py-5">
          <SkeletonBlock className="h-5 w-3/4 mb-3" />
          <SkeletonBlock className="h-3 w-full mb-2" />
          <SkeletonBlock className="h-3 w-5/6 mb-2" />
          <SkeletonBlock className="h-3 w-4/5 mb-6" />
          <div className="flex gap-2 border-t border-brand-100/60 pt-4 mt-auto">
            <SkeletonBlock className="h-6 w-16" />
            <SkeletonBlock className="h-6 w-12" />
          </div>
        </CaseCard>
      ))}
      <span className="sr-only">Cargando expedientes…</span>
    </div>
  );
}
