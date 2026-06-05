'use client';

import { useEffect, useMemo, useState } from 'react';
import { getQualitySnapshot, listQualityWatchQuarters } from '@/lib/api';
import type { QualityWatchHistoryItem, QuarterlySnapshot, SnapshotStock } from '@/lib/types';

interface Props {
  onSelect: (code: string, name: string) => void;
  onAddToWatchlist: (code: string, name: string) => void;
}

function scoreTone(score: number): string {
  if (score >= 70) return 'bg-emerald-500';
  if (score >= 50) return 'bg-amber-500';
  return 'bg-rose-500';
}

function clampScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, score));
}

function fmt(n: number | null | undefined, digits = 0): string {
  if (n == null || !Number.isFinite(n)) return '-';
  return n.toLocaleString('zh-TW', { maximumFractionDigits: digits });
}

function topComponents(stock: SnapshotStock): string {
  return Object.entries(stock.durability_components || {})
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([key, value]) => `${key.replaceAll('_', ' ')} ${Math.round(value * 100)}`)
    .join(' · ');
}

export default function QualityWatchTab({ onSelect, onAddToWatchlist }: Props) {
  const [history, setHistory] = useState<QualityWatchHistoryItem[]>([]);
  const [selectedQuarter, setSelectedQuarter] = useState<string>('latest');
  const [snapshot, setSnapshot] = useState<QuarterlySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>('desc');

  useEffect(() => {
    let cancelled = false;
    listQualityWatchQuarters()
      .then((items) => {
        if (!cancelled) setHistory(items);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getQualitySnapshot(selectedQuarter === 'latest' ? undefined : selectedQuarter)
      .then((data) => {
        if (!cancelled) setSnapshot(data);
      })
      .catch(() => {
        if (!cancelled) {
          setSnapshot(null);
          setError('尚未產生季度品質清單');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedQuarter]);

  const rows = useMemo(() => {
    return (snapshot?.snapshot_stocks ?? []).slice().sort((a, b) => (
      sortDir === 'desc'
        ? clampScore(b.durability_score) - clampScore(a.durability_score)
        : clampScore(a.durability_score) - clampScore(b.durability_score)
    ));
  }, [snapshot, sortDir]);

  const generatedAtMs = snapshot ? new Date(snapshot.generated_at).getTime() : NaN;
  const isStale = Number.isFinite(generatedAtMs)
    ? Date.now() - generatedAtMs > 1000 * 60 * 60 * 24 * 183
    : false;

  function exportCsv() {
    if (!snapshot) return;
    const header = ['symbol', 'name', 'durability_score', 'confidence', 'sector', 'price_at_snapshot'];
    const lines = [
      header.join(','),
      ...rows.map((stock) => [
        stock.symbol,
        `"${stock.name.replaceAll('"', '""')}"`,
        stock.durability_score,
        stock.confidence,
        stock.sector ?? '',
        stock.price_at_snapshot ?? '',
      ].join(',')),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `quality_watch_${snapshot.quarter}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">季度品質清單</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {snapshot ? `${snapshot.as_of_date} · ${snapshot.snapshot_stocks.length} 檔` : 'Quality Watch'}
            {isStale ? ' · 資料超過 6 個月' : ''}
            {snapshot?.status === 'no_data' ? ' · 資料來源暫無資料' : ''}
          </p>
          {snapshot?.warnings?.length ? (
            <p className="mt-1 text-xs text-amber-600 dark:text-amber-300">{snapshot.warnings[0]}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedQuarter}
            onChange={(event) => setSelectedQuarter(event.target.value)}
            className="rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
          >
            <option value="latest">Latest</option>
            {history.map((item) => (
              <option key={item.quarter} value={item.quarter}>
                {item.quarter} ({item.stock_count})
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))}
            className="rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            分數 {sortDir === 'desc' ? '高到低' : '低到高'}
          </button>
          <button
            type="button"
            onClick={exportCsv}
            disabled={!snapshot}
            className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            CSV
          </button>
        </div>
      </div>

      {loading ? (
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
          載入中...
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
          {error}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <table className="w-full text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                {['股票', 'Quality', 'Top components', 'Sector', 'Price', ''].map((header) => (
                  <th key={header} className="px-3 py-2 text-left text-xs font-medium text-zinc-500 dark:text-zinc-400">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {rows.map((stock) => {
                const score = clampScore(stock.durability_score);
                return (
                  <tr key={stock.symbol} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                    <td className="px-3 py-2">
                      <button type="button" onClick={() => onSelect(stock.symbol, stock.name)} className="text-left">
                        <div className="font-mono font-semibold text-zinc-900 dark:text-zinc-50">{stock.symbol}</div>
                        <div className="text-xs text-zinc-500">{stock.name}</div>
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex min-w-24 items-center gap-2">
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
                          <div className={`h-full ${scoreTone(score)}`} style={{ width: `${score}%` }} />
                        </div>
                        <span className="w-8 text-right font-mono">{Math.round(score)}</span>
                      </div>
                    </td>
                    <td className="max-w-[22rem] px-3 py-2 text-xs text-zinc-500 dark:text-zinc-400">
                      {topComponents(stock) || '-'}
                    </td>
                    <td className="px-3 py-2 text-xs text-zinc-500 dark:text-zinc-400">{stock.sector ?? '-'}</td>
                    <td className="px-3 py-2 font-mono">{fmt(stock.price_at_snapshot, 2)}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => onAddToWatchlist(stock.symbol, stock.name)}
                        className="rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                      >
                        加自選
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
