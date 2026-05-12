function SkeletonBlock({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800 ${className ?? ''}`} />;
}

/**
 * Layered loading state: mirrors the decision pyramid instead of using one spinner.
 */
export function LoadingSkeleton() {
  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-5 px-4 py-6">
      <SkeletonBlock className="h-32" />
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <SkeletonBlock className="h-44" />
        <SkeletonBlock className="h-44" />
        <SkeletonBlock className="h-44" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SkeletonBlock className="h-40" />
        <SkeletonBlock className="h-40" />
      </div>
      <SkeletonBlock className="h-64" />
    </div>
  );
}
