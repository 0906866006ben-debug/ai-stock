'use client';

interface FinancialSummaryProps {
  summary: Record<string, string>;
}

function formatKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function FinancialSummary({ summary }: FinancialSummaryProps) {
  const entries = Object.entries(summary);

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Financial Summary
      </h3>

      {entries.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-400 dark:text-zinc-500">
          No financial data available.
        </p>
      ) : (
        <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {entries.map(([key, value]) => (
            <div
              key={key}
              className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800"
            >
              <dt className="text-xs text-zinc-500 dark:text-zinc-400">
                {formatKey(key)}
              </dt>
              <dd className="mt-0.5 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                {value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
