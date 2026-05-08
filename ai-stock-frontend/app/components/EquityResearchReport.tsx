'use client';

import type { EquityResearch } from '@/lib/types';

interface Props {
  data: EquityResearch;
  currentPrice: number;
  companyName: string;
  symbol: string;
}

export default function EquityResearchReport({ data, currentPrice, companyName, symbol }: Props) {
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

  const getSentimentColor = (stage: string) => {
    switch (stage) {
      case 'euphoric':
        return 'text-red-600 dark:text-red-400';
      case 'early-stage':
        return 'text-green-600 dark:text-green-400';
      case 'fearful':
        return 'text-red-600 dark:text-red-400';
      case 'skeptical':
        return 'text-amber-600 dark:text-amber-400';
      default:
        return 'text-zinc-600 dark:text-zinc-400';
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
        return 'bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800';
      case 'base':
        return 'bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800';
      case 'bull':
        return 'bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800';
      case 'stretched':
        return 'bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800';
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">精英級股票研究報告</h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              {symbol} {companyName}
            </p>
          </div>
          <div className="text-right">
            <p className={`inline-block rounded-full px-4 py-2 text-sm font-semibold ${getRatingColor(data.investment_rating)}`}>
              {data.investment_rating}
            </p>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-zinc-500 dark:text-zinc-400">信心度</span>
              <div className="h-2 w-24 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
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

      {/* [1] Market Narrative */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-4">
        <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">市場敘事</h3>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800 p-3">
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">社群情緒</p>
            <p className={`text-sm font-semibold ${getSentimentColor(data.sentiment_stage)}`}>
              {data.sentiment_stage === 'euphoric' ? '狂熱' :
               data.sentiment_stage === 'fearful' ? '恐懼' :
               data.sentiment_stage === 'skeptical' ? '懷疑' :
               data.sentiment_stage === 'early-stage' ? '初期階段' :
               data.sentiment_stage}
            </p>
            <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">{data.social_sentiment}</p>
          </div>

          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800 p-3">
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">機構觀點</p>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">{data.institutional_view}</p>
          </div>

          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800 p-3">
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">主要催化劑</p>
            <ul className="space-y-1">
              {data.catalysts.slice(0, 2).map((c, i) => (
                <li key={i} className="text-xs text-zinc-600 dark:text-zinc-300 flex items-start gap-1">
                  <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-blue-400" />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950 p-4">
          <p className="text-xs font-medium text-blue-600 dark:text-blue-400 uppercase tracking-wide mb-2">股價移動結論</p>
          <p className="text-sm text-blue-900 dark:text-blue-100 leading-relaxed">{data.narrative_conclusion}</p>
        </div>
      </div>

      {/* [2] Fundamental Snapshot */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-4">
        <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">基本面快照</h3>

        <div>
          <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${getVerdictColor(data.valuation_verdict)}`}>
            {data.valuation_verdict === 'overvalued' ? '估值過高' :
             data.valuation_verdict === 'undervalued' ? '估值過低' :
             data.valuation_verdict === 'fairly valued' ? '估值合理' :
             data.valuation_verdict}
          </span>
        </div>

        <div>
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">估值假設</p>
          <p className="text-sm text-zinc-700 dark:text-zinc-300">{data.valuation_assumptions}</p>
        </div>

        {data.financial_risks.length > 0 && (
          <div>
            <p className="text-xs font-medium text-red-600 dark:text-red-400 uppercase tracking-wide mb-2">財務風險</p>
            <ul className="space-y-1">
              {data.financial_risks.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* [3] Technical Snapshot */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-4">
        <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">技術面快照</h3>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">動量判斷</p>
            <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${getVerdictColor(data.technical_verdict)}`}>
              {data.technical_verdict === 'strengthening' ? '強化中' :
               data.technical_verdict === 'weakening' ? '減弱中' :
               data.technical_verdict === 'consolidating' ? '整理中' :
               data.technical_verdict}
            </span>
          </div>

          <div>
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">機構持倉</p>
            <span className={`inline-block rounded-full px-3 py-1 text-xs font-semibold ${getVerdictColor(data.institutional_positioning)}`}>
              {data.institutional_positioning === 'accumulating' ? '積累中' :
               data.institutional_positioning === 'distributing' ? '派發中' :
               data.institutional_positioning === 'neutral' ? '中立' :
               data.institutional_positioning}
            </span>
          </div>

          <div>
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">適合投資風格</p>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">
              {data.setup_suitability === 'swing trader' ? '短線交易' :
               data.setup_suitability === 'long-term' ? '長期持有' :
               data.setup_suitability === 'both' ? '短長皆宜' :
               data.setup_suitability === 'neither' ? '暫不適合' :
               data.setup_suitability}
            </p>
          </div>
        </div>
      </div>

      {/* [4] Scenario Framework */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-4">
        <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">情景分析框架</h3>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Bear */}
          <div className={`rounded-lg border-2 p-4 ${getScenarioColor('bear')}`}>
            <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 uppercase tracking-wide mb-2">熊市情景</p>
            <p className={`text-2xl font-bold ${getScenarioPriceColor('bear')}`}>
              {data.scenario_bear.target_price.toFixed(2)}
            </p>
            {data.scenario_bear.upside_pct !== undefined && data.scenario_bear.upside_pct !== null && (
              <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-1">
                {data.scenario_bear.upside_pct > 0 ? '+' : ''}{data.scenario_bear.upside_pct.toFixed(1)}%
              </p>
            )}
            <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-2">{data.scenario_bear.rationale}</p>
            <div className="mt-3 pt-3 border-t border-current border-opacity-20">
              <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200 mb-1">主要風險</p>
              <p className="text-xs text-zinc-600 dark:text-zinc-300">{data.scenario_bear.key_risk}</p>
            </div>
          </div>

          {/* Base */}
          <div className={`rounded-lg border-2 p-4 ${getScenarioColor('base')}`}>
            <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 uppercase tracking-wide mb-2">基本情景</p>
            <p className={`text-2xl font-bold ${getScenarioPriceColor('base')}`}>
              {data.scenario_base.target_price.toFixed(2)}
            </p>
            {data.scenario_base.upside_pct !== undefined && data.scenario_base.upside_pct !== null && (
              <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-1">
                {data.scenario_base.upside_pct > 0 ? '+' : ''}{data.scenario_base.upside_pct.toFixed(1)}%
              </p>
            )}
            <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-2">{data.scenario_base.rationale}</p>
            <div className="mt-3 pt-3 border-t border-current border-opacity-20">
              <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200 mb-1">主要風險</p>
              <p className="text-xs text-zinc-600 dark:text-zinc-300">{data.scenario_base.key_risk}</p>
            </div>
          </div>

          {/* Bull */}
          <div className={`rounded-lg border-2 p-4 ${getScenarioColor('bull')}`}>
            <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 uppercase tracking-wide mb-2">看好情景</p>
            <p className={`text-2xl font-bold ${getScenarioPriceColor('bull')}`}>
              {data.scenario_bull.target_price.toFixed(2)}
            </p>
            {data.scenario_bull.upside_pct !== undefined && data.scenario_bull.upside_pct !== null && (
              <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-1">
                {data.scenario_bull.upside_pct > 0 ? '+' : ''}{data.scenario_bull.upside_pct.toFixed(1)}%
              </p>
            )}
            <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-2">{data.scenario_bull.rationale}</p>
            <div className="mt-3 pt-3 border-t border-current border-opacity-20">
              <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200 mb-1">主要風險</p>
              <p className="text-xs text-zinc-600 dark:text-zinc-300">{data.scenario_bull.key_risk}</p>
            </div>
          </div>

          {/* Stretched */}
          <div className={`rounded-lg border-2 p-4 ${getScenarioColor('stretched')}`}>
            <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300 uppercase tracking-wide mb-2">拉伸情景</p>
            <p className={`text-2xl font-bold ${getScenarioPriceColor('stretched')}`}>
              {data.scenario_stretched.target_price.toFixed(2)}
            </p>
            {data.scenario_stretched.upside_pct !== undefined && data.scenario_stretched.upside_pct !== null && (
              <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-1">
                {data.scenario_stretched.upside_pct > 0 ? '+' : ''}{data.scenario_stretched.upside_pct.toFixed(1)}%
              </p>
            )}
            <p className="text-xs text-zinc-600 dark:text-zinc-300 mt-2">{data.scenario_stretched.rationale}</p>
            <div className="mt-3 pt-3 border-t border-current border-opacity-20">
              <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-200 mb-1">主要風險</p>
              <p className="text-xs text-zinc-600 dark:text-zinc-300">{data.scenario_stretched.key_risk}</p>
            </div>
          </div>
        </div>
      </div>

      {/* [5] Actionable Framework */}
      <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 space-y-4">
        <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">投資行動框架</h3>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-b border-zinc-200 dark:border-zinc-700">
                <td className="py-3 pr-4 font-semibold text-zinc-700 dark:text-zinc-300 w-24">進場區間</td>
                <td className="py-3 text-zinc-600 dark:text-zinc-400">{data.entry_zone}</td>
              </tr>
              <tr className="border-b border-zinc-200 dark:border-zinc-700">
                <td className="py-3 pr-4 font-semibold text-zinc-700 dark:text-zinc-300 w-24">加倉區間</td>
                <td className="py-3 text-zinc-600 dark:text-zinc-400">{data.add_zone}</td>
              </tr>
              <tr className="border-b border-zinc-200 dark:border-zinc-700">
                <td className="py-3 pr-4 font-semibold text-zinc-700 dark:text-zinc-300 w-24">獲利位置</td>
                <td className="py-3 text-zinc-600 dark:text-zinc-400">{data.profit_taking}</td>
              </tr>
              <tr className="border-b border-zinc-200 dark:border-zinc-700">
                <td className="py-3 pr-4 font-semibold text-red-600 dark:text-red-400 w-24">止損條件</td>
                <td className="py-3 text-zinc-600 dark:text-zinc-400">{data.thesis_break}</td>
              </tr>
              <tr className="border-b border-zinc-200 dark:border-zinc-700">
                <td className="py-3 pr-4 font-semibold text-green-600 dark:text-green-400 w-24">核心催化劑</td>
                <td className="py-3 text-zinc-600 dark:text-zinc-400">{data.key_catalyst}</td>
              </tr>
              <tr>
                <td className="py-3 pr-4 font-semibold text-amber-600 dark:text-amber-400 w-24">隱藏風險</td>
                <td className="py-3 text-zinc-600 dark:text-zinc-400">{data.hidden_risk}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Summary */}
      <div className="rounded-xl border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950 p-6">
        <p className="text-xs font-medium text-blue-600 dark:text-blue-400 uppercase tracking-wide mb-3">執行摘要</p>
        <p className="text-sm text-blue-900 dark:text-blue-100 leading-relaxed">{data.summary}</p>
      </div>
    </div>
  );
}
