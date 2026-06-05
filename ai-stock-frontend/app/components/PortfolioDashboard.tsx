'use client';

import { useEffect, useState } from 'react';
import { getTwScreenQualityBatch } from '@/lib/api';
import type { DurabilityMetrics, Position } from '@/lib/types';
import PortfolioQualitySummary from './PortfolioQualitySummary';
import QualityDegradationAlert from './QualityDegradationAlert';

const SHARES_PER_LOT = 1000;

interface Props {
  positions: Position[];
  onDelete: (id: string) => void;
  onSelect: (code: string, name: string) => void;
  onRefreshPrices?: () => void;
  refreshingPrices?: boolean;
  priceRefreshError?: string | null;
}

function calcValue(pos: Position): number {
  return (pos.current_price ?? pos.cost_per_share) * pos.lots * SHARES_PER_LOT;
}

function calcCost(pos: Position): number {
  return pos.cost_per_share * pos.lots * SHARES_PER_LOT;
}

function calcPnl(pos: Position): number {
  return calcValue(pos) - calcCost(pos);
}

function calcReturn(pos: Position): number {
  const cost = calcCost(pos);
  if (!cost) return 0;
  return (calcPnl(pos) / cost) * 100;
}

function fmt(n: number, d = 0): string {
  return n.toLocaleString('zh-TW', { maximumFractionDigits: d });
}

function latestUpdatedAt(positions: Position[]): string | null {
  const timestamps = positions
    .map((p) => p.current_price_updated_at)
    .filter((v): v is string => Boolean(v))
    .map((v) => new Date(v).getTime())
    .filter((v) => Number.isFinite(v));
  if (timestamps.length === 0) return null;
  return new Date(Math.max(...timestamps)).toLocaleString('zh-TW', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function PortfolioDashboard({
  positions,
  onDelete,
  onSelect,
  onRefreshPrices,
  refreshingPrices = false,
  priceRefreshError = null,
}: Props) {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [qualityByCode, setQualityByCode] = useState<Record<string, DurabilityMetrics | null>>({});

  useEffect(() => {
    let cancelled = false;
    const codes = Array.from(new Set(positions.map((pos) => pos.stock_code.trim()).filter(Boolean)));
    const missing = codes.filter((code) => !(code in qualityByCode));
    if (missing.length === 0) return;

    getTwScreenQualityBatch(missing).then((results) => {
      if (cancelled) return;
      setQualityByCode((prev) => {
        const next = { ...prev };
        results.forEach(([code, metrics]) => {
          next[code] = metrics;
        });
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [positions, qualityByCode]);

  const totalValue = positions.reduce((s, p) => s + calcValue(p), 0);
  const totalCost = positions.reduce((s, p) => s + calcCost(p), 0);
  const totalPnl = totalValue - totalCost;
  const totalReturn = totalCost ? (totalPnl / totalCost) * 100 : 0;
  const updatedAt = latestUpdatedAt(positions);

  if (positions.length === 0) {
    return (
      <div className="rounded-2xl border border-pink-200 bg-gradient-to-br from-pink-50 to-purple-50 p-8 text-center dark:border-pink-900/40 dark:from-pink-950/20 dark:to-purple-950/20">
        <p className="text-pink-600 dark:text-pink-300">✿ 還沒有任何寶貝呢～</p>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">點「加新寶貝」開始收集你的小金庫 ♡</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-pink-700 dark:text-pink-300">♡ 我的寶貝清單</h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {refreshingPrices
              ? '🌸 現價更新中...'
              : updatedAt
                ? `現價更新：${updatedAt}`
                : '尚未更新現價'}
            {priceRefreshError ? `，${priceRefreshError}` : ''}
          </p>
        </div>
        {onRefreshPrices && (
          <button
            type="button"
            onClick={onRefreshPrices}
            disabled={refreshingPrices}
            className="rounded-full border border-pink-300 bg-white px-3 py-2 text-sm font-medium text-pink-600 hover:bg-pink-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-pink-900/60 dark:bg-zinc-900 dark:text-pink-300 dark:hover:bg-pink-950/30"
          >
            {refreshingPrices ? '更新中 ♡' : '↻ 更新現價'}
          </button>
        )}
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 stagger-children">
        {[
          { label: '✿ 總市值', value: `$${fmt(totalValue)}`, color: 'text-zinc-800 dark:text-zinc-100' },
          { label: '🪙 總成本', value: `$${fmt(totalCost)}`, color: 'text-zinc-600 dark:text-zinc-400' },
          {
            label: totalPnl >= 0 ? '💗 未實現損益' : '🥺 未實現損益',
            value: `${totalPnl >= 0 ? '+' : ''}$${fmt(totalPnl)}`,
            color: totalPnl >= 0 ? 'text-red-500' : 'text-green-600',
          },
          {
            label: totalReturn >= 0 ? '🎀 報酬率' : '💧 報酬率',
            value: `${totalReturn >= 0 ? '+' : ''}${totalReturn.toFixed(2)}%`,
            color: totalReturn >= 0 ? 'text-red-500' : 'text-green-600',
          },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            className="rounded-3xl border border-pink-100 bg-white p-3 shadow-sm hover:shadow-md hover:border-pink-200 hover:-translate-y-0.5 transition-all duration-300 dark:border-pink-900/30 dark:bg-zinc-900"
          >
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
            <p className={`mt-1 text-lg font-bold ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.45fr)]">
        <QualityDegradationAlert positions={positions} qualityByCode={qualityByCode} />
        <PortfolioQualitySummary positions={positions} qualityByCode={qualityByCode} />
      </div>

      {/* Holdings table */}
      <div className="overflow-x-auto rounded-3xl border border-pink-100 bg-white shadow-sm dark:border-pink-900/30 dark:bg-zinc-900">
        <table className="w-full text-sm">
          <thead className="border-b border-pink-100 bg-pink-50/50 dark:border-pink-900/30 dark:bg-pink-950/20">
            <tr>
              {['股票', '張數', '成本價', '現價', '市值', '損益', '報酬%', ''].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium text-pink-600 dark:text-pink-300">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-pink-50 bg-white dark:divide-pink-900/20 dark:bg-zinc-900">
            {positions.map((pos) => {
              const pnl = calcPnl(pos);
              const ret = calcReturn(pos);
              return (
                <tr key={pos.id} className="hover:bg-pink-50/40 dark:hover:bg-pink-950/20 transition-colors">
                  <td className="px-3 py-2">
                    <button
                      onClick={() => onSelect(pos.stock_code, pos.company_name)}
                      className="text-left"
                    >
                      <div className="font-medium text-zinc-800 dark:text-zinc-100">{pos.stock_code}</div>
                      <div className="text-xs text-zinc-400">{pos.company_name}</div>
                    </button>
                  </td>
                  <td className="px-3 py-2 font-mono">{pos.lots}</td>
                  <td className="px-3 py-2 font-mono">{fmt(pos.cost_per_share, 2)}</td>
                  <td className="px-3 py-2 font-mono">
                    {pos.current_price != null ? fmt(pos.current_price, 2) : '-'}
                  </td>
                  <td className="px-3 py-2 font-mono">{fmt(calcValue(pos))}</td>
                  <td className={`px-3 py-2 font-mono ${pnl >= 0 ? 'text-red-500' : 'text-green-600'}`}>
                    {pnl >= 0 ? '+' : ''}{fmt(pnl)}
                  </td>
                  <td className={`px-3 py-2 font-mono ${ret >= 0 ? 'text-red-500' : 'text-green-600'}`}>
                    {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2">
                    {confirmId === pos.id ? (
                      <div className="flex gap-2">
                        <button
                          onClick={() => { onDelete(pos.id); setConfirmId(null); }}
                          className="text-xs text-red-500 hover:underline"
                        >確認</button>
                        <button
                          onClick={() => setConfirmId(null)}
                          className="text-xs text-zinc-400 hover:underline"
                        >取消</button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmId(pos.id)}
                        className="text-xs text-zinc-400 hover:text-red-500"
                      >刪除</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
