'use client';

import { useState } from 'react';
import type { WyckoffPhase } from '@/types/aiAnalysis';
import { WYCKOFF_PHASE_DESCRIPTIONS, WYCKOFF_PHASE_LABELS } from '@/lib/ai-analysis/i18n';

interface WyckoffPhaseIndicatorProps {
  phase: WyckoffPhase;
}

type MajorPhase = 'accumulation' | 'markup' | 'distribution' | 'markdown';

const MAJOR_PHASES: Array<{
  key: MajorPhase;
  label: string;
  subLabel: string;
  phases: WyckoffPhase[];
}> = [
  {
    key: 'accumulation',
    label: '累積期',
    subLabel: 'A·B·C·D·E',
    phases: ['accumulation_a', 'accumulation_b', 'accumulation_c', 'accumulation_d', 'accumulation_e'],
  },
  {
    key: 'markup',
    label: '主升段',
    subLabel: 'Markup',
    phases: ['markup'],
  },
  {
    key: 'distribution',
    label: '派發期',
    subLabel: 'A·B·C·D·E',
    phases: ['distribution_a', 'distribution_b', 'distribution_c', 'distribution_d', 'distribution_e'],
  },
  {
    key: 'markdown',
    label: '主跌段',
    subLabel: 'Markdown',
    phases: ['markdown'],
  },
];

const DETAIL_PHASES: WyckoffPhase[] = [
  'accumulation_a',
  'accumulation_b',
  'accumulation_c',
  'accumulation_d',
  'accumulation_e',
  'markup',
  'distribution_a',
  'distribution_b',
  'distribution_c',
  'distribution_d',
  'distribution_e',
  'markdown',
  'unclear',
];

function currentMajorPhase(phase: WyckoffPhase): MajorPhase | 'unclear' {
  if (phase.startsWith('accumulation')) return 'accumulation';
  if (phase === 'markup') return 'markup';
  if (phase.startsWith('distribution')) return 'distribution';
  if (phase === 'markdown') return 'markdown';
  return 'unclear';
}

function activeStyle(major: MajorPhase) {
  if (major === 'distribution' || major === 'markdown') {
    return { background: '#FAEEDA', color: '#854F0B', border: '#BA7517' };
  }
  return { background: '#EAF3DE', color: '#27500A', border: '#3B6D11' };
}

/**
 * Topic D corrected Wyckoff view: four readable major phases with optional v1 subphase detail.
 */
export function WyckoffPhaseIndicator({ phase }: WyckoffPhaseIndicatorProps) {
  const [expanded, setExpanded] = useState(false);
  const activeMajor = currentMajorPhase(phase);

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        {MAJOR_PHASES.map((major) => {
          const active = major.key === activeMajor;
          const style = active
            ? activeStyle(major.key)
            : { background: 'var(--color-background-secondary)', color: 'var(--color-text-secondary)', border: 'var(--color-border-tertiary)' };

          return (
            <div
              key={major.key}
              aria-current={active ? 'step' : undefined}
              className="rounded-md border px-[22px] py-5 text-center"
              style={{
                background: style.background,
                color: style.color,
                borderColor: style.border,
              }}
            >
              <p className="text-sm font-bold">{major.label}</p>
              <p className="mt-1 text-xs opacity-80">{major.subLabel}</p>
              {active && (
                <p className="mt-2 text-xs font-semibold">
                  當前：{WYCKOFF_PHASE_LABELS[phase]}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="mt-3 rounded-md px-2 py-1 text-xs font-semibold text-blue-700 outline-none hover:bg-blue-50 focus:ring-2 focus:ring-blue-400 dark:text-blue-300 dark:hover:bg-blue-950"
      >
        {expanded ? '收合子相位' : '查看子相位 ↗'}
      </button>

      {expanded && (
        <div className="mt-3 rounded-md border border-zinc-200 bg-zinc-50 px-[22px] py-5 dark:border-zinc-700 dark:bg-zinc-950/60">
          <p className="text-xs font-semibold text-zinc-500 dark:text-zinc-400">
            v1 規則：細分相位尚未驗證，僅作為結構輔助閱讀。
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {DETAIL_PHASES.map((item) => (
              <span
                key={item}
                title={WYCKOFF_PHASE_DESCRIPTIONS[item]}
                className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                  item === phase
                    ? 'bg-blue-600 text-white'
                    : 'bg-white text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300'
                }`}
              >
                {WYCKOFF_PHASE_LABELS[item]}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
