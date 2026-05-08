'use client';

import type { FundamentalsData } from '@/lib/types';

interface FundamentalsCardProps {
  data: FundamentalsData;
}

function formatKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function ESGBar({ label, value }: { label: string; value?: number | null }) {
  if (value == null) return null;
  const pct = Math.min(100, Math.max(0, value));
  const color =
    pct >= 60 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400';
  return (
    <div>
      <div className="flex justify-between text-xs text-zinc-500 dark:text-zinc-400 mb-0.5">
        <span>{label}</span>
        <span className="font-medium text-zinc-700 dark:text-zinc-300">{pct.toFixed(1)}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-zinc-200 dark:bg-zinc-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function FundamentalsCard({ data }: FundamentalsCardProps) {
  const metrics = Object.entries(data.financial_metrics);
  const hasAnalyst = !!data.analyst?.consensus;
  const hasEarnings = !!(data.next_earnings_date || data.last_earnings?.eps_actual != null);
  const hasESG = data.esg?.total != null;

  if (metrics.length === 0 && !hasAnalyst && !hasEarnings && !hasESG) return null;

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900 space-y-5">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Fundamental Analysis
      </h3>

      {/* Financial Metrics Grid */}
      {metrics.length > 0 && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {metrics.map(([key, value]) => (
            <div key={key} className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800">
              <dt className="text-[11px] text-zinc-400 dark:text-zinc-500">{formatKey(key)}</dt>
              <dd className="mt-0.5 text-sm font-semibold text-zinc-800 dark:text-zinc-100">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {/* Analyst Price Targets */}
      {hasAnalyst && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
            Analyst Price Targets
          </h4>
          <div className="flex flex-wrap gap-3">
            {data.analyst.consensus && (
              <div className="rounded-lg bg-blue-50 px-4 py-2 dark:bg-blue-950">
                <p className="text-[11px] text-blue-500 dark:text-blue-400">Consensus</p>
                <p className="text-lg font-bold text-blue-700 dark:text-blue-300">
                  {data.analyst.consensus}
                </p>
              </div>
            )}
            {data.analyst.high && (
              <div className="rounded-lg bg-green-50 px-4 py-2 dark:bg-green-950">
                <p className="text-[11px] text-green-500 dark:text-green-400">High</p>
                <p className="text-base font-bold text-green-700 dark:text-green-300">
                  {data.analyst.high}
                </p>
              </div>
            )}
            {data.analyst.low && (
              <div className="rounded-lg bg-red-50 px-4 py-2 dark:bg-red-950">
                <p className="text-[11px] text-red-500 dark:text-red-400">Low</p>
                <p className="text-base font-bold text-red-700 dark:text-red-300">
                  {data.analyst.low}
                </p>
              </div>
            )}
            {data.analyst.median && (
              <div className="rounded-lg bg-zinc-50 px-4 py-2 dark:bg-zinc-800">
                <p className="text-[11px] text-zinc-400">Median</p>
                <p className="text-base font-bold text-zinc-700 dark:text-zinc-200">
                  {data.analyst.median}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Earnings */}
      {hasEarnings && (
        <div className="flex flex-wrap gap-3">
          {data.next_earnings_date && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-800 dark:bg-amber-950">
              <span className="text-amber-500">📅</span>
              <div>
                <p className="text-[10px] font-medium uppercase text-amber-600 dark:text-amber-400">
                  Next Earnings
                </p>
                <p className="text-sm font-bold text-amber-800 dark:text-amber-200">
                  {data.next_earnings_date}
                </p>
              </div>
            </div>
          )}
          {data.last_earnings?.eps_actual != null && (
            <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-800">
              <div>
                <p className="text-[10px] font-medium uppercase text-zinc-400">
                  Last EPS ({data.last_earnings.date ?? ''})
                </p>
                <p className="text-sm font-bold text-zinc-800 dark:text-zinc-100">
                  ${data.last_earnings.eps_actual?.toFixed(2)}{' '}
                  <span className="text-xs font-normal text-zinc-400">
                    est. ${data.last_earnings.eps_estimated?.toFixed(2) ?? 'N/A'}
                  </span>
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ESG Scores */}
      {hasESG && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
            ESG Score — {data.esg.total?.toFixed(1)}
          </h4>
          <div className="space-y-2">
            <ESGBar label="Environmental" value={data.esg.environmental} />
            <ESGBar label="Social" value={data.esg.social} />
            <ESGBar label="Governance" value={data.esg.governance} />
          </div>
        </div>
      )}
    </div>
  );
}
