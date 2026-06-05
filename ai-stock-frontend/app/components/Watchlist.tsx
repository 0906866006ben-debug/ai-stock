'use client';

import { useEffect, useMemo, useState } from 'react';
import { getTwScreenQualityBatch, syncTelegramWatchlist } from '@/lib/api';
import type { DurabilityMetrics } from '@/lib/types';

interface FavoriteItem {
  code: string;
  name: string;
}

interface Props {
  favorites: FavoriteItem[];
  recents: FavoriteItem[];
  onSelect: (code: string, name: string) => void;
  onRemoveFavorite: (code: string) => void;
  onClearRecents: () => void;
  telegramEnabled: boolean;
}

export default function Watchlist({
  favorites,
  recents,
  onSelect,
  onRemoveFavorite,
  onClearRecents,
  telegramEnabled,
}: Props) {
  const [qualityByCode, setQualityByCode] = useState<Record<string, DurabilityMetrics | null>>({});
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>('desc');
  const [minQuality, setMinQuality] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    const codes = favorites.map((item) => item.code).filter((code) => !(code in qualityByCode));
    if (codes.length === 0) return;

    getTwScreenQualityBatch(codes).then((results) => {
      if (cancelled) return;
      setQualityByCode((prev) => {
        const next = { ...prev };
        results.forEach(([code, metrics]) => {
          next[code] = metrics;
        });
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [favorites, qualityByCode]);

  const sortedFavorites = useMemo(() => {
    return favorites
      .filter((item) => {
        const score = qualityByCode[item.code]?.score;
        return minQuality <= 0 || (typeof score === 'number' && score >= minQuality);
      })
      .slice()
      .sort((a, b) => {
        const av = qualityByCode[a.code]?.score ?? -1;
        const bv = qualityByCode[b.code]?.score ?? -1;
        return sortDir === 'desc' ? bv - av : av - bv;
      });
  }, [favorites, minQuality, qualityByCode, sortDir]);

  async function handleRemove(code: string) {
    onRemoveFavorite(code);
    if (telegramEnabled) {
      try {
        await syncTelegramWatchlist('remove', code);
      } catch {
        // silent — local removal already done
      }
    }
  }

  function qualityTone(score: number | null | undefined): string {
    if (score == null) return 'text-zinc-400';
    if (score >= 70) return 'text-emerald-600 dark:text-emerald-400';
    if (score >= 50) return 'text-amber-600 dark:text-amber-400';
    return 'text-rose-600 dark:text-rose-400';
  }

  function trendMark(metrics: DurabilityMetrics | null | undefined): string {
    if (metrics?.trend === 'improving') return '↑';
    if (metrics?.trend === 'declining') return '↓';
    if (metrics?.trend === 'stable') return '→';
    return '';
  }

  return (
    <div className="space-y-6">
      {/* Favorites */}
      <div>
        <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          ★ 自選清單 ({favorites.length})
        </h3>
        {favorites.length === 0 ? (
          <p className="text-sm text-zinc-400">尚無自選股票。在「股票目錄」中點擊 ☆ 新增。</p>
        ) : (
          <>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))}
              className="rounded-md border border-zinc-200 px-2 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Quality {sortDir === 'desc' ? '高到低' : '低到高'}
            </button>
            <label className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
              Q ≥
              <select
                value={minQuality}
                onChange={(event) => setMinQuality(Number(event.target.value))}
                className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
              >
                <option value={0}>全部</option>
                <option value={50}>50</option>
                <option value={60}>60</option>
                <option value={70}>70</option>
              </select>
            </label>
          </div>
          <div className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {sortedFavorites.map((item) => {
              const metrics = qualityByCode[item.code];
              const score = metrics?.score;
              return (
              <div
                key={item.code}
                className="flex items-center justify-between px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
              >
                <button
                  onClick={() => onSelect(item.code, item.name)}
                  className="flex flex-1 items-center gap-2 text-left"
                >
                  <span className="font-mono text-sm font-medium text-zinc-800 dark:text-zinc-100">
                    {item.code}
                  </span>
                  <span className="text-sm text-zinc-500">{item.name}</span>
                </button>
                <span className={`mr-3 w-16 text-right font-mono text-sm font-semibold ${qualityTone(score)}`}>
                  {score == null ? '-' : Math.round(score)}{trendMark(metrics)}
                </span>
                <button
                  onClick={() => handleRemove(item.code)}
                  className="ml-2 text-xs text-zinc-400 hover:text-red-500"
                >
                  移除
                </button>
              </div>
            );})}
          </div>
          </>
        )}
      </div>

      {/* Recent searches */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            最近搜尋 ({recents.length})
          </h3>
          {recents.length > 0 && (
            <button
              onClick={onClearRecents}
              className="text-xs text-zinc-400 hover:text-red-500"
            >
              清除
            </button>
          )}
        </div>
        {recents.length === 0 ? (
          <p className="text-sm text-zinc-400">尚無搜尋紀錄。</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {recents.map((item) => (
              <button
                key={item.code}
                onClick={() => onSelect(item.code, item.name)}
                className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                {item.code} {item.name}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
