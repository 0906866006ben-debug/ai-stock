'use client';

import { useEffect, useState } from 'react';

interface Sector {
  sector: string;
  count: number;
  up: number;
  down: number;
  avg_change_pct: number;
  turnover: number;
}
interface Mover { stock_id: string; name?: string; sector?: string; change_pct: number }
interface Heatmap {
  status: string;
  date: string;
  sectors: Sector[];
  top_gainers?: Mover[];
  top_losers?: Mover[];
}

const apiBase = () => (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');

function tone(chg: number): string {
  const c = Math.max(-3, Math.min(3, chg));
  const a = 0.18 + (Math.abs(c) / 3) * 0.55;
  return c >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`;
}

export default function MarketHeatmapView() {
  const [data, setData] = useState<Heatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${apiBase()}/tw/market/heatmap`, { cache: 'no-store' });
        setData(await r.json());
      } catch (e) {
        setErr(e instanceof Error ? e.message : '載入失敗');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const maxTurnover = Math.max(1, ...(data?.sectors ?? []).map((s) => s.turnover));

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-purple-200 bg-gradient-to-r from-pink-50 to-purple-50 p-5 dark:border-purple-900/50 dark:from-pink-950/30 dark:to-purple-950/30">
        <h2 className="text-lg font-bold text-purple-700 dark:text-purple-300">🗺️ 板塊熱力圖</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          各產業最新一日平均漲跌（依本地股價庫計算，色深＝漲跌幅、面積＝成交額）。{data?.date ? ` 資料日：${data.date}` : ''}
        </p>
      </div>

      {loading && <p className="text-sm text-zinc-500">載入中…</p>}
      {err && <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">{err}</p>}
      {data && data.status !== 'ok' && !loading && (
        <p className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          暫無資料（本地股價庫可能尚未下載，或當日無資料）。
        </p>
      )}

      {data && data.status === 'ok' && (
        <>
          <div className="flex flex-wrap gap-1.5">
            {data.sectors.map((s) => (
              <div
                key={s.sector}
                style={{ flex: `${1 + (s.turnover / maxTurnover) * 6} 1 110px`, backgroundColor: tone(s.avg_change_pct) }}
                className="min-h-[78px] rounded-lg p-2 text-zinc-900"
                title={`${s.sector}：${s.count} 檔，漲 ${s.up} / 跌 ${s.down}`}
              >
                <div className="text-xs font-semibold leading-tight">{s.sector}</div>
                <div className="mt-1 text-lg font-bold">{s.avg_change_pct >= 0 ? '+' : ''}{s.avg_change_pct}%</div>
                <div className="text-[11px] opacity-80">{s.count} 檔 · 漲{s.up}/跌{s.down}</div>
              </div>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <MoverList title="📈 漲幅前 10" movers={data.top_gainers ?? []} positive />
            <MoverList title="📉 跌幅前 10" movers={data.top_losers ?? []} positive={false} />
          </div>
        </>
      )}
    </div>
  );
}

function MoverList({ title, movers, positive }: { title: string; movers: Mover[]; positive: boolean }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-200">{title}</div>
      <div className="space-y-1">
        {movers.map((m) => (
          <div key={m.stock_id} className="flex items-center justify-between gap-2 text-sm">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-medium text-zinc-700 dark:text-zinc-200">{m.stock_id}{m.name ?? ''}</span>
              {m.sector && <span className="shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">{m.sector}</span>}
            </span>
            <span className={`shrink-0 ${positive ? 'text-green-600' : 'text-red-500'}`}>
              {m.change_pct >= 0 ? '+' : ''}{m.change_pct}%
            </span>
          </div>
        ))}
        {movers.length === 0 && <p className="text-xs text-zinc-400">—</p>}
      </div>
    </div>
  );
}
