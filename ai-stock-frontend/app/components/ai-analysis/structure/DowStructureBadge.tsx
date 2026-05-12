import type { DowTrendStructure } from '@/types/aiAnalysis';
import { DOW_STRUCTURE_LABELS } from '@/lib/ai-analysis/i18n';

interface DowStructureBadgeProps {
  structure: DowTrendStructure;
}

/**
 * Topic D Dow structure badge.
 */
export function DowStructureBadge({ structure }: DowStructureBadgeProps) {
  const bullish = structure.includes('bullish') || structure === 'bos_up';
  const bearish = structure.includes('bearish') || structure === 'bos_down';
  const tone = bullish
    ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
    : bearish
      ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200'
      : 'border-zinc-200 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200';

  return (
    <div className={`rounded-lg border px-[22px] py-5 ${tone}`}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-80">Dow Structure</p>
      <p className="mt-1 text-base font-bold">{DOW_STRUCTURE_LABELS[structure]}</p>
      <p className="mt-1 text-xs opacity-80">
        {bullish ? 'HH/HL 結構仍有延續性' : bearish ? 'LH/LL 或破壞結構需提高警覺' : '尚未形成清楚結構'}
      </p>
    </div>
  );
}
