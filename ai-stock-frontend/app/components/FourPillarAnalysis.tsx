'use client';

import { useState } from 'react';
import type {
  FundamentalAnalysis,
  TechnicalAnalysis,
  ChipAnalysis,
  NewsAnalysis,
} from '@/lib/types';

interface Props {
  fundamental?: FundamentalAnalysis | null;
  technical?: TechnicalAnalysis | null;
  chip?: ChipAnalysis | null;
  news?: NewsAnalysis | null;
}

export default function FourPillarAnalysis({
  fundamental,
  technical,
  chip,
  news,
}: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    fundamental: false,
    technical: false,
    chip: false,
    news: false,
  });

  const toggle = (key: string) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  if (!fundamental && !technical && !chip && !news) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">四大分析柱</h3>

      {/* Fundamental Analysis */}
      {fundamental && (
        <PillarCard
          title="基本面 (Fundamental)"
          subtitle={fundamental.revenue_trend}
          summary={fundamental.summary}
          confidence={fundamental.confidence}
          isExpanded={expanded.fundamental}
          onToggle={() => toggle('fundamental')}
          content={
            <div className="space-y-2 text-sm">
              <div>
                <p className="font-semibold text-zinc-700 dark:text-zinc-300">營收趨勢</p>
                <p className="text-zinc-500 dark:text-zinc-400">{fundamental.revenue_trend}</p>
              </div>
              {fundamental.profitability && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">獲利能力</p>
                  <div className="text-zinc-500 dark:text-zinc-400">
                    <p>趨勢: {fundamental.profitability.trend}</p>
                    {fundamental.profitability.quality && (
                      <p>品質: {fundamental.profitability.quality}</p>
                    )}
                  </div>
                </div>
              )}
              {fundamental.valuation && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">估值</p>
                  <div className="text-zinc-500 dark:text-zinc-400">
                    <p>水位: {fundamental.valuation.level}</p>
                  </div>
                </div>
              )}
              {fundamental.risks && fundamental.risks.length > 0 && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">風險</p>
                  <ul className="list-inside list-disc text-zinc-500 dark:text-zinc-400">
                    {fundamental.risks.slice(0, 3).map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {fundamental.catalysts && fundamental.catalysts.length > 0 && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">催化劑</p>
                  <ul className="list-inside list-disc text-zinc-500 dark:text-zinc-400">
                    {fundamental.catalysts.slice(0, 3).map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          }
        />
      )}

      {/* Technical Analysis */}
      {technical && (
        <PillarCard
          title="技術面 (Technical)"
          subtitle={technical.trend}
          summary={technical.summary}
          confidence={technical.confidence}
          isExpanded={expanded.technical}
          onToggle={() => toggle('technical')}
          content={
            <div className="space-y-2 text-sm">
              <div>
                <p className="font-semibold text-zinc-700 dark:text-zinc-300">趨勢</p>
                <p className="text-zinc-500 dark:text-zinc-400">{technical.trend}</p>
              </div>
              {technical.momentum && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">動量</p>
                  <div className="text-zinc-500 dark:text-zinc-400">
                    {technical.momentum.rsi && <p>RSI: {technical.momentum.rsi}</p>}
                    {technical.momentum.rsi_signal && (
                      <p>信號: {technical.momentum.rsi_signal}</p>
                    )}
                  </div>
                </div>
              )}
              {technical.key_levels && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">關鍵位置</p>
                  <div className="text-zinc-500 dark:text-zinc-400">
                    {technical.key_levels.support && (
                      <p>支撐: {technical.key_levels.support}</p>
                    )}
                    {technical.key_levels.resistance && (
                      <p>阻力: {technical.key_levels.resistance}</p>
                    )}
                  </div>
                </div>
              )}
              {technical.risks && technical.risks.length > 0 && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">風險</p>
                  <ul className="list-inside list-disc text-zinc-500 dark:text-zinc-400">
                    {technical.risks.slice(0, 3).map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          }
        />
      )}

      {/* Chip/Institutional Analysis */}
      {chip && (
        <PillarCard
          title="籌碼面 (Chip)"
          subtitle={chip.institutional_sentiment?.foreign?.trend || '中立'}
          summary={chip.summary}
          confidence={chip.confidence}
          isExpanded={expanded.chip}
          onToggle={() => toggle('chip')}
          content={
            <div className="space-y-2 text-sm">
              {chip.institutional_sentiment && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">機構情緒</p>
                  <div className="text-zinc-500 dark:text-zinc-400">
                    {chip.institutional_sentiment.foreign && (
                      <p>
                        外資:{' '}
                        {chip.institutional_sentiment.foreign.trend || '中立'}
                      </p>
                    )}
                    {chip.institutional_sentiment.domestic_fund && (
                      <p>
                        投信:{' '}
                        {chip.institutional_sentiment.domestic_fund.trend || '中立'}
                      </p>
                    )}
                  </div>
                </div>
              )}
              {chip.chip_position && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">籌碼位置</p>
                  <p className="text-zinc-500 dark:text-zinc-400">
                    {chip.chip_position.overall_trend || '中立'}
                  </p>
                </div>
              )}
              {chip.signals && chip.signals.length > 0 && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">信號</p>
                  <ul className="list-inside list-disc text-zinc-500 dark:text-zinc-400">
                    {chip.signals.slice(0, 3).map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          }
        />
      )}

      {/* News/Sentiment Analysis */}
      {news && (
        <PillarCard
          title="消息面 (News)"
          subtitle={news.sentiment_aggregate?.trend || '中立'}
          summary={news.summary}
          confidence={news.confidence}
          isExpanded={expanded.news}
          onToggle={() => toggle('news')}
          content={
            <div className="space-y-2 text-sm">
              {news.sentiment_aggregate && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">情緒評分</p>
                  <div className="text-zinc-500 dark:text-zinc-400">
                    <p>
                      看好: {news.sentiment_aggregate.bullish_count} |{' '}
                      中立: {news.sentiment_aggregate.neutral_count} |{' '}
                      看壞: {news.sentiment_aggregate.bearish_count}
                    </p>
                    <p>
                      整體評分: {(
                        news.sentiment_aggregate.overall_score * 100
                      ).toFixed(0)}%
                    </p>
                    <p>趨勢: {news.sentiment_aggregate.trend}</p>
                  </div>
                </div>
              )}
              {news.key_catalysts && news.key_catalysts.length > 0 && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">催化劑</p>
                  <div className="text-zinc-500 dark:text-zinc-400 space-y-1">
                    {news.key_catalysts.slice(0, 2).map((c, i) => (
                      <div key={i}>
                        <p>{c.event}</p>
                        {c.date && (
                          <p className="text-xs text-zinc-400">{c.date}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {news.risks && news.risks.length > 0 && (
                <div>
                  <p className="font-semibold text-zinc-700 dark:text-zinc-300">風險</p>
                  <ul className="list-inside list-disc text-zinc-500 dark:text-zinc-400">
                    {news.risks.slice(0, 2).map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          }
        />
      )}
    </div>
  );
}

interface PillarCardProps {
  title: string;
  subtitle: string;
  summary: string;
  confidence: number;
  isExpanded: boolean;
  onToggle: () => void;
  content: React.ReactNode;
}

function PillarCard({
  title,
  subtitle,
  summary,
  confidence,
  isExpanded,
  onToggle,
  content,
}: PillarCardProps) {
  const confidenceColor =
    confidence > 0.7 ? 'text-green-600 dark:text-green-400' :
    confidence > 0.5 ? 'text-amber-600 dark:text-amber-400' :
    'text-red-600 dark:text-red-400';

  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-start justify-between hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
      >
        <div className="flex-1 text-left">
          <div className="flex items-center gap-2">
            <h4 className="font-semibold text-zinc-700 dark:text-zinc-300">{title}</h4>
            <span className="text-xs px-2 py-1 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
              {subtitle}
            </span>
          </div>
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-1 line-clamp-2">
            {summary}
          </p>
          <div className="flex items-center gap-2 mt-2">
            <div className="flex-1 h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-full overflow-hidden max-w-xs">
              <div
                className={`h-full ${
                  confidence > 0.7 ? 'bg-green-500' :
                  confidence > 0.5 ? 'bg-amber-500' :
                  'bg-red-500'
                }`}
                style={{ width: `${confidence * 100}%` }}
              />
            </div>
            <span className={`text-xs font-semibold ${confidenceColor}`}>
              {(confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
        <span
          className={`text-zinc-400 transition-transform flex-shrink-0 text-lg leading-none ${
            isExpanded ? 'rotate-90' : ''
          }`}
        >
          ›
        </span>
      </button>

      {isExpanded && (
        <div className="border-t border-zinc-200 dark:border-zinc-800 px-4 py-3 bg-zinc-50 dark:bg-zinc-800/50">
          {content}
        </div>
      )}
    </div>
  );
}
