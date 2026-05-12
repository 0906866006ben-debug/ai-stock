import type { StructurePanelData } from '@/types/aiAnalysis';
import { DOW_STRUCTURE_LABELS, WYCKOFF_PHASE_LABELS } from '@/lib/ai-analysis/i18n';
import { DowStructureBadge } from './DowStructureBadge';
import { KouDiTimeline } from './KouDiTimeline';
import { MaCompressionGauge } from './MaCompressionGauge';
import { SwingPivotChart } from './SwingPivotChart';
import { WyckoffPhaseIndicator } from './WyckoffPhaseIndicator';

interface WyckoffStructurePanelProps {
  data: StructurePanelData;
}

/**
 * Layer 5 and Topics A-E bridge: structure, Wyckoff phase, swing pivots,
 * KouDi pressure, and moving-average compression.
 */
export function WyckoffStructurePanel({ data }: WyckoffStructurePanelProps) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white px-[22px] py-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Structure
        </p>
        <h2 className="text-lg font-bold text-zinc-950 dark:text-zinc-50">
          結構與相位
        </h2>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="rounded-lg border border-zinc-200 px-[22px] py-5 dark:border-zinc-700">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-zinc-500 dark:text-zinc-400">Wyckoff 相位</p>
              <p className="mt-1 text-base font-bold text-zinc-950 dark:text-zinc-50">
                {WYCKOFF_PHASE_LABELS[data.wyckoff_phase]}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs font-semibold text-zinc-500 dark:text-zinc-400">道氏結構</p>
              <p className="mt-1 text-sm font-bold text-zinc-800 dark:text-zinc-200">
                {DOW_STRUCTURE_LABELS[data.dow_structure]}
              </p>
            </div>
          </div>
          <div className="mt-4">
            <WyckoffPhaseIndicator phase={data.wyckoff_phase} />
          </div>
        </div>

        <DowStructureBadge structure={data.dow_structure} />
      </div>

      <div className="mt-6 rounded-lg border border-zinc-200 px-[22px] py-5 dark:border-zinc-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            Swing 結構
          </h3>
          {(data.spring_detected || data.utad_detected) && (
            <div className="flex flex-wrap gap-2 text-xs">
              {data.spring_detected && (
                <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
                  Spring {data.spring_detected.level} / {data.spring_detected.date}
                </span>
              )}
              {data.utad_detected && (
                <span className="rounded-full bg-amber-100 px-2 py-1 font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                  UTAD {Math.round(data.utad_detected.confidence * 100)}%
                </span>
              )}
            </div>
          )}
        </div>
        <div className="mt-3">
          <SwingPivotChart pivots={data.recent_pivots} />
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6 rounded-lg border border-zinc-200 px-[22px] py-5 dark:border-zinc-700">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            扣抵值預測
          </h3>
          <KouDiTimeline data={data.kou_di_ma20} />
          <KouDiTimeline data={data.kou_di_ma60} />
          {data.kou_di_ma120 && <KouDiTimeline data={data.kou_di_ma120} />}
        </div>
        <MaCompressionGauge
          compressionRatio={data.ma_compression_ratio}
          isCompressed={data.is_compressed}
        />
      </div>

      <div className="mt-6 rounded-lg border border-zinc-200 px-[22px] py-5 dark:border-zinc-700">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
          特殊事件偵測
        </h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {data.spring_detected ? (
            <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
              Spring：{data.spring_detected.level} / {data.spring_detected.date}
            </span>
          ) : (
            <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              無 Spring
            </span>
          )}
          {data.utad_detected ? (
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-200">
              UTAD：{Math.round(data.utad_detected.confidence * 100)}%
            </span>
          ) : (
            <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              無 UTAD
            </span>
          )}
          <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            無頂背離
          </span>
          <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            無底背離
          </span>
        </div>
      </div>
    </section>
  );
}
