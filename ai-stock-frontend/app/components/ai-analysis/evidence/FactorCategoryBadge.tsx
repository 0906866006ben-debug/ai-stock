import type { FactorCategory } from '@/types/aiAnalysis';
interface FactorCategoryBadgeProps {
  category: FactorCategory;
}

/**
 * Topic A category tag for factor-vote traceability.
 */
export function FactorCategoryBadge({ category }: FactorCategoryBadgeProps) {
  return (
    <span className="rounded-full border border-zinc-200 px-2 py-0.5 text-[11px] font-semibold text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
      {category}
    </span>
  );
}
