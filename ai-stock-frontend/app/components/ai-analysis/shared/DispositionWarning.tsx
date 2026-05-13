import type { DispositionStatus } from '@/types/aiAnalysis';
import { DISPOSITION_MESSAGES } from '@/lib/ai-analysis/constants';

interface DispositionWarningProps {
  status: DispositionStatus;
}

/**
 * Topic M status banner: clearly downgrades technical interpretation when Taiwan
 * market disposition rules distort trading mechanics.
 */
export function DispositionWarning({ status }: DispositionWarningProps) {
  if (status === 'normal') return null;

  const message = DISPOSITION_MESSAGES[status];
  const className = message.level === 'danger'
    ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/60 dark:text-red-200'
    : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200';

  return (
    <div className={`rounded-lg border px-4 py-3 text-sm font-medium ${className}`}>
      {message.text}
    </div>
  );
}
