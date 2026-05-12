import type { Scenario } from '@/types/aiAnalysis';
import { InfoTooltip } from '../shared/InfoTooltip';

interface ScenarioCardProps {
  scenario: Scenario;
}

/**
 * Layer 3 scenario card: makes invalidation and action rules explicit.
 */
export function ScenarioCard({ scenario }: ScenarioCardProps) {
  const isBullish = scenario.direction === 'bullish';
  const tone = isBullish
    ? 'border-l-emerald-500'
    : 'border-l-red-500';
  const titleTone = isBullish
    ? 'text-emerald-700 dark:text-emerald-300'
    : 'text-red-700 dark:text-red-300';

  return (
    <article className={`rounded-xl border border-l-4 border-zinc-200 bg-white px-[22px] py-5 dark:border-zinc-800 dark:bg-zinc-900 ${tone}`}>
      <h3 className={`text-base font-bold ${titleTone}`}>{scenario.label}</h3>
      <ul className="mt-3 space-y-2">
        {scenario.conditions.map((condition) => (
          <li key={condition.trigger_expression} className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            <InfoTooltip
              label={`監控欄位：${condition.monitored_fields.join(', ')}；條件式：${condition.trigger_expression}`}
            >
              <span className="inline-flex gap-2">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400" />
                <span>{condition.condition_text}</span>
              </span>
            </InfoTooltip>
          </li>
        ))}
      </ul>
      <div className="mt-4 rounded-lg bg-zinc-50 px-[22px] py-5 text-sm text-zinc-700 dark:bg-zinc-950/60 dark:text-zinc-300">
        <span className="font-semibold">觸發後行動：</span>
        {scenario.action_if_triggered}
      </div>
    </article>
  );
}
