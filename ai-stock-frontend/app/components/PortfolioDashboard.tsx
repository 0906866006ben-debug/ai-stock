'use client';

import { useState } from 'react';
import type { Position } from '@/lib/types';

const SHARES_PER_LOT = 1000;

interface Props {
  positions: Position[];
  onDelete: (id: string) => void;
  onSelect: (code: string, name: string) => void;
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

export default function PortfolioDashboard({ positions, onDelete, onSelect }: Props) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const totalValue = positions.reduce((s, p) => s + calcValue(p), 0);
  const totalCost = positions.reduce((s, p) => s + calcCost(p), 0);
  const totalPnl = totalValue - totalCost;
  const totalReturn = totalCost ? (totalPnl / totalCost) * 100 : 0;

  if (positions.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-8 text-center dark:border-zinc-800 dark:bg-zinc-900">
        <p className="text-zinc-400">尚未新增任何持倉。</p>
        <p className="mt-1 text-xs text-zinc-400">點擊「新增持倉」開始追蹤您的投資組合。</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: '總市值', value: `$${fmt(totalValue)}`, color: 'text-zinc-800 dark:text-zinc-100' },
          { label: '總成本', value: `$${fmt(totalCost)}`, color: 'text-zinc-600 dark:text-zinc-400' },
          {
            label: '未實現損益',
            value: `${totalPnl >= 0 ? '+' : ''}$${fmt(totalPnl)}`,
            color: totalPnl >= 0 ? 'text-red-500' : 'text-green-600',
          },
          {
            label: '報酬率',
            value: `${totalReturn >= 0 ? '+' : ''}${totalReturn.toFixed(2)}%`,
            color: totalReturn >= 0 ? 'text-red-500' : 'text-green-600',
          },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
            <p className={`mt-1 text-lg font-bold ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Holdings table */}
      <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-sm">
          <thead className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
            <tr>
              {['股票', '張數', '成本價', '現價', '市值', '損益', '報酬%', ''].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium text-zinc-500 dark:text-zinc-400">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 bg-white dark:divide-zinc-800 dark:bg-zinc-900">
            {positions.map((pos) => {
              const pnl = calcPnl(pos);
              const ret = calcReturn(pos);
              return (
                <tr key={pos.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
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
