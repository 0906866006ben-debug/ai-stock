'use client';

import { useEffect, useState } from 'react';
import { getDividendCalendar } from '@/lib/api';
import type { DividendEvent } from '@/lib/types';

const TYPE_LABELS: Record<string, string> = {
  cash: '現金股利',
  stock: '股票股利',
  mixed: '現金+股票',
};

const TYPE_COLORS: Record<string, string> = {
  cash: 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  stock: 'bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
  mixed: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
};

interface Props {
  symbol?: string;
}

function todayPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function DividendCalendar({ symbol }: Props) {
  const [events, setEvents] = useState<DividendEvent[]>([]);
  const [dataSource, setDataSource] = useState('mock');
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(90);

  useEffect(() => {
    setLoading(true);
    const start = todayPlus(0);
    const end = todayPlus(days);
    getDividendCalendar({ symbol, start, end })
      .then((r) => {
        setEvents(r.events);
        setDataSource(r.data_source);
      })
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [symbol, days]);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          除息行事曆
          {symbol && <span className="ml-2 font-normal text-zinc-400">{symbol}</span>}
        </h3>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value))}
            className="rounded border border-zinc-300 bg-white px-2 py-0.5 text-xs dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          >
            <option value={30}>30 天</option>
            <option value={90}>90 天</option>
            <option value={180}>180 天</option>
          </select>
          <span className={`rounded-full px-2 py-0.5 text-xs ${
            dataSource === 'live'
              ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
          }`}>
            ● {dataSource}
          </span>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : events.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-400">此期間無除息事件</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-zinc-200 dark:border-zinc-800">
              <tr className="text-left text-xs text-zinc-500">
                <th className="px-2 py-2">代碼</th>
                <th className="px-2 py-2">類型</th>
                <th className="px-2 py-2">除息日</th>
                <th className="px-2 py-2 text-right">現金股利</th>
                <th className="px-2 py-2 text-right">股票股利</th>
                <th className="px-2 py-2">發放日</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {events.map((e, i) => (
                <tr key={i} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                  <td className="px-2 py-2">
                    <div className="font-mono font-medium text-zinc-800 dark:text-zinc-100">
                      {e.stock_code}
                    </div>
                    {e.company_name && (
                      <div className="text-xs text-zinc-400">{e.company_name}</div>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${TYPE_COLORS[e.type] ?? TYPE_COLORS.cash}`}>
                      {TYPE_LABELS[e.type] ?? e.type}
                    </span>
                  </td>
                  <td className="px-2 py-2 font-mono text-zinc-600 dark:text-zinc-300">
                    {e.ex_date ?? '-'}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">
                    {e.cash_per_share != null ? e.cash_per_share.toFixed(2) : '-'}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">
                    {e.stock_per_share != null && e.stock_per_share > 0
                      ? e.stock_per_share.toFixed(2)
                      : '-'}
                  </td>
                  <td className="px-2 py-2 font-mono text-zinc-500 dark:text-zinc-400">
                    {e.payment_date ?? '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
