'use client';

import { useEffect, useState } from 'react';
import { getTwEntryContext } from '@/lib/api';
import type { EntryContext, Expensiveness, EntryStructureStatus } from '@/lib/types';

const EXPENSIVE_STYLES: Record<Expensiveness, string> = {
  偏便宜: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  合理: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  偏貴: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  unknown: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
};

const STRUCT_STYLES: Record<EntryStructureStatus, string> = {
  intact: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  weakening: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  invalidated: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  unknown: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
};

const STRUCT_LABELS: Record<EntryStructureStatus, string> = {
  intact: '結構完整', weakening: '短期轉弱', invalidated: '結構失效', unknown: '未知',
};

const SUPPORT_LABELS: Record<string, string> = {
  dynamic_ma60: '季線 (60日)',
  dynamic_ma200: '年線 (200日)',
  structural_box_low: '盤整低 (箱底)',
  structural_neckline: '突破頸線',
};

function pct(v: number | undefined | null): string {
  return v === undefined || v === null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;
}

export default function EntryContextCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<EntryContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    getTwEntryContext(symbol)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((exc) => {
        if (!cancelled) setError(exc?.response?.data?.detail || (exc instanceof Error ? exc.message : '無法取得進場條件。'));
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  if (loading) {
    return <div className="rounded-2xl border border-zinc-200 bg-white p-5 text-sm text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">正在計算進場條件(估值/支撐/結構)…</div>;
  }
  if (error) {
    return <div className="rounded-2xl border border-zinc-200 bg-white p-5 text-sm text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">進場條件暫時無法取得:{error}</div>;
  }
  if (!data || data.current_price === null) return null;

  const exp = (data.expensiveness ?? 'unknown') as Expensiveness;
  const struct = (data.structure_status ?? 'unknown') as EntryStructureStatus;

  return (
    <div className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-zinc-950 dark:text-zinc-50">{data.current_price}</span>
          <span className="text-xs text-zinc-400 dark:text-zinc-500">目前價</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${EXPENSIVE_STYLES[exp]}`}>貴不貴:{exp}</span>
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${STRUCT_STYLES[struct]}`}>{STRUCT_LABELS[struct]}</span>
        </div>
      </div>

      {/* A 貴不貴 — extension + valuation */}
      <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">貴不貴(延伸度 + 估值百分位)</p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-zinc-700 dark:text-zinc-200 sm:grid-cols-3">
          <div>距20日線 <span className="font-medium">{pct(data.extension.pct_from_ma20)}</span></div>
          <div>距季線 <span className="font-medium">{pct(data.extension.pct_from_ma60)}</span></div>
          <div>距52週高 <span className="font-medium">{pct(data.extension.pct_from_52w_high)}</span></div>
          {data.valuation.pe !== undefined && (
            <div>PE <span className="font-medium">{data.valuation.pe}</span>
              {data.valuation.pe_percentile !== undefined && <span className="text-zinc-400"> ({data.valuation.pe_percentile}百分位)</span>}</div>
          )}
          {data.valuation.pb !== undefined && (
            <div>PB <span className="font-medium">{data.valuation.pb}</span>
              {data.valuation.pb_percentile !== undefined && <span className="text-zinc-400"> ({data.valuation.pb_percentile}百分位)</span>}</div>
          )}
        </div>
        {data.valuation.label === '偏貴' && data.extension.label !== '延伸過熱' && (
          <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">⚠ 技術面未過熱,但估值處於歷史高百分位 → 偏貴</p>
        )}
      </div>

      {/* B 等哪裡 — supports + confluence */}
      <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">等哪裡(支撐 / 回檔參考區)</p>
        {data.supports.length > 0 ? (
          <ul className="space-y-1 text-sm text-zinc-700 dark:text-zinc-200">
            {data.supports.map((s, i) => (
              <li key={i} className="flex items-center justify-between gap-2">
                <span>{SUPPORT_LABELS[s.kind] ?? s.kind}</span>
                <span><span className="font-medium">NT${s.price}</span> <span className="text-zinc-400">({pct(s.pct_below)})</span></span>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-zinc-400">目前無低於現價的支撐位</p>}
        {data.confluence_zones.length > 0 && (
          <div className="mt-2 rounded-lg bg-emerald-50 p-2 text-xs text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
            ◎ 高機率匯流支撐區:{data.confluence_zones.map((z) => `NT$${z.low}–${z.high} (${pct(z.pct_below)})`).join('、')}
          </div>
        )}
      </div>

      {/* C 能不能加 — structure gate */}
      <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">能不能加(結構閘門)</p>
        <p className="text-sm text-zinc-700 dark:text-zinc-200">{data.add_on_context.note}</p>
      </div>

      <p className="border-t border-zinc-100 pt-3 text-xs text-zinc-400 dark:border-zinc-800 dark:text-zinc-500">
        {data.data_quality.adjusted_available ? `還原股價計算(${data.data_quality.dividend_events ?? 0} 次除權息)` : '無除權息,使用原始股價'}
        ;均線/52週高用還原價、結構位用原始價。本資訊僅為條件參考,不構成投資建議。
      </p>
    </div>
  );
}
