'use client';

import type { MultiAgentAnalysis, AgentDataStatus } from '@/types/aiAnalysis';

interface MultiAgentAnalysisPanelProps {
  data?: MultiAgentAnalysis;
}

const STATUS_META: Record<AgentDataStatus, { label: string; className: string }> = {
  available: {
    label: '已取得',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200',
  },
  partial: {
    label: '部分資料',
    className: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200',
  },
  missing: {
    label: '缺資料',
    className: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200',
  },
  stale: {
    label: '資料偏舊',
    className: 'border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950/50 dark:text-zinc-300',
  },
};

const AGENT_STATUS_META = {
  completed: 'bg-emerald-500',
  fallback: 'bg-amber-500',
  pending: 'bg-zinc-400',
  error: 'bg-rose-500',
} as const;

export function MultiAgentAnalysisPanel({ data }: MultiAgentAnalysisPanelProps) {
  if (!data) return null;

  const final = data.claude_final;

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            FinMind → Gemini → Claude
          </p>
          <h3 className="mt-1 text-lg font-semibold text-zinc-950 dark:text-zinc-50">
            多 Agent 固定格式分析
          </h3>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-600 dark:text-zinc-300">
            FinMind 負責資料證據，Gemini 負責整理重點，Claude 負責最後審核。若 API key 或資料來源缺漏，後端會保留固定格式並標示 fallback。
          </p>
        </div>
        <div className="grid min-w-[280px] grid-cols-2 gap-2">
          <Metric label="最終狀態" value={final.status} />
          <Metric label="結論信心" value={final.confidence} />
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {data.agents.map((agent) => (
          <div key={agent.name} className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950/50">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-zinc-950 dark:text-zinc-50">{agent.name}</div>
              <span className={`h-2.5 w-2.5 rounded-full ${AGENT_STATUS_META[agent.status]}`} />
            </div>
            <p className="mt-2 text-sm leading-5 text-zinc-600 dark:text-zinc-300">{agent.role}</p>
            <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">狀態：{agent.status}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950/50">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Claude Final Review
        </div>
        <p className="mt-2 text-sm leading-6 text-zinc-700 dark:text-zinc-300">{final.conclusion}</p>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div>
          <h4 className="text-sm font-semibold text-zinc-950 dark:text-zinc-50">FinMind Evidence Packs</h4>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {data.evidence_packs.map((pack) => {
              const meta = STATUS_META[pack.status];
              return (
                <article key={pack.id} className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-zinc-950 dark:text-zinc-50">{pack.label}</div>
                      <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        {pack.source}{pack.latest_date ? ` · ${pack.latest_date}` : ''}
                      </div>
                    </div>
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.className}`}>
                      {meta.label}
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-5 text-zinc-700 dark:text-zinc-300">{pack.summary}</p>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    {pack.key_values.slice(0, 3).map((item) => (
                      <div key={item.label} className="rounded-lg bg-zinc-50 p-2 dark:bg-zinc-950/60">
                        <div className="text-[11px] text-zinc-500 dark:text-zinc-400">{item.label}</div>
                        <div className="mt-1 truncate text-xs font-semibold text-zinc-900 dark:text-zinc-100">{item.value}</div>
                      </div>
                    ))}
                  </div>
                  {pack.warnings.length > 0 && (
                    <p className="mt-3 text-xs text-amber-700 dark:text-amber-300">{pack.warnings.join('、')}</p>
                  )}
                </article>
              );
            })}
          </div>
        </div>

        <div className="space-y-4">
          <ListPanel title="Gemini 整理重點" items={data.gemini_structured.key_points} empty="尚無整理重點" />
          <ListPanel title="矛盾訊號" items={final.conflicting_signals} empty="目前未偵測到主要矛盾" />
          <ListPanel title="資料限制" items={final.data_limitations} empty="目前資料限制較少" />
          <ListPanel title="人工檢視" items={final.manual_review_required} empty="暫無人工檢視項目" />
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
      <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="mt-1 text-sm font-bold text-zinc-950 dark:text-zinc-50">{value}</div>
    </div>
  );
}

function ListPanel({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  const visibleItems = items.filter(Boolean).slice(0, 6);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h4 className="text-sm font-semibold text-zinc-950 dark:text-zinc-50">{title}</h4>
      {visibleItems.length ? (
        <ul className="mt-3 space-y-2 text-sm leading-5 text-zinc-700 dark:text-zinc-300">
          {visibleItems.map((item, index) => (
            <li key={`${title}-${index}`} className="flex gap-2">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-zinc-400 dark:text-zinc-500">{empty}</p>
      )}
    </div>
  );
}
