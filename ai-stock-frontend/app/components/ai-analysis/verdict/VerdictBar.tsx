import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { CROSS_HORIZON_META, DATA_QUALITY_LABELS } from '@/lib/ai-analysis/constants';
import { DirectionPill } from '../shared/DirectionPill';
import { ThreeAxisScoreBar } from './ThreeAxisScoreBar';

interface VerdictBarProps {
  data: AIAnalysisResult;
}

/**
 * Layer 1 verdict: the 10-second read for direction, scores, and one-line thesis.
 */
export function VerdictBar({ data }: VerdictBarProps) {
  const meta = CROSS_HORIZON_META[data.cross_horizon_state];
  const changeTone = data.price_change_pct >= 0
    ? 'text-emerald-600 dark:text-emerald-300'
    : 'text-red-600 dark:text-red-300';

  return (
    <section className="rounded-xl border border-zinc-200 bg-white px-[22px] py-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-bold text-zinc-950 dark:text-zinc-50">
              {data.symbol_name}
            </h2>
            <span className="text-sm font-semibold text-zinc-500 dark:text-zinc-400">
              {data.symbol}
            </span>
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              {data.sector_tag}
            </span>
            <DirectionPill direction={data.overall_direction} />
            <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800 dark:border-blue-800 dark:bg-blue-950/60 dark:text-blue-200">
              {meta.label}
            </span>
          </div>

          <p className="mt-3 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {data.one_line_summary}
          </p>

          <div className="mt-4 rounded-lg border border-zinc-200 bg-zinc-50 px-[22px] py-5 dark:border-zinc-700 dark:bg-zinc-950/60">
            <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {meta.label}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
              {meta.description}。{meta.action_hint}
            </p>
          </div>
        </div>

        <div className="w-full shrink-0 space-y-3 lg:w-[360px]">
          <div className="flex items-end justify-between gap-3">
            <div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">現價</p>
              <p className="text-2xl font-bold text-zinc-950 dark:text-zinc-50">
                {data.current_price.toFixed(2)}
              </p>
            </div>
            <div className="text-right">
              <p className={`text-sm font-semibold ${changeTone}`}>
                {data.price_change_pct >= 0 ? '+' : ''}{data.price_change_pct.toFixed(2)}%
              </p>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">
                {DATA_QUALITY_LABELS[data.data_quality]}
              </p>
            </div>
          </div>
          <ThreeAxisScoreBar scores={data.overall_scores} />
          {data.overall_scores.confidence_cap_reason && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              {data.overall_scores.confidence_cap_reason}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
