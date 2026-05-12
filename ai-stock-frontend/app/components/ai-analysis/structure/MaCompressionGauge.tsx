interface MaCompressionGaugeProps {
  compressionRatio: number;
  isCompressed: boolean;
}

/**
 * Topic E MA compression gauge.
 */
export function MaCompressionGauge({ compressionRatio, isCompressed }: MaCompressionGaugeProps) {
  const pct = Math.max(0, Math.min(10, compressionRatio * 100));
  const width = Math.max(4, Math.min(100, (pct / 10) * 100));
  const tone = isCompressed ? 'bg-emerald-500' : 'bg-blue-500';

  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-[22px] py-5 dark:border-zinc-700 dark:bg-zinc-950/60">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">MA 壓縮度</p>
        <p className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{pct.toFixed(1)}%</p>
      </div>
      <div className="relative mt-3 h-3 rounded-full bg-zinc-200 dark:bg-zinc-700">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
        <div className="absolute left-[30%] top-[-4px] h-5 w-px bg-amber-500" title="3% 壓縮警戒線" />
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-zinc-400 dark:text-zinc-500">
        <span>0%</span>
        <span>3% 警戒</span>
        <span>10%</span>
      </div>
      <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-300">
        {isCompressed ? '能量壓縮，密切關注突破方向。' : '均線尚未進入極端壓縮，趨勢延續性較重要。'}
      </p>
    </div>
  );
}
