'use client';

import { useState } from 'react';
import { SCORE_AXIS_CONFIG } from '@/lib/ai-analysis/constants';
import type { ThreeAxisScore } from '@/types/aiAnalysis';

interface Props {
  scores: ThreeAxisScore;
  size?: 'lg' | 'md' | 'sm';
  layout?: 'horizontal' | 'stacked';
}

export function ThreeAxisScoreBar({
  scores,
  size = 'lg',
  layout = 'horizontal',
}: Props) {
  if (layout === 'stacked') {
    return <StackedVariant scores={scores} size={size} />;
  }
  return <HorizontalVariant scores={scores} size={size} />;
}

function HorizontalVariant({ scores, size }: { scores: ThreeAxisScore; size: 'lg' | 'md' | 'sm' }) {
  const sizes = {
    lg: { value: 26, label: 11, bar: 3, padding: '14px 16px' },
    md: { value: 20, label: 10, bar: 2, padding: '10px 12px' },
    sm: { value: 16, label: 10, bar: 2, padding: '8px 10px' },
  }[size];

  return (
    <div className="grid grid-cols-3 gap-3.5">
      <ScoreCard axis="signal" value={scores.signal} sizes={sizes} />
      <ScoreCard
        axis="confidence"
        value={scores.confidence}
        sizes={sizes}
        cappedReason={scores.confidence_cap_reason}
      />
      <ScoreCard axis="risk" value={scores.risk} sizes={sizes} />
    </div>
  );
}

function StackedVariant({ scores }: { scores: ThreeAxisScore; size: 'lg' | 'md' | 'sm' }) {
  return (
    <div className="flex justify-between gap-1.5">
      <CompactScore axis="signal" value={scores.signal} />
      <CompactScore
        axis="confidence"
        value={scores.confidence}
        cappedReason={scores.confidence_cap_reason}
      />
      <CompactScore axis="risk" value={scores.risk} />
    </div>
  );
}

interface ScoreCardProps {
  axis: keyof typeof SCORE_AXIS_CONFIG;
  value: number;
  sizes: { value: number; label: number; bar: number; padding: string };
  cappedReason?: string;
}

function ScoreCard({ axis, value, sizes, cappedReason }: ScoreCardProps) {
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const config = SCORE_AXIS_CONFIG[axis];
  const roundedValue = Math.round(value);

  return (
    <div
      className="rounded-md"
      style={{
        background: 'var(--color-background-secondary)',
        padding: sizes.padding,
      }}
    >
      <div
        className="mb-2 flex items-center justify-between uppercase"
        style={{ fontSize: `${sizes.label}px`, color: 'var(--color-text-tertiary)', letterSpacing: '0.04em' }}
      >
        <span className="flex items-center gap-1.5">
          {config.label}
          {cappedReason && (
            <span
              aria-label={`信心受限：${cappedReason}`}
              style={{ fontSize: '11px' }}
            >
              鎖
            </span>
          )}
        </span>
        <button
          type="button"
          onMouseEnter={() => setTooltipOpen(true)}
          onMouseLeave={() => setTooltipOpen(false)}
          onFocus={() => setTooltipOpen(true)}
          onBlur={() => setTooltipOpen(false)}
          className="relative rounded px-1 outline-none focus:ring-2 focus:ring-blue-400"
          aria-label={`${config.label} 說明`}
        >
          i
          {tooltipOpen && (
            <div
              role="tooltip"
              className="absolute right-0 top-5 z-10 w-64 rounded-md p-3 text-left shadow-lg"
              style={{
                background: 'var(--color-background-primary)',
                border: '0.5px solid var(--color-border-secondary)',
                fontSize: '12px',
                lineHeight: 1.5,
                color: 'var(--color-text-secondary)',
                fontWeight: 400,
                textTransform: 'none',
                letterSpacing: 'normal',
              }}
            >
              {config.tooltip}
            </div>
          )}
        </button>
      </div>

      <div
        className="font-medium leading-none"
        style={{
          fontSize: `${sizes.value}px`,
          color: 'var(--color-text-primary)',
        }}
        aria-label={`${config.label} ${roundedValue} 分，滿分 100`}
      >
        {roundedValue}
        <span
          className="ml-1 font-normal"
          style={{
            fontSize: '13px',
            color: 'var(--color-text-secondary)',
          }}
        >
          /100
        </span>
      </div>

      <div
        className="mt-3 overflow-hidden rounded-sm"
        style={{
          height: `${sizes.bar}px`,
          background: 'var(--color-border-tertiary)',
        }}
      >
        <div
          className="h-full rounded-sm transition-all duration-300"
          style={{
            width: `${Math.max(0, Math.min(100, roundedValue))}%`,
            background: config.color,
          }}
        />
      </div>
    </div>
  );
}

function CompactScore({
  axis,
  value,
  cappedReason,
}: {
  axis: keyof typeof SCORE_AXIS_CONFIG;
  value: number;
  cappedReason?: string;
}) {
  const config = SCORE_AXIS_CONFIG[axis];
  const roundedValue = Math.round(value);

  return (
    <div className="flex-1 text-center">
      <div
        className="flex items-center justify-center gap-1 font-medium leading-none"
        style={{ fontSize: '14px', color: config.color }}
      >
        {roundedValue}
        {cappedReason && (
          <span
            aria-label={`信心受限：${cappedReason}`}
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
        {config.label.replace('技術', '').replace('分析', '').replace('追價', '')}
      </div>
    </div>
  );
}
