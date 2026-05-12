'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { getTwStocks } from '@/lib/api';
import type { StockInfo } from '@/lib/types';

const MARKET_TYPES = ['全部', '上市', '上櫃', 'ETF', '興櫃'];

interface Props {
  onSelectStock?: (code: string, name: string) => void;
  favorites: string[];
  onToggleFavorite: (code: string, name: string) => void;
}

export default function StockDirectory({ onSelectStock, favorites, onToggleFavorite }: Props) {
  const [query, setQuery] = useState('');
  const [marketType, setMarketType] = useState('全部');
  const [stocks, setStocks] = useState<StockInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (q: string, type: string) => {
    setLoading(true);
    try {
      const result = await getTwStocks({
        q: q || undefined,
        stock_type: type === '全部' ? undefined : type,
        limit: 100,
      });
      const seenCodes = new Set<string>();
      const uniqueStocks = result.stocks.filter((stock) => {
        if (seenCodes.has(stock.stock_code)) return false;
        seenCodes.add(stock.stock_code);
        return true;
      });

      setStocks(uniqueStocks);
      setTotal(uniqueStocks.length);
    } catch {
      setStocks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      load(query, marketType);
    }, 260);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, marketType, load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          placeholder="搜尋股票代碼或名稱…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <div className="flex gap-1 flex-wrap">
          {MARKET_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setMarketType(t)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                marketType === t
                  ? 'bg-blue-600 text-white'
                  : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-zinc-400">共 {total} 筆，顯示前 {stocks.length} 筆</p>

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : (
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {stocks.map((s, index) => (
            <div
              key={`${s.stock_code}-${s.company_name}-${s.market_type}-${index}`}
              className="flex items-center justify-between gap-3 py-3"
            >
              <button
                onClick={() => onSelectStock?.(s.stock_code, s.company_name)}
                className="flex min-w-0 flex-1 items-center gap-3 text-left"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                    {s.company_name}
                  </p>
                  <p className="mt-0.5 font-mono text-xs text-zinc-500 dark:text-zinc-400">
                    {s.stock_code}
                  </p>
                </div>
                <div className="ml-auto flex flex-wrap justify-end gap-1">
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800">
                    {s.market_type}
                  </span>
                  {s.industry && (
                    <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-600 dark:bg-blue-950 dark:text-blue-400">
                      {s.industry}
                    </span>
                  )}
                </div>
              </button>
              <button
                onClick={() => onToggleFavorite(s.stock_code, s.company_name)}
                className="ml-3 text-lg leading-none"
                title={favorites.includes(s.stock_code) ? '移除自選' : '加入自選'}
              >
                {favorites.includes(s.stock_code) ? '★' : '☆'}
              </button>
            </div>
          ))}
          {stocks.length === 0 && !loading && (
            <p className="py-6 text-center text-sm text-zinc-400">查無結果</p>
          )}
        </div>
      )}
    </div>
  );
}
