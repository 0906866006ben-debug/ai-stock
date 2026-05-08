'use client';

import { useState, useEffect, useCallback } from 'react';
import { getTwPriceHistory } from '@/lib/api';
import type { PriceHistoryResponse, CandlePoint } from '@/lib/types';
import StockChart from './StockChart';

type Range = '1D' | '5D' | '1W' | '1M' | '1Y';

const RANGES: Range[] = ['1D', '5D', '1W', '1M', '1Y'];

interface Props {
  stockCode: string;
  initialCandles?: CandlePoint[];
}

export default function PriceHistoryChart({ stockCode, initialCandles }: Props) {
  const [range, setRange] = useState<Range>('1M');
  const [data, setData] = useState<PriceHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(async (r: Range) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTwPriceHistory(stockCode, r);
      setData(result);
    } catch {
      setError('無法載入價格歷史');
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    fetchHistory(range);
  }, [fetchHistory, range]);

  const candles = data?.candles ?? initialCandles ?? [];

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          K 線圖
          {data?.is_mock && (
            <span className="ml-2 text-xs font-normal text-amber-500">模擬資料</span>
          )}
        </h3>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              disabled={loading}
              className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                range === r
                  ? 'bg-blue-600 text-white'
                  : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex h-32 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      )}

      {error && !loading && (
        <p className="text-sm text-red-500">{error}</p>
      )}

      {!loading && candles.length > 0 && (
        <StockChart chartData={candles} symbol={stockCode} mode="candle" />
      )}

      {!loading && !error && candles.length === 0 && (
        <p className="text-sm text-zinc-400">此期間無資料</p>
      )}
    </div>
  );
}
