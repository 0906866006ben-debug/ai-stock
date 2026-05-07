'use client';

import { useState } from 'react';
import { analyzeStock, analyzeTW, StockAnalysisResponse } from '@/lib/api';
import { TaiwanStockAnalysisResponse } from '@/lib/types';
import SearchBar from './components/SearchBar';
import TwSearchBar from './components/TwSearchBar';
import AnalysisCard from './components/AnalysisCard';
import StockChart from './components/StockChart';
import NewsSection from './components/NewsSection';
import FinancialSummary from './components/FinancialSummary';

type Mode = 'us' | 'tw';

type Result =
  | { mode: 'us'; data: StockAnalysisResponse }
  | { mode: 'tw'; data: TaiwanStockAnalysisResponse };

export default function DashboardPage() {
  const [mode, setMode] = useState<Mode>('us');
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function switchMode(next: Mode) {
    setMode(next);
    setResult(null);
    setError(null);
  }

  async function handleUsSearch(symbol: string) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeStock(symbol);
      setResult({ mode: 'us', data });
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Failed to fetch analysis. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleTwSearch(symbol: string) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeTW(symbol);
      setResult({ mode: 'tw', data });
    } catch {
      setError('無法取得台股分析，請確認股票代碼後重試。');
    } finally {
      setLoading(false);
    }
  }

  const usResult = result?.mode === 'us' ? result.data : null;
  const twResult = result?.mode === 'tw' ? result.data : null;

  const twFinancialSummary: Record<string, string> = twResult
    ? {
        '幣別': twResult.currency,
        '市場': twResult.market_type,
        '最新收盤價': `NT$${twResult.current_price.toFixed(2)}`,
        '漲跌幅': `${twResult.price_change_percent >= 0 ? '+' : ''}${twResult.price_change_percent.toFixed(2)}%`,
        '成交量': twResult.volume.toLocaleString(),
      }
    : {};

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-3xl px-4 py-4">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">
            AI Stock Analysis
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Financial analysis support — not financial advice
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 space-y-6">
        {/* Mode toggle */}
        <div className="flex w-fit rounded-lg border border-zinc-200 bg-white p-1 dark:border-zinc-700 dark:bg-zinc-900">
          <button
            onClick={() => switchMode('us')}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              mode === 'us'
                ? 'bg-blue-600 text-white'
                : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50'
            }`}
          >
            US Stocks
          </button>
          <button
            onClick={() => switchMode('tw')}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              mode === 'tw'
                ? 'bg-blue-600 text-white'
                : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50'
            }`}
          >
            台灣股市
          </button>
        </div>

        {/* Search */}
        {mode === 'us' ? (
          <SearchBar onSearch={handleUsSearch} loading={loading} />
        ) : (
          <TwSearchBar onSearch={handleTwSearch} loading={loading} />
        )}

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          </div>
        )}

        {/* US Results */}
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
            <StockChart chartType="line" chartData={usResult.chart_data} symbol={usResult.symbol} />
            <NewsSection news={usResult.recent_news} locale="en" />
            <FinancialSummary summary={usResult.financial_summary} />
            <p className="pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
              This is financial analysis support only, not financial advice.
              All AI-generated content is for informational purposes only.
              Always consult a qualified financial advisor before making investment decisions.
            </p>
          </>
        )}

        {/* Taiwan Results */}
        {twResult && !loading && (
          <>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-400 dark:text-zinc-500">
                {new Date(twResult.analyzed_at).toLocaleString('zh-TW')}
              </span>
              <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                twResult.data_source === 'live'
                  ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                  : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
              }`}>
                {twResult.data_source === 'live' ? '● 即時資料' : '● 模擬資料'}
              </span>
            </div>
            <AnalysisCard data={twResult} />
            <StockChart chartType="candlestick" chartData={twResult.chart_data} symbol={twResult.symbol} />
            <NewsSection news={twResult.recent_news} locale="zh" />
            <FinancialSummary summary={twFinancialSummary} />
            <p className="pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
              {twResult.disclaimer}
            </p>
          </>
        )}
      </main>
    </div>
  );
}
