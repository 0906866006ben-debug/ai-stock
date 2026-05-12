'use client';

import { useEffect, useState } from 'react';
import { getEarningsCalendar } from '@/lib/api';
import type { EarningsEvent } from '@/lib/types';

interface Props {
  symbol?: string;
}

export default function EarningsCalendar({ symbol }: Props) {
  const [events, setEvents] = useState<EarningsEvent[]>([]);
  const [dataSource, setDataSource] = useState('mock');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getEarningsCalendar(symbol)
      .then((r) => {
        setEvents(r.events);
        setDataSource(r.data_source);
      })
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [symbol]);

  const past = events.filter((e) => !e.is_upcoming);
  const upcoming = events.filter((e) => e.is_upcoming);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          法說 / 財報行事曆
          {symbol && <span className="ml-2 font-normal text-zinc-400">{symbol}</span>}
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-xs ${
          dataSource === 'live'
            ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
            : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
        }`}>
          ● {dataSource}
        </span>
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : events.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-400">無資料</p>
      ) : (
        <div className="space-y-4">
          {/* Upcoming windows */}
          <div>
            <p className="mb-2 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              📅 即將公布
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {upcoming.map((e, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-2 dark:border-blue-900 dark:bg-blue-950/30"
                >
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                      {e.fiscal_year} Q{e.fiscal_quarter}
                    </span>
                    <span className="text-xs text-zinc-500">
                      截止：{e.deadline}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Past filings (with EPS) */}
          {past.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-zinc-500 dark:text-zinc-400">
                📊 已公布
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-zinc-200 dark:border-zinc-800">
                    <tr className="text-left text-xs text-zinc-500">
                      <th className="px-2 py-1.5">期別</th>
                      <th className="px-2 py-1.5">公布日</th>
                      <th className="px-2 py-1.5 text-right">EPS (NTD)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {past.map((e, i) => (
                      <tr key={i}>
                        <td className="px-2 py-1.5 font-medium">
                          {e.fiscal_year} Q{e.fiscal_quarter}
                        </td>
                        <td className="px-2 py-1.5 font-mono text-zinc-500 dark:text-zinc-400">
                          {e.actual_filing_date ?? '-'}
                        </td>
                        <td className={`px-2 py-1.5 text-right font-mono ${
                          (e.eps ?? 0) >= 0 ? 'text-red-500' : 'text-green-600'
                        }`}>
                          {e.eps != null ? e.eps.toFixed(2) : '-'}
                        </td>
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
