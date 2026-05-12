import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { ScenarioCard } from './ScenarioCard';

interface ScenarioPlaybookProps {
  data: AIAnalysisResult;
}

/**
 * Layer 3: side-by-side bullish and bearish playbooks.
 */
export function ScenarioPlaybook({ data }: ScenarioPlaybookProps) {
  return (
    <section className="space-y-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Playbook
        </p>
        <h2 className="text-lg font-bold text-zinc-950 dark:text-zinc-50">
          情境劇本
        </h2>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ScenarioCard scenario={data.bullish_scenario} />
        <ScenarioCard scenario={data.bearish_scenario} />
      </div>
    </section>
  );
}
