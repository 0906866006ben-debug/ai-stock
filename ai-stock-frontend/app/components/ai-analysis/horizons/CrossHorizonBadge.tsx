import type { CrossHorizonState } from '@/types/aiAnalysis';
import { CROSS_HORIZON_META } from '@/lib/ai-analysis/constants';

interface CrossHorizonBadgeProps {
  state: CrossHorizonState;
}

/**
 * Topic B cross-horizon state badge.
 */
export function CrossHorizonBadge({ state }: CrossHorizonBadgeProps) {
  const meta = CROSS_HORIZON_META[state];

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm dark:border-blue-800 dark:bg-blue-950/60">
      <span className="font-semibold text-blue-800 dark:text-blue-200">{meta.label}</span>
      <span className="ml-2 text-blue-700 dark:text-blue-300">{meta.action_hint}</span>
    </div>
  );
}
