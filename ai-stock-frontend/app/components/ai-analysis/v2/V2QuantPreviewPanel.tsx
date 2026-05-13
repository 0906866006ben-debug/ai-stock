import type { DecimalLike, V2QuantAnalysisResult } from '@/types/aiAnalysis';

interface V2QuantPreviewPanelProps {
  data?: V2QuantAnalysisResult;
}

export function V2QuantPreviewPanel({ data }: V2QuantPreviewPanelProps) {
  if (!data) return null;

  const ma20 = data.time_boxes.ma20;
  const ma60 = data.time_boxes.ma60;
  const risk = data.risk_execution;
  const profile = data.volume_profile;
  const twoB = data.two_b_reversal;

  return (
    <section className="rounded-xl border border-zinc-200 bg-white px-[22px] py-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Quant v2.0
          </p>
          <h2 className="text-lg font-bold text-zinc-950 dark:text-zinc-50">
            時空推演與硬風控
          </h2>
        </div>
        <StatusPill label={data.fundamental_gate.status} tone={gateTone(data.fundamental_gate.status)} />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <Metric label="POC 成本區" value={formatPrice(profile.poc_price)} helper={`距離 ${formatPct(profile.poc_distance_pct)}`} />
        <Metric label="盈虧比" value={formatPlain(risk.rr_ratio)} helper={risk.rr_pass ? '通過 3:1 門檻' : '未達 3:1 門檻'} tone={risk.rr_pass ? 'good' : 'warn'} />
        <Metric label="Kelly 建議" value={formatPctFraction(risk.kelly_fraction)} helper={`單筆上限 ${formatPctFraction(risk.position_cap)}`} />
        <Metric label="2B 結構" value={twoB.status} helper={twoB.confirmed ? `收復 ${twoB.prior_low_l1}` : `BIAS120 ${formatPct(twoB.bias_120_pct)}`} tone={twoB.confirmed ? 'good' : 'neutral'} />
        <Metric label="MA20 臨界價" value={formatPrice(ma20?.p_crit)} helper={ma20?.projection_date ?? '資料不足'} />
        <Metric label="MA60 臨界價" value={formatPrice(ma60?.p_crit)} helper={ma60?.projection_date ?? '資料不足'} />
      </div>

      {risk.forced_exit && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-800 dark:border-red-800 dark:bg-red-950/60 dark:text-red-200">
          硬性風控觸發：{risk.forced_exit_reason}
        </div>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  helper,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  helper: string;
  tone?: 'neutral' | 'good' | 'warn';
}) {
  const valueColor = tone === 'good'
    ? 'text-emerald-700 dark:text-emerald-300'
    : tone === 'warn'
      ? 'text-amber-700 dark:text-amber-300'
      : 'text-zinc-950 dark:text-zinc-50';

  return (
    <div className="rounded-md border border-zinc-100 px-3 py-3 dark:border-zinc-800">
      <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className={`mt-1 text-base font-bold ${valueColor}`}>{value}</p>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{helper}</p>
    </div>
  );
}

function StatusPill({ label, tone }: { label: string; tone: 'good' | 'warn' | 'neutral' }) {
  const className = tone === 'good'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
    : tone === 'warn'
      ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300'
      : 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300';

  return (
    <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${className}`}>
      基本面 Gate：{label}
    </span>
  );
}

function gateTone(status: string): 'good' | 'warn' | 'neutral' {
  if (status === 'pass') return 'good';
  if (status === 'fail') return 'warn';
  return 'neutral';
}

function formatPrice(value?: DecimalLike | null): string {
  const number = toNumber(value);
  return number === null ? 'N/A' : number.toFixed(2);
}

function formatPlain(value?: DecimalLike | null): string {
  const number = toNumber(value);
  return number === null ? 'N/A' : number.toFixed(2);
}

function formatPct(value?: DecimalLike | null): string {
  const number = toNumber(value);
  return number === null ? 'N/A' : `${number.toFixed(2)}%`;
}

function formatPctFraction(value?: DecimalLike | null): string {
  const number = toNumber(value);
  return number === null ? 'N/A' : `${(number * 100).toFixed(1)}%`;
}

function toNumber(value?: DecimalLike | null): number | null {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
