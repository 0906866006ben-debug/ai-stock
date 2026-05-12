import type { DataQuality } from '@/types/aiAnalysis';
import { DATA_QUALITY_LABELS } from '@/lib/ai-analysis/constants';

interface DataQualityIndicatorProps {
  quality: DataQuality;
  score: number;
}

/**
 * Layer 7 compact quality marker.
 */
export function DataQualityIndicator({ quality, score }: DataQualityIndicatorProps) {
  const tone = score >= 75
    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
    : score >= 60
      ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
      : 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200';

  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${tone}`}>
      {DATA_QUALITY_LABELS[quality]} {score}/100
    </span>
  );
}
