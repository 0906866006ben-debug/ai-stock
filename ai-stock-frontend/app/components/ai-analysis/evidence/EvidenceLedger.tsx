import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { EvidenceRow } from './EvidenceRow';

interface EvidenceLedgerProps {
  data: AIAnalysisResult;
}

/**
 * Layer 4: ranked evidence ledger with directional counts.
 */
export function EvidenceLedger({ data }: EvidenceLedgerProps) {
  const sorted = [...data.evidence_ledger].sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  const bullishCount = sorted.filter((e) => e.direction === 'bullish').length;
  const bearishCount = sorted.filter((e) => e.direction === 'bearish').length;
  const neutralCount = sorted.filter((e) => e.direction === 'neutral').length;

  return (
    <section className="rounded-xl border border-zinc-200 bg-white px-[22px] py-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Evidence
          </p>
          <h2 className="text-lg font-bold text-zinc-950 dark:text-zinc-50">
            證據鏈
          </h2>
        </div>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {sorted.length} 項共振因子（{bullishCount} 多 / {bearishCount} 空 / {neutralCount} 中性）
        </p>
      </div>
      <div className="mt-3">
        {sorted.map((item) => (
          <EvidenceRow key={item.id} item={item} />
        ))}
      </div>
    </section>
  );
}
