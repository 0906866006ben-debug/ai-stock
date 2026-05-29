/**
 * Data quality banner for mock analysis payloads.
 */
export function MockDataBanner() {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800 dark:border-red-800 dark:bg-red-950/60 dark:text-red-200">
      示範資料：目前顯示的是 fallback / mock 資料分析，不能當作真實投資判斷。
    </div>
  );
}
