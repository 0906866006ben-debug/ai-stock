'use client';

import { NewsItem } from '@/lib/api';

interface NewsSectionProps {
  news: NewsItem[];
}

function formatDate(iso: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
}

export default function NewsSection({ news }: NewsSectionProps) {
  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Recent News
      </h3>

      {news.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-400 dark:text-zinc-500">
          No recent news available.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-zinc-100 dark:divide-zinc-800">
          {news.map((item, i) => (
            <li key={i} className="py-3 first:pt-0 last:pb-0">
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-zinc-800 hover:text-blue-600 dark:text-zinc-200 dark:hover:text-blue-400"
                >
                  {item.title}
                </a>
              ) : (
                <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                  {item.title}
                </p>
              )}
              <p className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">
                {item.source}
                {item.published_at && ` · ${formatDate(item.published_at)}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
