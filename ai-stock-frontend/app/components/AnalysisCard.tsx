'use client';

import { StockAnalysisResponse } from '@/lib/api';

interface AnalysisCardProps {
  data: StockAnalysisResponse;
}

const TREND_STYLES: Record<string, string> = {
  bullish: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  bearish: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  neutral: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200',
};

export default function AnalysisCard({ data }: AnalysisCardProps) {
  const changePositive = data.price_change_percent >= 0;
  const trendStyle = TREND_STYLES[data.trend] ?? TREND_STYLES.neutral;
  const confidencePct = Math.round(data.confidence * 100);

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
            {data.symbol}
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{data.company_name}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            ${data.current_price.toFixed(2)}
          </p>
          <p className={`text-sm font-medium ${changePositive ? 'text-green-600' : 'text-red-500'}`}>
            {changePositive ? '+' : ''}
            {data.price_change_percent.toFixed(2)}%
          </p>
        </div>
      </div>

      {/* Trend + Confidence */}
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${trendStyle}`}>
          {data.trend}
        </span>
        <div className="flex flex-1 items-center gap-2 min-w-[160px]">
          <span className="text-xs text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
            AI Confidence
          </span>
          <div className="flex-1 rounded-full bg-zinc-200 dark:bg-zinc-700 h-2 overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${confidencePct}%` }}
            />
          </div>
          <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300 w-8 text-right">
            {confidencePct}%
          </span>
        </div>
      </div>

      {/* Summary */}
      {data.summary && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            AI Summary
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {data.summary}
          </p>
        </div>
      )}

      {/* Recommendation */}
      {data.recommendation && (
        <div className="mt-4 rounded-lg bg-blue-50 px-4 py-3 dark:bg-blue-950">
          <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
            {data.recommendation}
          </p>
        </div>
      )}

      {/* Risks + Catalysts */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {data.risks.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-red-500">
              Risks
            </h3>
            <ul className="mt-1 space-y-1">
              {data.risks.map((r, i) => (
                <li key={i} className="flex items-start gap-1.5 text-sm text-zinc-700 dark:text-zinc-300">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}
        {data.catalysts.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-green-600">
              Catalysts
            </h3>
            <ul className="mt-1 space-y-1">
              {data.catalysts.map((c, i) => (
                <li key={i} className="flex items-start gap-1.5 text-sm text-zinc-700 dark:text-zinc-300">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-green-400" />
                  {c}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
