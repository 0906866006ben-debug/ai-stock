'use client';

import { useState, useEffect } from 'react';
import { getExternalNews } from '@/lib/api';
import type { ExternalNewsItem } from '@/lib/types';

const CATEGORIES: { key: string; label: string }[] = [
  { key: 'market', label: '大盤環境' },
  { key: 'interest', label: '利率政策' },
  { key: 'fx', label: '匯率' },
  { key: 'industry', label: '產業景氣' },
  { key: 'global', label: '國際股市' },
  { key: 'commodity', label: '原物料' },
  { key: 'geopolitics', label: '地緣政治' },
  { key: 'policy', label: '政策法規' },
];

export default function ExternalNews() {
  const [activeTab, setActiveTab] = useState('market');
  const [data, setData] = useState<Record<string, ExternalNewsItem[]>>({});
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getExternalNews()
      .then((result) => {
        if (!cancelled) {
          setData(result.categories);
          setStatus(result.status);
        }
      })
      .catch(() => {
        if (!cancelled) setData({});
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const items = data[activeTab] ?? [];

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-200">市場環境新聞</h2>
        {status && (
          <span className={`rounded-full px-2 py-0.5 text-xs ${
            status === 'live'
              ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
          }`}>
            {status === 'live' ? '● Live' : '● Mock'}
          </span>
        )}
      </div>

      {/* Category tabs */}
      <div className="mb-4 flex gap-1 flex-wrap">
        {CATEGORIES.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              activeTab === key
                ? 'bg-blue-600 text-white'
                : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300'
            }`}
          >
            {label}
            {data[key]?.length ? (
              <span className="ml-1 opacity-70">({data[key].length})</span>
            ) : null}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      ) : items.length === 0 ? (
        <p className="py-4 text-center text-sm text-zinc-400">此分類暫無新聞</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item, i) => (
            <li key={i} className="border-b border-zinc-100 pb-3 last:border-0 dark:border-zinc-800">
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  {item.title}
                </a>
              ) : (
                <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{item.title}</p>
              )}
              <div className="mt-1 flex gap-3 text-xs text-zinc-400">
                {item.source && <span>{item.source}</span>}
                {item.published_at && <span>{item.published_at}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
