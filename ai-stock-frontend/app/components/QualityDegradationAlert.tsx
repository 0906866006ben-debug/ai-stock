'use client';

import { useMemo, useState } from 'react';
import type { DurabilityMetrics, Position } from '@/lib/types';

interface Props {
  positions: Position[];
  qualityByCode: Record<string, DurabilityMetrics | null>;
}

export default function QualityDegradationAlert({ positions, qualityByCode }: Props) {
  const [dismissed, setDismissed] = useState(false);
  const affected = useMemo(() => {
    return positions
      .map((pos) => ({ pos, change: qualityByCode[pos.stock_code]?.change_yoy ?? null }))
      .filter((item): item is { pos: Position; change: number } => typeof item.change === 'number' && item.change <= -10);
  }, [positions, qualityByCode]);

  if (dismissed || affected.length === 0) return null;

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-100">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{affected.length} 檔持股品質分數年減超過 10 分</p>
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-200">
            {affected.map((item) => `${item.pos.stock_code} ${item.change.toFixed(1)}`).join('、')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="rounded-md px-2 py-1 text-xs text-amber-700 hover:bg-amber-100 dark:text-amber-200 dark:hover:bg-amber-900/40"
        >
          關閉
        </button>
      </div>
    </div>
  );
}
