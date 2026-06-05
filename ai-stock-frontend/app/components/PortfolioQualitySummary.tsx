'use client';

import type { DurabilityMetrics, Position } from '@/lib/types';

interface Props {
  positions: Position[];
  qualityByCode: Record<string, DurabilityMetrics | null>;
}

function tier(score: number): 'excellent' | 'good' | 'fair' | 'poor' {
  if (score >= 75) return 'excellent';
  if (score >= 60) return 'good';
  if (score >= 40) return 'fair';
  return 'poor';
}

function fmt(score: number | null): string {
  return score == null ? '-' : score.toFixed(0);
}

export default function PortfolioQualitySummary({ positions, qualityByCode }: Props) {
  const scored = positions
    .map((pos) => ({ pos, score: qualityByCode[pos.stock_code]?.score ?? null }))
    .filter((item): item is { pos: Position; score: number } => typeof item.score === 'number');
  const missing = positions.length - scored.length;
  const avg = scored.length ? scored.reduce((sum, item) => sum + item.score, 0) / scored.length : null;
  const counts = { excellent: 0, good: 0, fair: 0, poor: 0 };
  scored.forEach((item) => {
    counts[tier(item.score)] += 1;
  });
  const highest = scored.slice().sort((a, b) => b.score - a.score)[0];
  const lowest = scored.slice().sort((a, b) => a.score - b.score)[0];
  const total = Math.max(scored.length, 1);

  return (
    <div className="rounded-2xl border border-pink-100 bg-white p-4 shadow-sm dark:border-pink-900/30 dark:bg-zinc-900">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">Portfolio Quality</h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {missing > 0 ? `${missing} 檔暫無品質資料` : '持股品質資料已更新'}
          </p>
        </div>
        <div className="text-right">
          <p className="font-mono text-2xl font-bold text-pink-600 dark:text-pink-300">{fmt(avg)}</p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">平均</p>
        </div>
      </div>

      <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div className="bg-emerald-500" style={{ width: `${(counts.excellent / total) * 100}%` }} />
        <div className="bg-lime-500" style={{ width: `${(counts.good / total) * 100}%` }} />
        <div className="bg-amber-500" style={{ width: `${(counts.fair / total) * 100}%` }} />
        <div className="bg-rose-500" style={{ width: `${(counts.poor / total) * 100}%` }} />
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2 text-center text-xs">
        {[
          ['優', counts.excellent, 'text-emerald-600'],
          ['良', counts.good, 'text-lime-600'],
          ['中', counts.fair, 'text-amber-600'],
          ['弱', counts.poor, 'text-rose-600'],
        ].map(([label, count, color]) => (
          <div key={label} className="rounded-lg bg-zinc-50 px-2 py-1 dark:bg-zinc-800/70">
            <p className={`font-semibold ${color}`}>{count}</p>
            <p className="text-zinc-500 dark:text-zinc-400">{label}</p>
          </div>
        ))}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-zinc-600 dark:text-zinc-300">
        <div>
          <p className="text-zinc-400">最高</p>
          <p className="mt-0.5 font-medium">{highest ? `${highest.pos.stock_code} · ${fmt(highest.score)}` : '-'}</p>
        </div>
        <div>
          <p className="text-zinc-400">最低</p>
          <p className="mt-0.5 font-medium">{lowest ? `${lowest.pos.stock_code} · ${fmt(lowest.score)}` : '-'}</p>
        </div>
      </div>
    </div>
  );
}
