import type { ReportSection } from '@/types/aiAnalysis';

interface ReportAccordionRowProps {
  section: ReportSection;
}

/**
 * Layer 6 report section row using native details for accessibility.
 */
export function ReportAccordionRow({ section }: ReportAccordionRowProps) {
  return (
    <details className="group border-b border-zinc-100 py-3 last:border-b-0 dark:border-zinc-800">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 rounded-lg px-2 py-1 outline-none focus:ring-2 focus:ring-blue-400">
        <div>
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{section.title}</h3>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{section.preview}</p>
        </div>
        <span className="mt-1 text-zinc-400 transition-transform group-open:rotate-90">›</span>
      </summary>
      <div className="px-2 pb-2 pt-3 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
        {section.body_markdown.split('\n').filter(Boolean).map((paragraph) => (
          <p key={paragraph} className="mb-2 last:mb-0">
            {paragraph.replace(/^#+\s*/, '')}
          </p>
        ))}
      </div>
    </details>
  );
}
