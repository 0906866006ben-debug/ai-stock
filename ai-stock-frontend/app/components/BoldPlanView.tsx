'use client';

import { useEffect, useMemo, useState } from 'react';

interface DatasetItem { name: string; label: string; paid: boolean }
interface QueryResult {
  dataset: string;
  status: string;
  msg?: string;
  total?: number;
  count: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

const apiBase = () => (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');

const STATUS_TONE: Record<string, string> = {
  ok: 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300',
  rate_limited: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200',
  ip_banned: 'border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300',
  param_error: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200',
  needs_paid_plan: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200',
  token_error: 'border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300',
  no_token: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200',
  empty_or_unauthorized: 'border-zinc-300 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300',
};

const STATUS_LABEL: Record<string, string> = {
  ok: '✅ 成功',
  rate_limited: '⏳ 流量上限（稍後再試）',
  ip_banned: '🚫 IP 暫時封鎖（約 30 分鐘）',
  param_error: '⚠️ 參數問題（看右方訊息）',
  needs_paid_plan: '💰 此資料集需更高方案',
  token_error: '🔑 token / 參數問題',
  no_token: '🔑 未設定 FINMIND_API_KEY',
  empty_or_unauthorized: '空資料或此資料集需付費方案',
  not_allowed: '此 dataset 不在允許清單',
  network_error: '🌐 連線錯誤',
  bad_response: '回應格式錯誤',
};

export default function BoldPlanView() {
  const [groups, setGroups] = useState<Record<string, DatasetItem[]>>({});
  const [dataset, setDataset] = useState('TaiwanStockPrice');
  const [dataId, setDataId] = useState('2330');
  // Most FinMind datasets require start_date (else HTTP 400). Pre-fill ~90 days ago.
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 90);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState('');
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${apiBase()}/tw/finmind/datasets`, { cache: 'no-store' });
        const data = await res.json();
        setGroups(data.groups || {});
      } catch {
        /* keep default dataset usable even if list fails */
      }
    })();
  }, []);

  const paidLookup = useMemo(() => {
    const m = new Map<string, boolean>();
    Object.values(groups).forEach((items) => items.forEach((it) => m.set(it.name, it.paid)));
    return m;
  }, [groups]);

  const runQuery = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const params = new URLSearchParams({ dataset });
      if (dataId.trim()) params.set('data_id', dataId.trim());
      if (startDate) params.set('start_date', startDate);
      if (endDate) params.set('end_date', endDate);
      const res = await fetch(`${apiBase()}/tw/finmind/query?${params.toString()}`, { cache: 'no-store' });
      setResult(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : '查詢失敗');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-purple-200 bg-gradient-to-r from-pink-50 to-purple-50 p-5 dark:border-purple-900/50 dark:from-pink-950/30 dark:to-purple-950/30">
        <h2 className="text-lg font-bold text-purple-700 dark:text-purple-300">🧪 大膽的計畫</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          FinMind 資料實驗室 ── 直接查任何資料集來試試看。token 留在後端、不外露；單次查詢不重試，不會觸發封鎖。
        </p>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
            資料集 (dataset)
            <select
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            >
              {Object.keys(groups).length === 0 && <option value="TaiwanStockPrice">TaiwanStockPrice</option>}
              {Object.entries(groups).map(([group, items]) => (
                <optgroup key={group} label={group}>
                  {items.map((it) => (
                    <option key={it.name} value={it.name}>
                      {it.label} ({it.name}){it.paid ? ' 💰付費' : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
            代號 (data_id)
            <input
              value={dataId}
              onChange={(e) => setDataId(e.target.value)}
              placeholder="2330"
              className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
            起始日 (多數資料集必填)
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
            結束日
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            />
          </label>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={runQuery}
            disabled={loading}
            className="rounded-full bg-gradient-to-r from-purple-500 to-fuchsia-500 px-5 py-2 text-sm font-semibold text-white shadow-md hover:from-purple-600 hover:to-fuchsia-600 disabled:opacity-60"
          >
            {loading ? '查詢中…' : '🔍 查詢'}
          </button>
          {paidLookup.get(dataset) && (
            <span className="text-xs text-amber-600 dark:text-amber-400">此資料集需 Backer/Sponsor 方案，免費 token 會回空</span>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-2.5 text-sm ${STATUS_TONE[result.status] || 'border-zinc-300 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300'}`}>
            <span className="font-semibold">{STATUS_LABEL[result.status] || result.status}</span>
            <span className="text-xs">
              {result.status === 'ok'
                ? `回傳 ${result.count} / 共 ${result.total ?? result.count} 筆`
                : result.msg}
            </span>
          </div>

          {result.status === 'ok' && result.rows.length > 0 && (
            <>
              <div className="flex items-center justify-end">
                <button
                  type="button"
                  onClick={() => setShowRaw((v) => !v)}
                  className="text-xs font-semibold text-purple-600 hover:text-purple-800 dark:text-purple-300"
                >
                  {showRaw ? '看表格' : '看原始 JSON'}
                </button>
              </div>
              {showRaw ? (
                <pre className="max-h-[28rem] overflow-auto rounded-xl border border-zinc-200 bg-zinc-950 p-3 text-xs text-zinc-100 dark:border-zinc-800">
                  {JSON.stringify(result.rows.slice(0, 100), null, 2)}
                </pre>
              ) : (
                <div className="max-h-[28rem] overflow-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full border-collapse text-xs">
                    <thead className="sticky top-0 bg-zinc-100 dark:bg-zinc-800">
                      <tr>
                        {result.columns.map((c) => (
                          <th key={c} className="whitespace-nowrap border-b border-zinc-200 px-2 py-1.5 text-left font-semibold text-zinc-700 dark:border-zinc-700 dark:text-zinc-200">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.slice(0, 200).map((row, i) => (
                        <tr key={i} className="odd:bg-white even:bg-zinc-50 dark:odd:bg-zinc-900 dark:even:bg-zinc-950/50">
                          {result.columns.map((c) => (
                            <td key={c} className="whitespace-nowrap border-b border-zinc-100 px-2 py-1 text-zinc-700 dark:border-zinc-800 dark:text-zinc-300">
                              {String(row[c] ?? '')}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {result.count > 200 && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">表格僅顯示前 200 筆（共回傳 {result.count} 筆）。</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
