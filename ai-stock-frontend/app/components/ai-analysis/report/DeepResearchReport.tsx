import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { ReportAccordionRow } from './ReportAccordionRow';

interface DeepResearchReportProps {
  data: AIAnalysisResult;
}

/**
 * Layer 6: optional deep research sections, collapsed by default.
 */
export function DeepResearchReport({ data }: DeepResearchReportProps) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white px-[22px] py-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Deep Research
        </p>
        <h2 className="text-lg font-bold text-zinc-950 dark:text-zinc-50">
          深度研究報告
        </h2>
      </div>
      <div className="mt-3">
        {data.report_sections.map((section) => (
          <ReportAccordionRow key={section.key} section={section} />
        ))}
      </div>
    </section>
  );
}
