'use client';

import { useState } from 'react';
import { analyzeStock, StockAnalysisResponse } from '@/lib/api';
import SearchBar from './components/SearchBar';
import AnalysisCard from './components/AnalysisCard';
import StockChart from './components/StockChart';
import NewsSection from './components/NewsSection';
import FinancialSummary from './components/FinancialSummary';

export default function DashboardPage() {
  const [result, setResult] = useState<StockAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(symbol: string) {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeStock(symbol);
      setResult(data);
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

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
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
        {/* Search */}
        <SearchBar onSearch={handleSearch} loading={loading} />

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

        {/* Results */}
        {result && !loading && (
          <>
            {/* Data source badge */}
            <div className="flex justify-end">
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  result.data_source === 'live'
                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                    : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                }`}
              >
                {result.data_source === 'live' ? '● Live Data' : '● Demo Data'}
              </span>
            </div>

            <AnalysisCard data={result} />
            <StockChart chartData={result.chart_data} symbol={result.symbol} />
            <NewsSection news={result.recent_news} />
            <FinancialSummary summary={result.financial_summary} />

            {/* Disclaimer */}
            <p className="text-center text-xs text-zinc-400 dark:text-zinc-500 pb-4">
              This is financial analysis support only, not financial advice.
              All AI-generated content is for informational purposes only.
              Always consult a qualified financial advisor before making investment decisions.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
