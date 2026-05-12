import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { CrossHorizonBadge } from './CrossHorizonBadge';
import { HorizonCard } from './HorizonCard';

interface ThreeHorizonViewProps {
  data: AIAnalysisResult;
}

/**
 * Layer 2: three horizons remain parallel so the UI never collapses distinct
 * trading timeframes into one answer.
 */
export function ThreeHorizonView({ data }: ThreeHorizonViewProps) {
  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Three Horizons
          </p>
          <h2 className="text-lg font-bold text-zinc-950 dark:text-zinc-50">
            三時序判讀
          </h2>
        </div>
        <CrossHorizonBadge state={data.cross_horizon_state} />
      </div>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <HorizonCard view={data.horizons.short_term} />
        <HorizonCard view={data.horizons.swing} />
        <HorizonCard view={data.horizons.long_term} />
      </div>
    </section>
  );
}
