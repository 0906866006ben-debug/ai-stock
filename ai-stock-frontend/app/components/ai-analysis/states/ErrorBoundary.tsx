interface ErrorBoundaryProps {
  error?: Error | null;
  onRetry: () => void;
}

/**
 * Recoverable AI analysis error state.
 */
export function ErrorBoundary({ error, onRetry }: ErrorBoundaryProps) {
  return (
    <div className="rounded-xl border border-red-200 bg-white p-6 text-center dark:border-red-800 dark:bg-zinc-900">
      <h2 className="text-base font-semibold text-red-700 dark:text-red-300">
        AI 分析暫時不可用
      </h2>
      <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
        {error?.message ?? '資料讀取失敗，請稍後再試。'}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
      >
        重新分析
      </button>
    </div>
  );
}
