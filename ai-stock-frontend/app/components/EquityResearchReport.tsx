'use client';

import { useState } from 'react';
import type { EquityResearch, ScenarioPrice } from '@/lib/types';

interface Props {
  data: EquityResearch;
  currentPrice: number;
  companyName: string;
  symbol: string;
}

function Accordion({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
      >
        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{title}</h3>
        <span
          className={`text-xl leading-none text-zinc-400 transition-transform ${
            open ? 'rotate-90' : ''
          }`}
          aria-hidden="true"
        >
          ›
        </span>
      </button>
      {open && (
        <div className="border-t border-zinc-200 px-5 py-5 dark:border-zinc-700">
          {children}
        </div>
      )}
    </section>
  );
}

export default function EquityResearchReport({ data, currentPrice: _currentPrice, companyName, symbol }: Props) {
  const getRatingColor = (rating: string) => {
    switch (rating) {
      case 'Strong Buy':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
      case 'Buy':
        return 'bg-green-50 text-green-600 dark:bg-green-950 dark:text-green-400';
      case 'Hold':
        return 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300';
      case 'Sell':
        return 'bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400';
      case 'Strong Sell':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
      default:
        return 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300';
    }
  };

  const getReportMode = () => {
    if (data.is_mock || data.sentiment_data?.source === 'mock') {
      return {
        label: 'Mock / Fallback',
        className: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300',
      };
    }
    if (data.sentiment_data?.source === 'estimated') {
      return {
        label: 'AI Estimated',
        className: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
      };
    }
    return {
      label: 'AI Analysis',
      className: 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
    };
  };

  const getSentimentColor = (stage: string) => {
    switch (stage) {
      case 'euphoric':
      case 'fearful':
        return 'text-red-600 dark:text-red-400';
      case 'early-stage':
        return 'text-green-600 dark:text-green-400';
      case 'skeptical':
        return 'text-amber-600 dark:text-amber-400';
      default:
        return 'text-zinc-600 dark:text-zinc-400';
    }
  };

  const sentimentLabel = (stage: string) => (
    stage === 'euphoric' ? '狂熱' :
    stage === 'fearful' ? '恐懼' :
    stage === 'skeptical' ? '懷疑' :
    stage === 'early-stage' ? '初期階段' :
    stage
  );

  const getAnalystRatingColor = (rating: string) => {
    switch (rating) {
      case 'Buy':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
      case 'Hold':
        return 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300';
      case 'Sell':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
      default:
        return 'bg-zinc-100 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-300';
    }
  };

  const getVerdictColor = (verdict: string) => {
    if (verdict.includes('overvalued') || verdict.includes('weakening') || verdict.includes('distributing')) {
      return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
    }
    if (verdict.includes('undervalued') || verdict.includes('strengthening') || verdict.includes('accumulating')) {
      return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
    }
    return 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300';
  };

  const getScenarioColor = (scenario: 'bear' | 'base' | 'bull' | 'stretched') => {
    switch (scenario) {
      case 'bear':
        return 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950';
      case 'base':
        return 'border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950';
      case 'bull':
        return 'border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950';
      case 'stretched':
        return 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950';
    }
  };

  const getScenarioPriceColor = (scenario: 'bear' | 'base' | 'bull' | 'stretched') => {
    switch (scenario) {
      case 'bear':
        return 'text-red-600 dark:text-red-400';
      case 'base':
        return 'text-amber-600 dark:text-amber-400';
      case 'bull':
        return 'text-green-600 dark:text-green-400';
      case 'stretched':
        return 'text-blue-600 dark:text-blue-400';
    }
  };

  const mode = getReportMode();
  const scenarios: {
    key: 'bear' | 'base' | 'bull' | 'stretched';
    label: string;
    scenario: ScenarioPrice;
  }[] = [
    { key: 'bear', label: '熊市情景', scenario: data.scenario_bear },
    { key: 'base', label: '基本情景', scenario: data.scenario_base },
    { key: 'bull', label: '看好情景', scenario: data.scenario_bull },
    { key: 'stretched', label: '拉伸情景', scenario: data.scenario_stretched },
  ];
  const actionRows = [
    { label: '進場區間', value: data.entry_zone, className: 'text-zinc-700 dark:text-zinc-300' },
    { label: '加倉區間', value: data.add_zone, className: 'text-zinc-700 dark:text-zinc-300' },
    { label: '獲利位置', value: data.profit_taking, className: 'text-green-600 dark:text-green-400' },
    { label: '止損條件', value: data.thesis_break, className: 'text-red-600 dark:text-red-400' },
    { label: '核心催化劑', value: data.key_catalyst, className: 'text-green-600 dark:text-green-400' },
    { label: '隱藏風險', value: data.hidden_risk, className: 'text-amber-600 dark:text-amber-400' },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">精英級股票研究報告</h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              {symbol} {companyName}
            </p>
          </div>
          <div className="flex flex-col items-start gap-3 sm:items-end">
            <div className="flex flex-wrap gap-2">
              <span className={`rounded-full px-4 py-2 text-sm font-semibold ${getRatingColor(data.investment_rating)}`}>
                {data.investment_rating}
              </span>
              <span className={`rounded-full px-4 py-2 text-sm font-semibold ${mode.className}`}>
                {mode.label}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-500 dark:text-zinc-400">信心度</span>
              <div className="h-2 w-28 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{ width: `${Math.round(data.confidence * 100)}%` }}
                />
              </div>
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
                {Math.round(data.confidence * 100)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      <section className="rounded-xl border border-blue-200 bg-blue-50 p-6 dark:border-blue-800 dark:bg-blue-950">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-blue-600 dark:text-blue-400">執行摘要</p>
        <div className="space-y-4 text-sm leading-relaxed text-blue-900 dark:text-blue-100">
          <p>{data.summary}</p>
          {data.narrative_conclusion && (
            <p className="border-t border-blue-200 pt-4 dark:border-blue-800">
              {data.narrative_conclusion}
            </p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
        <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">投資行動框架</h3>
        <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
          {actionRows.map((row) => (
            <div key={row.label} className="rounded-lg bg-zinc-50 p-4 dark:bg-zinc-800">
              <p className={`text-sm font-semibold ${row.className}`}>{row.label}</p>
              <p className="mt-2 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{row.value}</p>
            </div>
          ))}
        </div>
      </section>

      <Accordion title="市場敘事詳細">
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">社群情緒</h4>
              {data.sentiment_data ? (
                <div className="flex items-center gap-4 rounded-lg bg-zinc-50 p-4 dark:bg-zinc-800">
                  <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-4 border-blue-500 bg-white dark:bg-zinc-900">
                    <div className="text-center">
                      <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                        {data.sentiment_data.score ?? 0}
                      </div>
                      <div className="text-xs text-zinc-500 dark:text-zinc-400">/100</div>
                    </div>
                  </div>
                  <div className="min-w-0 text-sm text-zinc-600 dark:text-zinc-300">
                    <p className={`font-semibold ${getSentimentColor(data.sentiment_data.stage)}`}>
                      {sentimentLabel(data.sentiment_data.stage)}
                    </p>
                    <p className="mt-1">來源：{data.sentiment_data.source}</p>
                    {data.sentiment_data.avg_likes_per_post != null && (
                      <p>平均讚數：{data.sentiment_data.avg_likes_per_post}</p>
                    )}
                    {data.sentiment_data.avg_comments_per_post != null && (
                      <p>平均評論：{data.sentiment_data.avg_comments_per_post}</p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="rounded-lg bg-zinc-50 p-4 dark:bg-zinc-800">
                  <p className={`text-sm font-semibold ${getSentimentColor(data.sentiment_stage)}`}>
                    {sentimentLabel(data.sentiment_stage)}
                  </p>
                  <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">{data.social_sentiment}</p>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">機構觀點</h4>
              {data.analyst_consensus_data ? (
                <div className="space-y-4 rounded-lg bg-zinc-50 p-4 dark:bg-zinc-800">
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-700 dark:bg-green-900 dark:text-green-300">
                      {data.analyst_consensus_data.buy_count ?? 0} Buy
                    </span>
                    <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-900 dark:text-amber-300">
                      {data.analyst_consensus_data.hold_count ?? 0} Hold
                    </span>
                    <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700 dark:bg-red-900 dark:text-red-300">
                      {data.analyst_consensus_data.sell_count ?? 0} Sell
                    </span>
                  </div>
                  {(data.analyst_consensus_data.target_low != null ||
                    data.analyst_consensus_data.target_median != null ||
                    data.analyst_consensus_data.target_high != null) && (
                    <p className="text-sm text-zinc-600 dark:text-zinc-300">
                      目標價：TWD {data.analyst_consensus_data.target_low?.toFixed(2) ?? 'N/A'} ~{' '}
                      {data.analyst_consensus_data.target_high?.toFixed(2) ?? 'N/A'}
                      （中位數：{data.analyst_consensus_data.target_median?.toFixed(2) ?? 'N/A'}）
                    </p>
                  )}
                </div>
              ) : (
                <div className="rounded-lg bg-zinc-50 p-4 text-sm text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                  {data.institutional_view}
                </div>
              )}
            </div>
          </div>

          {data.analyst_consensus_data && data.analyst_consensus_data.entries.length > 0 && (
            <div>
              <h4 className="mb-3 text-sm font-semibold text-zinc-800 dark:text-zinc-200">分析師明細</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200 dark:border-zinc-700">
                      <th className="py-2 pr-3 text-left font-semibold text-zinc-600 dark:text-zinc-300">券商</th>
                      <th className="px-3 py-2 text-center font-semibold text-zinc-600 dark:text-zinc-300">評等</th>
                      <th className="py-2 pl-3 text-right font-semibold text-zinc-600 dark:text-zinc-300">目標價</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.analyst_consensus_data.entries.map((entry, idx) => (
                      <tr key={`${entry.firm}-${idx}`} className="border-b border-zinc-200 last:border-0 dark:border-zinc-700">
                        <td className="py-3 pr-3 text-zinc-700 dark:text-zinc-300">{entry.firm}</td>
                        <td className="px-3 py-3 text-center">
                          <span className={`rounded px-2 py-1 text-xs font-medium ${getAnalystRatingColor(entry.rating)}`}>
                            {entry.rating}
                          </span>
                        </td>
                        <td className="py-3 pl-3 text-right text-zinc-700 dark:text-zinc-300">
                          {entry.target_price != null ? `TWD ${entry.target_price.toFixed(2)}` : 'N/A'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <h4 className="mb-3 text-sm font-semibold text-zinc-800 dark:text-zinc-200">主要催化劑</h4>
            {data.catalyst_table && data.catalyst_table.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-blue-50 dark:bg-blue-900">
                      <th className="border border-zinc-300 px-3 py-2 text-left dark:border-zinc-600">時間</th>
                      <th className="border border-zinc-300 px-3 py-2 text-left dark:border-zinc-600">事件</th>
                      <th className="border border-zinc-300 px-3 py-2 text-left dark:border-zinc-600">數據</th>
                      <th className="border border-zinc-300 px-3 py-2 text-right dark:border-zinc-600">影響</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.catalyst_table.map((row, idx) => (
                      <tr key={`${row.time_horizon}-${idx}`} className="border-b border-zinc-200 dark:border-zinc-700">
                        <td className="whitespace-nowrap border border-zinc-300 px-3 py-2 font-medium text-zinc-700 dark:border-zinc-600 dark:text-zinc-300">{row.time_horizon}</td>
                        <td className="border border-zinc-300 px-3 py-2 text-zinc-600 dark:border-zinc-600 dark:text-zinc-300">{row.event}</td>
                        <td className="border border-zinc-300 px-3 py-2 text-zinc-600 dark:border-zinc-600 dark:text-zinc-300">{row.data_point}</td>
                        <td className="border border-zinc-300 px-3 py-2 text-right font-semibold text-blue-700 dark:border-zinc-600 dark:text-blue-300">{row.impact}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <ul className="space-y-2">
                {data.catalysts.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Accordion>

      <Accordion title="基本面詳細">
        <div className="space-y-6">
          <div className="space-y-3">
            <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${getVerdictColor(data.valuation_verdict)}`}>
              {data.valuation_verdict === 'overvalued' ? '估值過高' :
               data.valuation_verdict === 'undervalued' ? '估值過低' :
               data.valuation_verdict === 'fairly valued' ? '估值合理' :
               data.valuation_verdict}
            </span>
            <div>
              <h4 className="mb-2 text-sm font-semibold text-zinc-800 dark:text-zinc-200">估值假設</h4>
              <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{data.valuation_assumptions}</p>
            </div>
          </div>

          <div>
            <h4 className="mb-3 text-sm font-semibold text-red-600 dark:text-red-400">財務風險</h4>
            {data.risk_table && data.risk_table.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-red-50 dark:bg-red-900">
                      <th className="border border-zinc-300 px-3 py-2 text-left dark:border-zinc-600">風險</th>
                      <th className="whitespace-nowrap border border-zinc-300 px-3 py-2 text-center dark:border-zinc-600">機率%</th>
                      <th className="border border-zinc-300 px-3 py-2 text-left dark:border-zinc-600">緩解策略</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.risk_table.map((row, idx) => (
                      <tr key={`${row.risk}-${idx}`} className="border-b border-zinc-200 dark:border-zinc-700">
                        <td className="border border-zinc-300 px-3 py-2 text-zinc-700 dark:border-zinc-600 dark:text-zinc-300">{row.risk}</td>
                        <td className="border border-zinc-300 px-3 py-2 text-center dark:border-zinc-600">
                          <span className="rounded bg-red-100 px-2 py-1 text-xs font-semibold text-red-700 dark:bg-red-900 dark:text-red-300">
                            {row.probability_pct}%
                          </span>
                        </td>
                        <td className="border border-zinc-300 px-3 py-2 text-zinc-700 dark:border-zinc-600 dark:text-zinc-300">{row.mitigation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <ul className="space-y-2">
                {data.financial_risks.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Accordion>

      <Accordion title="技術與籌碼詳細">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">動量判斷</p>
            <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${getVerdictColor(data.technical_verdict)}`}>
              {data.technical_verdict === 'strengthening' ? '強化中' :
               data.technical_verdict === 'weakening' ? '減弱中' :
               data.technical_verdict === 'consolidating' ? '整理中' :
               data.technical_verdict}
            </span>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">機構持倉</p>
            <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${getVerdictColor(data.institutional_positioning)}`}>
              {data.institutional_positioning === 'accumulating' ? '積累中' :
               data.institutional_positioning === 'distributing' ? '派發中' :
               data.institutional_positioning === 'neutral' ? '中立' :
               data.institutional_positioning}
            </span>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">適合投資風格</p>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">
              {data.setup_suitability === 'swing trader' ? '短線交易' :
               data.setup_suitability === 'long-term' ? '長期持有' :
               data.setup_suitability === 'both' ? '短長皆宜' :
               data.setup_suitability === 'neither' ? '暫不適合' :
               data.setup_suitability}
            </p>
          </div>
        </div>
      </Accordion>

      <Accordion title="情景分析">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {scenarios.map(({ key, label, scenario }) => (
            <div key={key} className={`rounded-lg border-2 p-4 ${getScenarioColor(key)}`}>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-300">{label}</p>
              <p className={`text-2xl font-bold ${getScenarioPriceColor(key)}`}>
                {scenario.target_price.toFixed(2)}
              </p>
              {scenario.upside_pct !== undefined && scenario.upside_pct !== null && (
                <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
                  {scenario.upside_pct > 0 ? '+' : ''}{scenario.upside_pct.toFixed(1)}%
                </p>
              )}
              <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">{scenario.rationale}</p>
              <div className="mt-3 border-t border-current border-opacity-20 pt-3">
                <p className="mb-1 text-xs font-semibold text-zinc-700 dark:text-zinc-200">主要風險</p>
                <p className="text-xs text-zinc-600 dark:text-zinc-300">{scenario.key_risk}</p>
              </div>
            </div>
          ))}
        </div>
      </Accordion>

      <Accordion title="評級與資料來源">
        <div className="space-y-6">
          {data.category_ratings && data.category_ratings.length > 0 && (
            <div>
              <h4 className="mb-4 text-sm font-semibold text-zinc-800 dark:text-zinc-200">評級評分</h4>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {data.category_ratings.map((rating, idx) => {
                  const stars = Math.max(1, Math.min(5, rating.stars ?? 0));
                  return (
                    <div key={`${rating.category}-${idx}`} className="flex items-center justify-between gap-4 rounded-lg bg-zinc-50 px-4 py-3 dark:bg-zinc-800">
                      <span className="font-medium text-zinc-800 dark:text-zinc-200">{rating.label_zh}</span>
                      <div className="flex gap-1" aria-label={`${rating.label_zh} ${stars} out of 5`}>
                        {Array.from({ length: 5 }).map((_, i) => (
                          <span
                            key={i}
                            className={i < stars ? 'text-xl text-yellow-400' : 'text-xl text-zinc-300 dark:text-zinc-600'}
                          >
                            {i < stars ? '★' : '☆'}
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {data.source_citations && data.source_citations.length > 0 && (
            <div className="border-t border-zinc-200 pt-5 dark:border-zinc-700">
              <h4 className="mb-3 text-sm font-semibold text-zinc-800 dark:text-zinc-200">資料來源</h4>
              <ul className="space-y-2 text-sm">
                {data.source_citations.map((citation, idx) => (
                  <li key={`${citation.source}-${idx}`}>
                    {citation.url ? (
                      <a
                        href={citation.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline dark:text-blue-400"
                      >
                        {citation.source}: {citation.title}
                      </a>
                    ) : (
                      <span className="text-zinc-700 dark:text-zinc-300">
                        {citation.source}: {citation.title}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Accordion>
    </div>
  );
}
