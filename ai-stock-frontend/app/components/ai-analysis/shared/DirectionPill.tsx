import type { Direction } from '@/types/aiAnalysis';
import { DIRECTION_STYLES } from '@/lib/ai-analysis/constants';

interface DirectionPillProps {
  direction: Direction;
  size?: 'sm' | 'md' | 'lg';
}

/**
 * Topic P shared direction marker: keeps directional labels consistent across verdict,
 * horizons, and scenario views.
 */
export function DirectionPill({ direction, size = 'md' }: DirectionPillProps) {
  const style = DIRECTION_STYLES[direction];
  const sizeClass = size === 'lg'
    ? 'px-3 py-1.5 text-sm'
    : size === 'sm'
      ? 'px-2 py-0.5 text-xs'
      : 'px-2.5 py-1 text-xs';

  return (
    <span
      role="status"
      aria-label={`方向 ${style.label}`}
      className={`inline-flex items-center gap-1 rounded-full border font-semibold ${sizeClass} ${style.bg} ${style.text} ${style.border}`}
    >
      <span aria-hidden="true">{style.icon}</span>
      {style.label}
    </span>
  );
}
