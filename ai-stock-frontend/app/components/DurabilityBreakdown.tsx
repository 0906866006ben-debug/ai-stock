'use client';

import type { DurabilityComponents, DurabilityMetrics } from '@/lib/types';

interface Props {
  metrics: DurabilityMetrics | null | undefined;
}

const COMPONENT_LABELS: { keys: string[]; label: string }[] = [
  { keys: ['op_margin_stability'], label: '營業利益率穩定' },
  { keys: ['roe_quality', 'roe_trend'], label: 'ROE 品質' },
  { keys: ['multiyear_consistency', 'multi_year_consistency'], label: '多年 EPS 一致性' },
  { keys: ['earnings_purity'], label: '本業獲利純度' },
  { keys: ['inst_continuity', 'institutional_flow'], label: '法人連續性' },
  { keys: ['cfo_quality'], label: '現金流品質' },
  { keys: ['partial_fscore', 'f_score_partial'], label: 'Piotroski 部分分數' },
];

function pickComponent(components: DurabilityComponents, keys: string[]): number | null {
  for (const key of keys) {
    const value = components[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function tone(value: number): string {
  if (value >= 0.7) return 'bg-emerald-500';
  if (value >= 0.4) return 'bg-amber-500';
  return 'bg-rose-500';
}

function trendText(trend: DurabilityMetrics['trend'], change: number | null): string {
  const delta = typeof change === 'number' ? `${change >= 0 ? '+' : ''}${change.toFixed(1)}` : null;
  if (trend === 'improving') return delta ? `改善 ${delta}` : '改善';
  if (trend === 'declining') return delta ? `下降 ${delta}` : '下降';
  if (trend === 'stable') return delta ? `穩定 ${delta}` : '穩定';
  return '趨勢資料不足';
}

export default function DurabilityBreakdown({ metrics }: Props) {
  if (!metrics || metrics.score == null) {
    return (
      <div className="border-t border-zinc-200 pt-4 text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
        耐久度分數暫無足夠資料。
      </div>
    );
  }

  const score = Math.max(0, Math.min(100, metrics.score));
  const rows = COMPONENT_LABELS.map((item) => ({
    label: item.label,
    value: pickComponent(metrics.components || {}, item.keys),
  }));

  return (
    <div className="border-t border-zinc-200 pt-4 dark:border-zinc-700">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Quality & Durability
          </p>
          <h3 className="mt-1 text-base font-semibold text-zinc-900 dark:text-zinc-50">
            品質耐久度
          </h3>
        </div>
        <div className="text-right">
          <p className="font-mono text-2xl font-bold text-zinc-900 dark:text-zinc-50">{score.toFixed(0)}</p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            信心 {Math.round(metrics.confidence ?? 0)}% · {trendText(metrics.trend, metrics.change_yoy)}
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {rows.map(({ label, value }) => (
          <div key={label} className="grid grid-cols-[7.5rem_1fr_3rem] items-center gap-3 text-sm">
            <span className="text-zinc-600 dark:text-zinc-300">{label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
              {value == null ? null : (
                <div className={`h-full rounded-full ${tone(value)}`} style={{ width: `${Math.round(value * 100)}%` }} />
              )}
            </div>
            <span className="text-right font-mono text-xs text-zinc-500 dark:text-zinc-400">
              {value == null ? '-' : `${Math.round(value * 100)}`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
