interface LowQualityBannerProps {
  score: number;
}

/**
 * Data quality downgrade banner used when analysis confidence has been capped.
 */
export function LowQualityBanner({ score }: LowQualityBannerProps) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
      資料完整度偏低（{score}/100），AI 判讀已自動保守化。
    </div>
  );
}
