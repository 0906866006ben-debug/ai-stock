import type { KouDiAnalysis } from '@/types/aiAnalysis';

interface Props {
  data: KouDiAnalysis;
  daysToShow?: number;
}

const COLOR_UPWARD = ['#EAF3DE', '#C0DD97', '#97C459', '#639922', '#3B6D11'];
const COLOR_DOWNWARD = ['#FAEEDA', '#FAC775', '#EF9F27', '#BA7517', '#854F0B'];
const COLOR_FLAT = '#F1EFE8';

/**
 * Topic E production KouDi visual: future MA deduction pressure over 20 days.
 */
export function KouDiTimeline({ data, daysToShow = 20 }: Props) {
  const cells = buildCellData(data, daysToShow);
  const criticalDays = data.critical_kou_di_points.filter(
    (p) => p.day_offset >= 0 && p.day_offset <= daysToShow
  );
  const segments = computeSegments(cells);

  return (
    <section aria-labelledby={`kou-di-heading-${data.ma_window}`}>
      <div
        className="mb-2.5 flex items-baseline justify-between gap-3"
        style={{ fontSize: '11px', color: 'var(--color-text-tertiary)' }}
      >
        <span id={`kou-di-heading-${data.ma_window}`}>
          MA{data.ma_window} 扣抵值預測（未來 {daysToShow} 日）
          <span className="ml-3" style={{ color: 'var(--color-text-secondary)' }}>
            <span
              className="mr-1 inline-block h-2 w-2 rounded-sm align-middle"
              style={{ background: '#3B6D11' }}
            />
            助漲
            <span
              className="ml-3 mr-1 inline-block h-2 w-2 rounded-sm align-middle"
              style={{ background: '#BA7517' }}
            />
            沉重
          </span>
        </span>
        {criticalDays[0] && (
          <span style={{ color: '#BA7517' }}>
            {`! T+${criticalDays[0].day_offset} 關鍵點 (${formatPct(criticalDays[0].distance_pct)})`}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1 overflow-x-auto">
        <span
          style={{
            fontSize: '10px',
            color: 'var(--color-text-tertiary)',
            width: '24px',
          }}
        >
          今
        </span>
        {cells.map((cell, idx) => (
          <div
            key={idx}
            title={`T+${idx + 1}: ${cell.tooltip}`}
            className="shrink-0 rounded-sm"
            style={{
              width: '18px',
              height: '24px',
              background: cell.color,
              outline: cell.isCritical ? '1px solid #BA7517' : 'none',
            }}
            aria-label={`第 ${idx + 1} 日：${cell.tooltip}`}
          />
        ))}
        <span
          style={{
            fontSize: '10px',
            color: 'var(--color-text-tertiary)',
            width: '30px',
            textAlign: 'right',
          }}
        >
          T+{daysToShow}
        </span>
      </div>

      {segments.length > 0 && (
        <div
          className="mt-1.5 flex justify-between px-6"
          style={{ fontSize: '10px', color: 'var(--color-text-tertiary)' }}
        >
          {segments.map((seg, idx) => (
            <span key={`${seg.direction}-${idx}`}>
              {seg.direction === 'upward' ? '助漲' : seg.direction === 'downward' ? '沉重' : '持平'}
              {` ${seg.length} 日`}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

interface CellData {
  color: string;
  tooltip: string;
  intensity: number;
  direction: 'upward' | 'downward' | 'flat';
  isCritical: boolean;
}

function buildCellData(data: KouDiAnalysis, days: number): CellData[] {
  const cells: CellData[] = [];

  for (let i = 0; i < days; i++) {
    const dayOffset = i + 1;
    const inUpward = data.upward_pressure_periods.find(
      (p) => dayOffset >= p.start_day_offset && dayOffset <= p.end_day_offset
    );
    const inDownward = data.downward_pressure_periods.find(
      (p) => dayOffset >= p.start_day_offset && dayOffset <= p.end_day_offset
    );
    const critical = data.critical_kou_di_points.find((p) => p.day_offset === dayOffset);

    if (inUpward) {
      const intensity = inUpward.intensity;
      const colorIdx = Math.min(4, Math.floor(intensity * 5));
      cells.push({
        color: COLOR_UPWARD[colorIdx],
        tooltip: `助漲（強度 ${(intensity * 100).toFixed(0)}%）`,
        intensity,
        direction: 'upward',
        isCritical: !!critical,
      });
    } else if (inDownward) {
      const intensity = inDownward.intensity;
      const colorIdx = Math.min(4, Math.floor(intensity * 5));
      cells.push({
        color: COLOR_DOWNWARD[colorIdx],
        tooltip: `沉重（強度 ${(intensity * 100).toFixed(0)}%）`,
        intensity,
        direction: 'downward',
        isCritical: !!critical,
      });
    } else {
      cells.push({
        color: COLOR_FLAT,
        tooltip: '扣抵值持平',
        intensity: 0,
        direction: 'flat',
        isCritical: !!critical,
      });
    }
  }

  return cells;
}

function computeSegments(cells: CellData[]) {
  const segments: Array<{ direction: CellData['direction']; length: number }> = [];
  let current: { direction: CellData['direction']; length: number } | null = null;

  for (const cell of cells) {
    if (current && current.direction === cell.direction) {
      current.length += 1;
    } else {
      if (current) segments.push(current);
      current = { direction: cell.direction, length: 1 };
    }
  }
  if (current) segments.push(current);

  return segments.filter((s) => s.length >= 2);
}

function formatPct(pct: number): string {
  return pct >= 0 ? `+${pct.toFixed(1)}%` : `${pct.toFixed(1)}%`;
}
