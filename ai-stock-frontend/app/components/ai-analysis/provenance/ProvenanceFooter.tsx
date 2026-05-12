import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { DataQualityIndicator } from './DataQualityIndicator';

interface ProvenanceFooterProps {
  data: AIAnalysisResult;
  onRecompute?: () => void | Promise<void>;
}

/**
 * Layer 7 provenance footer: sources, models, rule version, and recompute.
 */
export function ProvenanceFooter({ data, onRecompute }: ProvenanceFooterProps) {
  async function handleRecompute() {
    const confirmed = window.confirm('重新分析將消耗一次 API 配額，是否繼續？');
    if (!confirmed) return;
    await onRecompute?.();
  }

  return (
    <footer className="flex flex-col gap-3 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400 sm:flex-row sm:items-center sm:justify-between">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <DataQualityIndicator quality={data.data_quality} score={data.data_quality_score} />
          {data.is_v1_hypothesis && (
            <span className="rounded-full bg-zinc-100 px-2 py-1 font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              v1 未回測假設
            </span>
          )}
        </div>
        <p>資料來源：{data.data_sources.join(' + ')}</p>
        <p>模型：{data.models_used.join(' + ')} / 規則 v{data.rule_set_version.replace(/^v/, '')}</p>
        <p>
          分析時間：{new Date(data.analyzed_at).toLocaleString('zh-TW')} / 下次更新：{new Date(data.next_update_at).toLocaleString('zh-TW')}
        </p>
      </div>
      {onRecompute && (
        <button
          type="button"
          onClick={handleRecompute}
          className="self-start rounded-lg border border-zinc-300 px-3 py-2 text-sm font-semibold text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800 sm:self-center"
        >
          立即重算
        </button>
      )}
    </footer>
  );
}
