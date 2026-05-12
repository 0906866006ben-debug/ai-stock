'use client';

import { useEffect, useState } from 'react';
import { getMarketOverview, MarketOverviewResponse } from '@/lib/api';
import type { EconomicIndicator } from '@/lib/types';

function IndicatorChip({ ind }: { ind: EconomicIndicator }) {
  const hasValue = ind.value != null;
  return (
    <div className="flex flex-col items-center rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800 min-w-[90px]">
      <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {ind.label}
      </span>
      <span className="mt-0.5 text-sm font-bold text-zinc-800 dark:text-zinc-100">
        {hasValue ? ind.value!.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}
      </span>
      {ind.date && (
        <span className="text-[10px] text-zinc-400 dark:text-zinc-500">
          {ind.date.slice(0, 7)}
        </span>
      )}
    </div>
  );
}

export default function MarketOverview() {
  const [data, setData] = useState<MarketOverviewResponse | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    getMarketOverview()
      .then(setData)
      .catch(() => null);
  }, []);

  if (!data) return null;

  const indicators = data.economic_indicators.filter((i) => i.value != null);
  if (indicators.length === 0 && data.top_stocks.length === 0) return null;

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-5 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Market Pulse
          </span>
          {data.data_source === 'live' && (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-700 dark:bg-green-900 dark:text-green-300">
              ● Live
            </span>
          )}
        </div>
        <span className="text-xs text-zinc-400">{open ? '▲ Hide' : '▼ Show'}</span>
      </button>

      {open && (
        <div className="border-t border-zinc-100 px-5 pb-5 dark:border-zinc-800">
          {/* Economic Indicators */}
          {indicators.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
                Economic Indicators
              </p>
              <div className="flex flex-wrap gap-2">
                {indicators.map((ind) => (
                  <IndicatorChip key={ind.name} ind={ind} />
                ))}
              </div>
            </div>
          )}

          {/* Top Stocks */}
          {data.top_stocks.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-400">
                Top US Stocks by Market Cap
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-medium uppercase text-zinc-400">
                      <th className="pb-2 pr-4">Symbol</th>
                      <th className="pb-2 pr-4">Company</th>
                      <th className="pb-2 pr-4 text-right">Price</th>
                      <th className="pb-2 pr-4 text-right">Market Cap</th>
                      <th className="pb-2 text-right">Sector</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {data.top_stocks.slice(0, 8).map((s) => (
                      <tr key={s.symbol} className="text-zinc-700 dark:text-zinc-300">
                        <td className="py-1.5 pr-4 font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                          {s.symbol}
                        </td>
                        <td className="py-1.5 pr-4 max-w-[140px] truncate">{s.company_name}</td>
                        <td className="py-1.5 pr-4 text-right">
                          {s.price != null ? `$${s.price.toFixed(2)}` : '—'}
                        </td>
                        <td className="py-1.5 pr-4 text-right">
                          {s.market_cap != null
                            ? s.market_cap >= 1e12
                              ? `$${(s.market_cap / 1e12).toFixed(2)}T`
                              : `$${(s.market_cap / 1e9).toFixed(2)}B`
                            : '—'}
                        </td>
                        <td className="py-1.5 text-right text-xs text-zinc-400">{s.sector ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
