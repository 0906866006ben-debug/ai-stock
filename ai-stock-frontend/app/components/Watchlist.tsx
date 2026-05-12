'use client';

import { syncTelegramWatchlist } from '@/lib/api';

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
          <div className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {favorites.map((item) => (
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
                <button
                  onClick={() => handleRemove(item.code)}
                  className="ml-2 text-xs text-zinc-400 hover:text-red-500"
                >
                  移除
                </button>
              </div>
            ))}
          </div>
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
