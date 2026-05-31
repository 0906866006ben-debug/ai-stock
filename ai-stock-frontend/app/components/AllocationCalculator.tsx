'use client';

import { useState } from 'react';
import type { FormEvent } from 'react';
import { postTwAllocation } from '@/lib/api';
import type { AllocationResult } from '@/lib/types';

const NT = (n: number | undefined | null) =>
  n === undefined || n === null ? '—' : `NT$${Math.round(n).toLocaleString('zh-TW')}`;
const PCT = (n: number | undefined | null) =>
  n === undefined || n === null ? '—' : `${(n * 100).toFixed(1)}%`;

const FLAG_LABELS: Record<string, string> = {
  Armed_Intact: '結構完整·可加碼觀察',
  Armed_Weakening: '結構轉弱·謹慎觀察',
  Invalidated_Frozen: '結構失效·凍結(不加碼)',
  Insufficient_Friction_Margin: '金額過小·成本不划算(略過)',
};

export default function AllocationCalculator({ defaultSymbols = '' }: { defaultSymbols?: string }) {
  const [capital, setCapital] = useState('3000000');
  const [reserve, setReserve] = useState('20');
  const [maxPos, setMaxPos] = useState('30');
  const [sectorLimit, setSectorLimit] = useState('50');
  const [symbols, setSymbols] = useState(defaultSymbols);
  const [result, setResult] = useState<AllocationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e?: FormEvent<HTMLFormElement>) {
    e?.preventDefault();
    const syms = symbols.split(/[\s,]+/).map((s) => s.trim()).filter((s) => /^\d{4,6}$/.test(s));
    if (syms.length === 0) {
      setError('請輸入至少一檔 4–6 位數台股代號(空白或逗號分隔)。');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await postTwAllocation({
        symbols: syms,
        portfolio_parameters: {
          total_capital_ntd: Number(capital) || 0,
          reserve_pct: (Number(reserve) || 0) / 100,
          max_position_pct: (Number(maxPos) || 0) / 100,
          sector_limit_pct: (Number(sectorLimit) || 0) / 100,
        },
      });
      setResult(res);
    } catch (exc) {
      const detail = (exc as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || (exc instanceof Error ? exc.message : '計算失敗。'));
    } finally {
      setLoading(false);
    }
  }

  const d = result?.risk_dashboard;

  return (
    <div className="space-y-5 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Capital Allocation</p>
        <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">資金分配計算機</h2>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          依品質調整風險平價(QWRP)配置張數,並預留資金做結構式遞減加碼梯。這是依你輸入的算術結果,非投資建議。
        </p>
      </div>

      <form onSubmit={run} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="text-sm">總資金 (NT$)
          <input value={capital} onChange={(e) => setCapital(e.target.value)} inputMode="numeric"
            className="mt-1 w-full rounded-lg border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-950" />
        </label>
        <label className="text-sm">預留加碼 %
          <input value={reserve} onChange={(e) => setReserve(e.target.value)} inputMode="numeric"
            className="mt-1 w-full rounded-lg border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-950" />
        </label>
        <label className="text-sm">單檔上限 %
          <input value={maxPos} onChange={(e) => setMaxPos(e.target.value)} inputMode="numeric"
            className="mt-1 w-full rounded-lg border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-950" />
        </label>
        <label className="text-sm">單一產業上限 %
          <input value={sectorLimit} onChange={(e) => setSectorLimit(e.target.value)} inputMode="numeric"
            className="mt-1 w-full rounded-lg border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-950" />
        </label>
        <label className="col-span-2 text-sm sm:col-span-4">股票清單(代號,空白或逗號分隔)
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="2330 2454 2308 2412 1216"
            className="mt-1 w-full rounded-lg border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-950" />
        </label>
        <button type="submit" disabled={loading}
          className="col-span-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 sm:col-span-1">
          {loading ? '計算中…' : '計算分配'}
        </button>
      </form>

      {error && <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      {result?.notes && result.notes.length > 0 && (
        <div className="rounded-lg bg-amber-50 p-2 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
          {result.notes.map((n, i) => <div key={i}>⚠ {n}</div>)}
        </div>
      )}

      {result && (
        <div className="space-y-5">
          {/* Risk dashboard */}
          {d && (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <Metric label="已配置" value={`${NT(d.total_active_capital)} (${PCT(d.total_active_pct)})`} />
              <Metric label="預留加碼" value={NT(d.total_reserve_capital)} />
              <Metric label="持股數" value={`${d.n_positions ?? '—'} 檔`} />
              <Metric label={`最大產業 ${d.max_sector ?? ''}`} value={`${PCT(d.max_sector_pct)} / 上限 ${PCT(d.sector_limit_pct)}`} />
            </div>
          )}

          {/* Base allocation */}
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">初始配置</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-zinc-500 dark:text-zinc-400">
                  <th className="py-1">代號</th><th>張數</th><th>零股</th><th>預估資金</th><th>權重</th><th>狀態</th>
                </tr></thead>
                <tbody>
                  {result.base_matrix.map((r) => (
                    <tr key={r.symbol} className="border-t border-zinc-100 dark:border-zinc-800">
                      <td className="py-1 font-medium">{r.symbol}</td>
                      <td>{r.target_lots}</td><td>{r.target_odd}</td>
                      <td>{NT(r.est_capital_req)}</td><td>{PCT(r.final_weight)}</td>
                      <td className="text-zinc-500">{r.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pyramiding ladder */}
          {result.ladder_matrix.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">加碼階梯(預留資金·結構閘門)</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-zinc-500 dark:text-zinc-400">
                    <th className="py-1">代號</th><th>階</th><th>參考價</th><th>股數</th><th>預估資金</th><th>條件</th>
                  </tr></thead>
                  <tbody>
                    {result.ladder_matrix.map((r, i) => (
                      <tr key={i} className="border-t border-zinc-100 dark:border-zinc-800">
                        <td className="py-1 font-medium">{r.symbol}</td><td>{r.level}</td>
                        <td>{r.target_price === null ? '—' : `NT$${r.target_price}`}</td>
                        <td>{r.target_shares}</td><td>{NT(r.est_capital_req)}</td>
                        <td className={r.condition_flag.startsWith('Invalidated') ? 'text-rose-600 dark:text-rose-400' : 'text-zinc-500'}>
                          {FLAG_LABELS[r.condition_flag] ?? r.condition_flag}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <p className="border-t border-zinc-100 pt-3 text-xs text-zinc-400 dark:border-zinc-800 dark:text-zinc-500">
            加碼參考價來自結構/均線匯流支撐;結構失效的標的會凍結加碼(不接刀)。本表為條件計算,不構成投資建議。
          </p>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 p-2 dark:border-zinc-800">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-0.5 font-medium text-zinc-900 dark:text-zinc-50">{value}</p>
    </div>
  );
}
