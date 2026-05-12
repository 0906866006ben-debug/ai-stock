import type { EvidenceSource } from '@/types/aiAnalysis';
import { SOURCE_STYLES } from '@/lib/ai-analysis/constants';

interface SourceTagProps {
  source: EvidenceSource;
}

/**
 * Topic A evidence provenance marker: every visible evidence row carries a source.
 */
export function SourceTag({ source }: SourceTagProps) {
  const style = SOURCE_STYLES[source];

  return (
    <span
      title={style.description}
      className={`inline-flex h-6 min-w-6 items-center justify-center rounded-full px-2 text-xs font-bold ${style.bg} ${style.text}`}
    >
      {style.label}
    </span>
  );
}
