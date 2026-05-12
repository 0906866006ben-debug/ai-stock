'use client';

import type { ComprehensiveAnalysis } from '@/lib/types';

interface Props {
  data: ComprehensiveAnalysis;
}

export default function SynthesisRecommendation({ data }: Props) {
  const directionColor =
    data.overall_direction === 'bullish'
      ? 'text-green-600 dark:text-green-400'
      : data.overall_direction === 'bearish'
        ? 'text-red-600 dark:text-red-400'
        : 'text-amber-600 dark:text-amber-400';

  const directionBg =
    data.overall_direction === 'bullish'
      ? 'bg-green-100 dark:bg-green-900'
      : data.overall_direction === 'bearish'
        ? 'bg-red-100 dark:bg-red-900'
        : 'bg-amber-100 dark:bg-amber-900';

  const convictionColor =
    data.conviction_level === '高'
      ? 'text-green-600 dark:text-green-400'
      : data.conviction_level === '中'
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-red-600 dark:text-red-400';

  const directionLabel =
    data.overall_direction === 'bullish'
      ? '看漲'
      : data.overall_direction === 'bearish'
        ? '看跌'
        : '中立';

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-5">
      {/* Overall Direction and Conviction */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className={`rounded-lg ${directionBg} px-4 py-3`}>
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
            綜合判斷
          </p>
          <p className={`text-2xl font-bold ${directionColor} mt-1`}>
            {directionLabel}
          </p>
          <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-2">
            {data.summary}
          </p>
        </div>

        <div className="rounded-lg bg-blue-50 dark:bg-blue-950 px-4 py-3">
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
            確認度評分
          </p>
          <p className="text-2xl font-bold text-blue-600 dark:text-blue-400 mt-1">
            {(data.confirmation_score * 100).toFixed(0)}%
          </p>
          <div className="mt-2 flex gap-1 text-xs">
            <span className="px-2 py-1 rounded bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">
              基本面: {data.confirmation_pillars?.基本面 || '—'}
            </span>
          </div>
          <div className="mt-1 flex gap-1 text-xs">
            <span className="px-2 py-1 rounded bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300">
              技術面: {data.confirmation_pillars?.技術面 || '—'}
            </span>
          </div>
        </div>

        <div className="rounded-lg bg-purple-50 dark:bg-purple-950 px-4 py-3">
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
            信心度
          </p>
          <p className={`text-2xl font-bold ${convictionColor} mt-1`}>
            {data.conviction_level}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-2 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
              <div
                className={`h-full ${
                  data.conviction_level === '高'
                    ? 'bg-green-500'
                    : data.conviction_level === '中'
                      ? 'bg-amber-500'
                      : 'bg-red-500'
                }`}
                style={{
                  width: `${
                    data.conviction_level === '高'
                      ? 100
                      : data.conviction_level === '中'
                        ? 60
                        : 30
                  }%`,
                }}
              />
            </div>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-2">
            時間: {data.timeframe}
          </p>
        </div>
      </div>

      {/* Recommendation Box */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950 px-4 py-3">
        <p className="text-xs font-medium text-blue-600 dark:text-blue-400 uppercase tracking-wide">
          投資建議
        </p>
        <p className="text-sm font-medium text-blue-900 dark:text-blue-100 mt-2 leading-relaxed">
          {data.recommendation}
        </p>
      </div>

      {/* Price Targets */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-lg bg-green-50 dark:bg-green-950 px-4 py-3">
          <p className="text-xs font-medium text-green-600 dark:text-green-400 uppercase tracking-wide">
            目標價
          </p>
          <p className="text-2xl font-bold text-green-700 dark:text-green-300 mt-1">
            {data.target_price.toFixed(2)}
          </p>
        </div>

        <div className="rounded-lg bg-red-50 dark:bg-red-950 px-4 py-3">
          <p className="text-xs font-medium text-red-600 dark:text-red-400 uppercase tracking-wide">
            停損價
          </p>
          <p className="text-2xl font-bold text-red-700 dark:text-red-300 mt-1">
            {data.stop_loss.toFixed(2)}
          </p>
        </div>
      </div>

      {/* Conflicts */}
      {data.conflicts && data.conflicts.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950 px-4 py-3">
          <p className="text-xs font-medium text-amber-600 dark:text-amber-400 uppercase tracking-wide">
            衝突警告
          </p>
          <div className="mt-2 space-y-1">
            {data.conflicts.map((conflict, i) => (
              <p key={i} className="text-sm text-amber-900 dark:text-amber-100">
                ⚠️ {conflict}
              </p>
            ))}
          </div>
          {data.conflict_resolution && (
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-2 italic">
              {data.conflict_resolution}
            </p>
          )}
        </div>
      )}

      {/* Risks and Catalysts */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {data.key_risks && data.key_risks.length > 0 && (
          <div>
            <p className="text-sm font-semibold text-red-600 dark:text-red-400 uppercase tracking-wide mb-2">
              主要風險
            </p>
            <ul className="space-y-1">
              {data.key_risks.map((risk, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm text-zinc-700 dark:text-zinc-300"
                >
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                  {risk}
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.catalyst_timeline && data.catalyst_timeline.length > 0 && (
          <div>
            <p className="text-sm font-semibold text-green-600 dark:text-green-400 uppercase tracking-wide mb-2">
              催化劑時間表
            </p>
            <ul className="space-y-1">
              {data.catalyst_timeline.map((catalyst, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm text-zinc-700 dark:text-zinc-300"
                >
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-green-400" />
                  {catalyst}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Pillar Agreement Summary */}
      {data.confirmation_pillars && (
        <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800 px-4 py-3">
          <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 uppercase tracking-wide mb-2">
            各柱共識
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(data.confirmation_pillars).map(([pillar, direction]) => (
              <div
                key={pillar}
                className={`rounded px-2 py-1 text-xs font-medium text-center ${
                  direction === 'bullish' || direction === 'uptrend'
                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                    : direction === 'bearish' || direction === 'downtrend'
                      ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                      : 'bg-zinc-200 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-300'
                }`}
              >
                <p className="font-semibold">{pillar}</p>
                <p className="text-xs">
                  {direction === 'bullish' || direction === 'uptrend'
                    ? '看好'
                    : direction === 'bearish' || direction === 'downtrend'
                      ? '看壞'
                      : '中立'}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
