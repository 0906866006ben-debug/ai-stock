interface WeightPillProps {
  weight: number;
}

/**
 * Evidence weight marker: makes bullish and bearish evidence comparable at a glance.
 */
export function WeightPill({ weight }: WeightPillProps) {
  const style = weight > 1
    ? { background: '#EAF3DE', color: '#27500A', label: `多 +${Math.abs(weight)}` }
    : weight < -1
      ? { background: '#FAEEDA', color: '#854F0B', label: `空 -${Math.abs(weight)}` }
      : { background: '#F1EFE8', color: '#444441', label: '中性' };

  return (
    <span
      className="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold"
      style={{ background: style.background, color: style.color }}
    >
      {style.label}
    </span>
  );
}
