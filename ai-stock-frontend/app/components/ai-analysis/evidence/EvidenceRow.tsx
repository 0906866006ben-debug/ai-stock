import type { EvidenceItem } from '@/types/aiAnalysis';
import { SourceTag } from '../shared/SourceTag';
import { WeightPill } from '../shared/WeightPill';
import { InfoTooltip } from '../shared/InfoTooltip';
import { FactorCategoryBadge } from './FactorCategoryBadge';

interface EvidenceRowProps {
  item: EvidenceItem;
}

/**
 * Layer 4 evidence row: every row shows source, quantitative detail, and weight.
 */
export function EvidenceRow({ item }: EvidenceRowProps) {
  const traceLabel = item.trace
    ? `${item.trace.reason_text}；${item.trace.calculation}；${item.trace.calculation_value}`
    : item.detail;

  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 border-b border-zinc-100 py-3 last:border-b-0 dark:border-zinc-800 md:grid-cols-[auto_minmax(0,1fr)_auto]">
      <SourceTag source={item.source} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <InfoTooltip label={traceLabel}>
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {item.title}
            </h3>
          </InfoTooltip>
          <FactorCategoryBadge category={item.factor_category ?? 'STRUCTURE'} />
        </div>
        <p className="mt-1 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
          {item.detail}
        </p>
        {item.backtest_hit_rate != null && (
          <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
            歷史命中率 {Math.round(item.backtest_hit_rate * 100)}% / 樣本 {item.backtest_sample_size ?? '-'}
          </p>
        )}
        <div className="mt-2 md:hidden">
          <WeightPill weight={item.weight} />
        </div>
      </div>
      <div className="hidden md:block">
        <WeightPill weight={item.weight} />
      </div>
    </div>
  );
}
