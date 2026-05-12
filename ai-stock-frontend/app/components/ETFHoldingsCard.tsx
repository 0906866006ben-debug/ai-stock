'use client';

import type { ETFHoldingsResponse } from '@/lib/types';

const SECTOR_PALETTE = [
  '#3b82f6', '#8b5cf6', '#ec4899', '#f97316', '#22c55e',
  '#06b6d4', '#eab308', '#ef4444', '#71717a',
];

interface Props {
  data: ETFHoldingsResponse;
}

export default function ETFHoldingsCard({ data }: Props) {
  if (data.status === 'unsupported') {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          ETF 持股明細
        </h3>
        <p className="mt-2 text-sm text-zinc-400">
          此 ETF（{data.symbol}）暫不支援持股明細。
        </p>
      </div>
    );
  }

  const maxWeight = Math.max(1, ...data.holdings.map((h) => h.weight_pct ?? 0));

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-3 flex items-baseline justify-between">
          <div>
            <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              ETF 持股明細
            </h3>
            {data.fund_name && (
              <p className="text-xs text-zinc-500">
                {data.fund_name}
                {data.total_constituents && ` · ${data.total_constituents} 檔成分股`}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {data.last_updated && (
              <span className="text-xs text-zinc-400">更新：{data.last_updated}</span>
            )}
            <span className={`rounded-full px-2 py-0.5 text-xs ${
              data.status === 'live'
                ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
            }`}>
              ● {data.status}
            </span>
          </div>
        </div>

        {/* Top holdings as horizontal bars */}
        <div className="space-y-2">
          {data.holdings.map((h, i) => {
            const w = h.weight_pct ?? 0;
            return (
              <div key={i} className="flex items-center gap-3">
                <div className="w-24 shrink-0">
                  <div className="font-mono text-xs font-medium text-zinc-700 dark:text-zinc-200">
                    {h.stock_code ?? '-'}
                  </div>
                  <div className="text-xs text-zinc-500 truncate">{h.company_name}</div>
                </div>
                <div className="relative flex-1 h-5 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
                  <div
                    className="h-full bg-blue-500 transition-all"
                    style={{ width: `${(w / maxWeight) * 100}%` }}
                  />
                </div>
                <div className="w-12 shrink-0 text-right font-mono text-xs text-zinc-700 dark:text-zinc-300">
                  {w.toFixed(1)}%
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sector weights */}
      {data.sector_weights.length > 0 && (
        <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            產業權重
          </h3>
          <div className="flex h-3 overflow-hidden rounded-full">
            {data.sector_weights.map((s, i) => (
              <div
                key={i}
                title={`${s.sector} ${s.weight_pct.toFixed(1)}%`}
                style={{
                  width: `${s.weight_pct}%`,
                  backgroundColor: SECTOR_PALETTE[i % SECTOR_PALETTE.length],
                }}
              />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {data.sector_weights.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span
                  className="h-2.5 w-2.5 rounded-sm shrink-0"
                  style={{ backgroundColor: SECTOR_PALETTE[i % SECTOR_PALETTE.length] }}
                />
                <span className="text-zinc-600 dark:text-zinc-300">{s.sector}</span>
                <span className="ml-auto font-mono text-zinc-500">
                  {s.weight_pct.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
