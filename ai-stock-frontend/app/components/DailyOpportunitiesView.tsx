'use client';

import { useEffect, useState } from 'react';

interface OppItem {
  stock_id: string;
  name: string;
  close: number;
  change_pct?: number | null;
  industry?: string;
  grade: 'S' | 'A' | 'B' | 'C';
  basis: string;
  metrics: Record<string, unknown>;
}
interface Opportunities {
  status: string;
  date: string;
  universe_total?: number;
  buyable_count?: number;
  buckets?: { short: OppItem[]; mid: OppItem[]; long: OppItem[] };
  notices?: string[];
}

const apiBase = () => (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');

const GRADE_STYLE: Record<string, string> = {
  S: 'bg-purple-600 text-white',
  A: 'bg-emerald-600 text-white',
  B: 'bg-sky-600 text-white',
  C: 'bg-zinc-400 text-white',
};

const BUCKETS: { key: 'short' | 'mid' | 'long'; title: string; desc: string }[] = [
  {
    key: 'mid',
    title: '📈 中線桶（1–3 個月）',
    desc: '月營收 YoY 動能 × 法人連續買超（雙確認）。核心桶。',
  },
  {
    key: 'long',
    title: '🏦 長線桶（6–12 個月+）',
    desc: '價值綜合分位（益本比／殖利率／PBR）＋ 營收成長為正。',
  },
  {
    key: 'short',
    title: '⚡ 進場時點觀察（3–15 日）',
    desc: '非獨立策略——中線候選中出現短期事件觸發者（營收創高公告窗、外資大額買超）。',
  },
];

function GradeChip({ grade }: { grade: string }) {
  return (
    <span className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${GRADE_STYLE[grade] ?? GRADE_STYLE.C}`}>
      {grade}
    </span>
  );
}

export default function DailyOpportunitiesView({ onSelect }: { onSelect?: (code: string) => void }) {
  const [data, setData] = useState<Opportunities | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${apiBase()}/tw/daily-opportunities`, { cache: 'no-store' });
        setData(await r.json());
      } catch (e) {
        setErr(e instanceof Error ? e.message : '載入失敗');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-purple-200 bg-gradient-to-r from-pink-50 to-purple-50 p-5 dark:border-purple-900/50 dark:from-pink-950/30 dark:to-purple-950/30">
        <h2 className="text-lg font-bold text-purple-700 dark:text-purple-300">🎯 每日交易機會</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          依研究報告 v2 的三桶規則，列出符合條件的候選觀察名單與支持數據（S/A/B/C 分級）。
          {data?.date ? ` 資料日：${data.date}` : ''}
          {data?.buyable_count != null ? `　可買性篩查通過：${data.buyable_count}/${data.universe_total} 檔` : ''}
        </p>
      </div>

      {data?.notices && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          {data.notices.map((n, i) => (
            <p key={i}>⚠️ {n}</p>
          ))}
        </div>
      )}

      {loading && <p className="text-sm text-zinc-500">載入中…（首次計算全市場約需 10–60 秒）</p>}
      {err && (
        <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
          {err}
        </p>
      )}
      {data && data.status !== 'ok' && !loading && (
        <p className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          暫無資料（可能為非交易日或資料源暫時不可用）。
        </p>
      )}

      {data?.buckets &&
        BUCKETS.map(({ key, title, desc }) => {
          const items = data.buckets?.[key] ?? [];
          return (
            <section
              key={key}
              className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
            >
              <h3 className="text-base font-bold text-zinc-800 dark:text-zinc-100">{title}</h3>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{desc}</p>

              {items.length === 0 ? (
                <p className="mt-3 text-sm text-zinc-500">今日無符合條件的候選。</p>
              ) : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead>
                      <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500 dark:border-zinc-700">
                        <th className="py-1.5 pr-2">級</th>
                        <th className="py-1.5 pr-3">股票</th>
                        <th className="py-1.5 pr-3 text-right">收盤</th>
                        <th className="py-1.5 pr-3 text-right">漲跌</th>
                        <th className="py-1.5">符合條件（支持數據）</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it) => (
                        <tr
                          key={`${key}-${it.stock_id}`}
                          className="cursor-pointer border-b border-zinc-100 hover:bg-purple-50/60 dark:border-zinc-800 dark:hover:bg-purple-950/20"
                          onClick={() => onSelect?.(it.stock_id)}
                          title="點擊查看個股分析"
                        >
                          <td className="py-2 pr-2">
                            <GradeChip grade={it.grade} />
                          </td>
                          <td className="py-2 pr-3">
                            <span className="font-semibold text-zinc-800 dark:text-zinc-100">{it.stock_id}</span>{' '}
                            <span className="text-zinc-600 dark:text-zinc-300">{it.name}</span>
                            {it.industry ? (
                              <span className="ml-1 text-[10px] text-zinc-400">{it.industry}</span>
                            ) : null}
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums">{it.close.toLocaleString()}</td>
                          <td
                            className={`py-2 pr-3 text-right tabular-nums ${
                              (it.change_pct ?? 0) > 0
                                ? 'text-red-600 dark:text-red-400'
                                : (it.change_pct ?? 0) < 0
                                  ? 'text-green-600 dark:text-green-400'
                                  : 'text-zinc-500'
                            }`}
                          >
                            {it.change_pct != null ? `${it.change_pct > 0 ? '+' : ''}${it.change_pct}%` : '—'}
                          </td>
                          <td className="py-2 text-xs leading-5 text-zinc-600 dark:text-zinc-300">{it.basis}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          );
        })}
    </div>
  );
}
