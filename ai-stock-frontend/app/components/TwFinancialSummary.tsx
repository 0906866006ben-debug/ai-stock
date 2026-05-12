'use client';

interface TwFinancialSummaryProps {
  currency: string;
  market_type: string;
  current_price: number;
  price_change_percent: number;
  volume: number;
}

export default function TwFinancialSummary({
  currency,
  market_type,
  current_price,
  price_change_percent,
  volume,
}: TwFinancialSummaryProps) {
  const changePositive = price_change_percent >= 0;

  const entries: { label: string; value: string; highlight?: string }[] = [
    { label: '幣別', value: currency },
    { label: '市場', value: market_type },
    { label: '最新收盤價', value: `${current_price.toFixed(2)} ${currency}` },
    {
      label: '漲跌幅',
      value: `${changePositive ? '+' : ''}${price_change_percent.toFixed(2)}%`,
      highlight: changePositive ? 'text-green-600' : 'text-red-500',
    },
    { label: '成交量', value: volume.toLocaleString('zh-TW') },
  ];

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        市場資訊
      </h3>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {entries.map(({ label, value, highlight }) => (
          <div key={label} className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800">
            <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className={`mt-0.5 text-sm font-semibold ${highlight ?? 'text-zinc-800 dark:text-zinc-100'}`}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
