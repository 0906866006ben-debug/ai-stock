'use client';

import type { PeerStock } from '@/lib/types';

interface CompetitorCardProps {
  symbol: string;
  peers: PeerStock[];
  loading?: boolean;
}

const COLS: { key: keyof PeerStock; label: string; right?: boolean }[] = [
  { key: 'symbol', label: 'Symbol' },
  { key: 'company_name', label: 'Company' },
  { key: 'price', label: 'Price', right: true },
  { key: 'market_cap', label: 'Mkt Cap', right: true },
  { key: 'pe_ratio', label: 'P/E', right: true },
  { key: 'gross_margin', label: 'Gross Margin', right: true },
  { key: 'net_margin', label: 'Net Margin', right: true },
  { key: 'roe', label: 'ROE', right: true },
  { key: 'ev_ebitda', label: 'EV/EBITDA', right: true },
];

function cellValue(peer: PeerStock, key: keyof PeerStock): string {
  const v = peer[key];
  if (v == null) return '—';
  if (key === 'price') return `$${Number(v).toFixed(2)}`;
  if (key === 'market_cap') return peer.market_cap_fmt ?? String(v);
  return String(v);
}

export default function CompetitorCard({ symbol, peers, loading }: CompetitorCardProps) {
  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Competitor Analysis — {symbol} vs Peers
      </h3>

      {loading && (
        <div className="mt-4 flex justify-center py-6">
          <div className="h-6 w-6 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
        </div>
      )}

      {!loading && peers.length === 0 && (
        <p className="mt-3 text-sm text-zinc-400 dark:text-zinc-500">
          No peer data available for {symbol}.
        </p>
      )}

      {!loading && peers.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-zinc-700">
                {COLS.map((col) => (
                  <th
                    key={col.key}
                    className={`pb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400 ${
                      col.right ? 'text-right' : 'text-left'
                    } pr-4 last:pr-0`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {peers.map((peer) => (
                <tr key={peer.symbol} className="text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
                  {COLS.map((col) => (
                    <td
                      key={col.key}
                      className={`py-2 pr-4 last:pr-0 ${col.right ? 'text-right' : ''} ${
                        col.key === 'symbol'
                          ? 'font-mono font-semibold text-zinc-900 dark:text-zinc-100'
                          : col.key === 'company_name'
                          ? 'max-w-[140px] truncate'
                          : ''
                      }`}
                    >
                      {cellValue(peer, col.key)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
