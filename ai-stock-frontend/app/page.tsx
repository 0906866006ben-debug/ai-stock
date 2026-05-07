'use client';

import { useState } from 'react';
import { analyzeStock, analyzeTW, StockAnalysisResponse } from '@/lib/api';
import { TaiwanStockAnalysisResponse } from '@/lib/types';
import TwSearchBar from './components/TwSearchBar';
import AnalysisCard from './components/AnalysisCard';
import TwAnalysisCard from './components/TwAnalysisCard';
import StockChart from './components/StockChart';
import NewsSection from './components/NewsSection';
import FinancialSummary from './components/FinancialSummary';
import TwFinancialSummary from './components/TwFinancialSummary';

const TW_RE = /^\d{4,6}$/;

export default function DashboardPage() {
  const [usResult, setUsResult] = useState<StockAnalysisResponse | null>(null);
  const [twResult, setTwResult] = useState<TaiwanStockAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(symbol: string) {
    setLoading(true);
    setError(null);

    try {
      if (TW_RE.test(symbol)) {
        const data = await analyzeTW(symbol);
        setTwResult(data);
        setUsResult(null);
      } else {
        const data = await analyzeStock(symbol);
        setUsResult(data);
        setTwResult(null);
      }
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : '查詢失敗，請稍後再試。';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-3xl px-4 py-4">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">
            AI 股票分析
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            支援台灣股票（輸入數字代碼）及美股（輸入英文代碼）
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 space-y-6">
        <TwSearchBar onSearch={handleSearch} loading={loading} />

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          </div>
        )}

        {/* Taiwan results */}
        {twResult && !loading && (
          <>
            <TwAnalysisCard data={twResult} />
            <StockChart chartData={twResult.chart_data} symbol={twResult.symbol} mode="candle" />
            <TwFinancialSummary
              currency={twResult.currency}
              market_type={twResult.market_type}
              current_price={twResult.current_price}
              price_change_percent={twResult.price_change_percent}
              volume={twResult.volume}
            />
            <NewsSection news={twResult.recent_news} />
            <p className="pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
              {twResult.disclaimer}
            </p>
            <p className="-mt-4 pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
              分析時間：{new Date(twResult.analyzed_at).toLocaleString('zh-TW')}
            </p>
          </>
        )}

        {/* US results */}
        {usResult && !loading && (
          <>
            <div className="flex justify-end">
              <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                usResult.data_source === 'live'
                  ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                  : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
              }`}>
                {usResult.data_source === 'live' ? '● Live Data' : '● Demo Data'}
              </span>
            </div>
            <AnalysisCard data={usResult} />
            <StockChart chartData={usResult.chart_data} symbol={usResult.symbol} />
            <NewsSection news={usResult.recent_news} />
            <FinancialSummary summary={usResult.financial_summary} />
            <p className="pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
              This is financial analysis support only, not financial advice.
              Always consult a qualified financial advisor before making investment decisions.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
