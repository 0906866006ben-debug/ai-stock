import type { SwingPivot } from '@/types/aiAnalysis';

interface SwingPivotChartProps {
  pivots: SwingPivot[];
  height?: number;
}

/**
 * Topic D swing pivot mini chart.
 */
export function SwingPivotChart({ pivots, height = 150 }: SwingPivotChartProps) {
  if (pivots.length === 0) {
    return (
      <div className="rounded-lg bg-zinc-50 px-[22px] py-5 text-sm text-zinc-500 dark:bg-zinc-950 dark:text-zinc-400">
        暫無 swing pivot 資料
      </div>
    );
  }

  const width = 640;
  const prices = pivots.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = Math.max(max - min, 1);
  const points = pivots.map((pivot, index) => {
    const x = 28 + index * ((width - 56) / Math.max(pivots.length - 1, 1));
    const y = 20 + (1 - (pivot.price - min) / range) * (height - 50);
    return { ...pivot, x, y };
  });
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');

  return (
    <div className="overflow-x-auto">
      <svg
        role="img"
        aria-label="最近 swing pivot 結構圖"
        viewBox={`0 0 ${width} ${height}`}
        className="min-w-[640px]"
      >
        <title>最近 swing pivot 結構</title>
        <desc>上三角代表 swing high，下三角代表 swing low，空心代表尚未確認。</desc>
        <path d={path} fill="none" className="stroke-zinc-300 dark:stroke-zinc-700" strokeWidth="2" />
        {points.map((point) => (
          <g key={`${point.date}-${point.type}-${point.price}`}>
            {point.type === 'high' ? (
              <path
                d={`M ${point.x} ${point.y - 8} L ${point.x - 7} ${point.y + 6} L ${point.x + 7} ${point.y + 6} Z`}
                className={point.is_confirmed ? 'fill-red-500' : 'fill-white stroke-red-500 dark:fill-zinc-900'}
                strokeWidth="2"
              />
            ) : (
              <path
                d={`M ${point.x} ${point.y + 8} L ${point.x - 7} ${point.y - 6} L ${point.x + 7} ${point.y - 6} Z`}
                className={point.is_confirmed ? 'fill-emerald-500' : 'fill-white stroke-emerald-500 dark:fill-zinc-900'}
                strokeWidth="2"
              />
            )}
            <text x={point.x - 18} y={height - 10} className="fill-zinc-400 text-[10px]">
              {point.date.slice(5)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
