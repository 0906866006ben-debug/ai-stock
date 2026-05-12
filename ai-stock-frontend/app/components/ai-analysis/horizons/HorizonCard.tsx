import type { HorizonView, Horizon } from '@/types/aiAnalysis';
import {
  TECHNICAL_STATE_LABEL_ZH,
  HORIZON_TIME_RANGE_LABEL,
} from '@/lib/ai-analysis/i18n';
import { DirectionPill } from '../shared/DirectionPill';
import { SCORE_AXIS_CONFIG } from '@/lib/ai-analysis/constants';

interface Props {
  view: HorizonView;
}

const HORIZON_LABELS: Record<Horizon, string> = {
  short_term: '短線',
  swing: '波段',
  long_term: '長線',
};

const TOTAL_FACTOR_CATEGORIES = 6;

/**
 * Topic B/C corrected horizon card. The same five information blocks remain
 * visible at every viewport width.
 */
export function HorizonCard({ view }: Props) {
  const stateMeta = TECHNICAL_STATE_LABEL_ZH[view.technical_state];
  const consensusCount = view.categories_in_agreement.length;
  const isInsufficient = consensusCount < 3;

  return (
    <article
      className="rounded-md"
      style={{
        background: isInsufficient
          ? 'var(--color-background-secondary)'
          : 'var(--color-background-primary)',
        border: '0.5px solid var(--color-border-tertiary)',
        padding: '20px 22px',
        opacity: isInsufficient ? 0.72 : 1,
      }}
    >
      <header className="mb-2.5 flex items-center justify-between gap-3">
        <span
          style={{
            fontSize: '11px',
            color: 'var(--color-text-tertiary)',
            letterSpacing: '0.04em',
          }}
        >
          {HORIZON_LABELS[view.horizon]} {HORIZON_TIME_RANGE_LABEL[view.horizon]}
        </span>
        <DirectionPill direction={view.direction} size="sm" />
      </header>

      <h3
        style={{
          fontSize: '15px',
          fontWeight: 600,
          marginBottom: '4px',
          color: 'var(--color-text-primary)',
        }}
      >
        {stateMeta.label}
      </h3>

      <p
        style={{
          fontSize: '12px',
          color: 'var(--color-text-secondary)',
          lineHeight: 1.5,
          marginBottom: '12px',
        }}
      >
        {view.state_detail || stateMeta.short_description}
      </p>

      <ConsensusBar count={consensusCount} total={TOTAL_FACTOR_CATEGORIES} />

      <ThreeScoreRow scores={view.scores} />
    </article>
  );
}

function ConsensusBar({ count, total }: { count: number; total: number }) {
  return (
    <div
      className="mb-3 flex items-center gap-1.5"
      style={{ fontSize: '11px', color: 'var(--color-text-tertiary)' }}
      aria-label={`因子類別共識：${count} / ${total}`}
    >
      <span>{`${count} / ${total} 因子類別同意`}</span>
      <div className="ml-1 flex gap-0.5">
        {Array.from({ length: total }).map((_, i) => (
          <span
            key={i}
            style={{
              width: '8px',
              height: '3px',
              borderRadius: '1px',
              background: i < count ? '#3B6D11' : 'var(--color-border-secondary)',
            }}
          />
        ))}
      </div>
    </div>
  );
}

function ThreeScoreRow({ scores }: { scores: HorizonView['scores'] }) {
  return (
    <div className="flex justify-between gap-1.5" role="group" aria-label="三軸分數">
      <ScoreCell axis="signal" value={scores.signal} />
      <ScoreCell axis="confidence" value={scores.confidence} cappedReason={scores.confidence_cap_reason} />
      <ScoreCell axis="risk" value={scores.risk} />
    </div>
  );
}

function ScoreCell({
  axis,
  value,
  cappedReason,
}: {
  axis: 'signal' | 'confidence' | 'risk';
  value: number;
  cappedReason?: string;
}) {
  const config = SCORE_AXIS_CONFIG[axis];
  const shortLabels = { signal: '訊號', confidence: '信心', risk: '風險' } as const;

  return (
    <div className="flex-1 text-center">
      <div
        className="flex items-center justify-center gap-1"
        style={{
          fontSize: '14px',
          fontWeight: 600,
          color: config.color,
          lineHeight: 1,
        }}
      >
        {Math.round(value)}
        {cappedReason && (
          <span
            aria-label={`受限：${cappedReason}`}
            style={{ fontSize: '10px' }}
          >
            鎖
          </span>
        )}
      </div>
      <div
        className="mt-1"
        style={{ fontSize: '10px', color: 'var(--color-text-tertiary)' }}
      >
        {shortLabels[axis]}
      </div>
    </div>
  );
}
