'use client';

import { useState, FormEvent } from 'react';

interface TwSearchBarProps {
  onSearch: (symbol: string) => void;
  loading?: boolean;
}

const TW_RE = /^\d{4,6}$/;
const US_RE = /^[A-Z0-9]{1,10}$/;

export default function TwSearchBar({ onSearch, loading = false }: TwSearchBarProps) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    const upper = trimmed.toUpperCase();

    if (!trimmed) {
      setError('請輸入股票代碼。');
      return;
    }
    if (!TW_RE.test(trimmed) && !US_RE.test(upper)) {
      setError('請輸入有效代碼：台灣股票為 4–6 位數字（如 2330），美股為 1–10 碼英數字（如 AAPL）。');
      return;
    }
    setError('');
    onSearch(TW_RE.test(trimmed) ? trimmed : upper);
  }

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={value}
          onChange={(e) => { setValue(e.target.value); setError(''); }}
          placeholder="輸入股票代碼，例如 2330 或 AAPL"
          maxLength={10}
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-4 py-3 text-base text-zinc-900 placeholder-zinc-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder-zinc-500"
          aria-label="股票代碼"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-blue-600 px-6 py-3 text-base font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? '分析中…' : '分析'}
        </button>
      </div>
      {error && <p className="mt-1 text-sm text-red-500">{error}</p>}
    </form>
  );
}
