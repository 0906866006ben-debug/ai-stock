'use client';

import { useEffect, useState } from 'react';

// ---- Types (mirror backend/scripts/export_backtest_dashboard_data.py output) ----
type Period = 'dev' | 'oos';
type Grade = 'S' | 'A' | 'B' | 'C';
type Metric = 'excu' | 'exc';

interface MetricStat { median: number; win_rate: number; n: number }
interface WindowStats { excu: MetricStat | null; exc: MetricStat | null; n_signals: number }
interface BucketData {
  label: string;
  status: 'production' | 'retired';
  n_total: number;
  grades: Partial<Record<Grade, Partial<Record<Period, Record<string, WindowStats>>>>>;
}
interface YearlyRow { year: string; n: number; median_excu: number; win_rate: number }
interface HistBin { lo: number; hi: number; count: number; is_loss: boolean }
interface Histogram { window: number; n: number; median: number; mean: number; win_rate: number; bins: HistBin[] }
interface DashboardData {
  generated_at: string;
  meta: {
    windows: number[];
    dev_range: [string, string];
    oos_range: [string, string];
    round_trip_cost_bps: number;
    benchmarks: { excu: string; exc: string };
    caveats: string[];
  };
  headline: { bucket: string; grade: string; window: number; dev: MetricStat | null; oos: MetricStat | null };
  buckets: { long: BucketData };
  yearly: { long: YearlyRow[] };
  histogram: { long: Histogram | null };
  disclaimer: string;
}

const WINDOWS = [5, 20, 60, 120, 250];
const GRADES: Grade[] = ['S', 'A', 'B', 'C'];

// Grade accent deliberately avoids red/green — this view already uses red/green
// exhaustively for return sign (紅漲綠跌), so grade tiers get their own hue ramp
// (violet → amber → sky → zinc) to prevent "green badge = bad" misreads.
const GRADE_STYLE: Record<Grade, string> = {
  S: 'bg-violet-600 text-white',
  A: 'bg-amber-500 text-white',
  B: 'bg-sky-600 text-white',
  C: 'bg-zinc-400 text-white dark:bg-zinc-500',
};

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return '—';
  const s = (v * 100).toFixed(digits);
  return v > 0 ? `+${s}%` : `${s}%`;
}
function fmtRate(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${Math.round(v * 100)}%`;
}
// 台股慣例：正 = 紅（漲／獲利）、負 = 綠（跌／虧損）。一律搭配正負號文字，不單靠顏色。
function returnTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v) || v === 0) return 'text-zinc-400 dark:text-zinc-500';
  return v > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400';
}

function GradeBadge({ grade }: { grade: Grade }) {
  return (
    <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${GRADE_STYLE[grade]}`}>
      {grade}
    </span>
  );
}

// ── Yearly stability bars (long bucket S+A, T+60 median excess vs buyable pool) ──
function YearlyBars({ rows, muted }: { rows: YearlyRow[]; muted?: boolean }) {
  if (rows.length === 0) return <p className="text-xs text-zinc-400 dark:text-zinc-500">無資料</p>;
  const maxAbs = Math.max(0.005, ...rows.map((r) => Math.abs(r.median_excu)));
  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-max items-end gap-2 px-1">
        {rows.map((r) => {
          const hPct = Math.max(3, (Math.abs(r.median_excu) / maxAbs) * 100);
          const positive = r.median_excu > 0;
          return (
            <div key={r.year} className="flex w-9 flex-col items-center gap-1">
              <span className={`font-mono text-[10px] tabular-nums ${muted ? 'text-zinc-400 dark:text-zinc-500' : returnTone(r.median_excu)}`}>
                {fmtPct(r.median_excu, 1)}
              </span>
              <div className="flex h-24 w-full flex-col justify-end">
                <div
                  title={`${r.year}：中位超額 ${fmtPct(r.median_excu)}，勝率 ${fmtRate(r.win_rate)}，n=${r.n}`}
                  style={{ height: `${hPct}%` }}
                  className={`w-full rounded-t-sm ${
                    muted
                      ? 'bg-zinc-400/50 dark:bg-zinc-600/60'
                      : positive
                        ? 'bg-red-500/85 dark:bg-red-400/80'
                        : 'bg-green-500/85 dark:bg-green-400/80'
                  }`}
                />
              </div>
              <span className="text-[10px] text-zinc-400 dark:text-zinc-500">{r.year}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Profit/loss distribution histogram (raw T+N return, marked with median) ──
function HistogramChart({ hist }: { hist: Histogram }) {
  const maxCount = Math.max(1, ...hist.bins.map((b) => b.count));
  const lo = hist.bins[0].lo;
  const hi = hist.bins[hist.bins.length - 1].hi;
  const span = hi - lo || 1;
  const medianPct = Math.min(98, Math.max(2, ((hist.median - lo) / span) * 100));
  const zeroPct = Math.min(100, Math.max(0, ((0 - lo) / span) * 100));

  return (
    <div>
      <div className="relative h-40">
        <div className="flex h-40 items-end gap-[2px]">
          {hist.bins.map((b, i) => {
            const hPct = Math.max(2, (b.count / maxCount) * 100);
            return (
              <div
                key={i}
                title={`${fmtPct(b.lo, 0)} ~ ${fmtPct(b.hi, 0)}：${b.count.toLocaleString()} 筆`}
                style={{ height: `${hPct}%` }}
                className={`flex-1 rounded-t-[1px] ${
                  b.is_loss ? 'bg-green-500/70 dark:bg-green-400/60' : 'bg-red-500/70 dark:bg-red-400/60'
                }`}
              />
            );
          })}
        </div>
        {/* 0% reference line */}
        <div
          className="pointer-events-none absolute top-0 h-40 border-l border-zinc-300 dark:border-zinc-600"
          style={{ left: `${zeroPct}%` }}
        />
        {/* median marker */}
        <div
          className="pointer-events-none absolute top-0 h-40 border-l border-dashed border-zinc-600 dark:border-zinc-200"
          style={{ left: `${medianPct}%` }}
        >
          <span className="absolute -top-4 -translate-x-1/2 whitespace-nowrap font-mono text-[10px] font-semibold text-zinc-600 dark:text-zinc-200">
            中位 {fmtPct(hist.median, 1)}
          </span>
        </div>
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] tabular-nums text-zinc-400 dark:text-zinc-500">
        <span>{fmtPct(lo, 0)}</span>
        <span>0%</span>
        <span>{fmtPct(hi, 0)}</span>
      </div>
    </div>
  );
}

// ── Grade × window monotonicity table (one period) ──
function GradeTable({ bucket, period, metric }: { bucket: BucketData; period: Period; metric: Metric }) {
  const rows = GRADES.filter((g) => bucket.grades[g]?.[period]);
  if (rows.length === 0) {
    return <p className="px-1 py-3 text-xs text-zinc-400 dark:text-zinc-500">此期間無資料</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] text-xs">
        <thead>
          <tr className="border-b border-zinc-200 text-left text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            <th className="py-1.5 pr-2 font-medium">級</th>
            {WINDOWS.map((w) => (
              <th key={w} className="py-1.5 pr-3 text-right font-medium">T+{w}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => {
            const stats = bucket.grades[g]?.[period];
            return (
              <tr key={g} className="border-b border-zinc-100 dark:border-zinc-800/60">
                <td className="py-1.5 pr-2">
                  <GradeBadge grade={g} />
                </td>
                {WINDOWS.map((w) => {
                  const s = stats?.[String(w)];
                  const m = s?.[metric];
                  return (
                    <td key={w} className="py-1.5 pr-3 text-right font-mono tabular-nums">
                      <div className={returnTone(m?.median)}>{fmtPct(m?.median)}</div>
                      <div className="text-[10px] text-zinc-400 dark:text-zinc-500">
                        {fmtRate(m?.win_rate)} · n={m?.n ?? 0}
                      </div>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SectionHeader({ eyebrow, title, hint }: { eyebrow: string; title: string; hint?: string }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{eyebrow}</p>
      <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
      {hint && <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>}
    </div>
  );
}

// Note: unlike the other data views, this dashboard reads a pre-aggregated static
// JSON bundled at build time (public/backtest_dashboard.json), not a live backend
// endpoint — the underlying canonical databases don't exist in the cloud deployment.
export default function BacktestDashboardView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [metric, setMetric] = useState<Metric>('excu');

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/backtest_dashboard.json', { cache: 'no-store' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        setData(await r.json());
      } catch (e) {
        setErr(e instanceof Error ? e.message : '載入失敗');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  let generatedAt: string | null = null;
  if (data?.generated_at) {
    try {
      generatedAt = new Date(data.generated_at).toLocaleString('zh-TW');
    } catch {
      generatedAt = data.generated_at;
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-violet-500 border-t-transparent" />
      </div>
    );
  }
  if (err || !data) {
    return (
      <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
        載入失敗：{err || '無資料'}（請先執行 backend/scripts/export_backtest_dashboard_data.py 產生
        public/backtest_dashboard.json）
      </p>
    );
  }

  const long = data.buckets.long;

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="rounded-2xl border border-purple-200 bg-gradient-to-r from-pink-50 to-purple-50 p-5 dark:border-purple-900/50 dark:from-pink-950/30 dark:to-purple-950/30">
        <h2 className="text-lg font-bold text-purple-700 dark:text-purple-300">📊 回測儀表板</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          每日選股回測（{long.label}）完整結果——分年穩定性、報酬分佈、S/A/B/C 分級單調性。
          {generatedAt && ` 資料產生時間：${generatedAt}`}
        </p>
      </div>

      {/* ── Headline: dark quant hero card ── */}
      <div className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 p-6 shadow-xl">
        <div className="pointer-events-none absolute -top-16 -left-10 h-56 w-56 rounded-full bg-violet-600/25 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 -right-10 h-64 w-64 rounded-full bg-cyan-500/15 blur-3xl" />
        <div className="relative">
          <p className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
            核心結論 · {long.label} · A 級 · T+{data.headline.window}
          </p>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-[11px] text-zinc-400">DEV 中位超額（{data.meta.dev_range[0].slice(0, 4)}–{data.meta.dev_range[1].slice(0, 4)}）</p>
              <p className={`mt-1 font-mono text-3xl font-bold tabular-nums ${returnTone(data.headline.dev?.median)}`}>
                {fmtPct(data.headline.dev?.median)}
              </p>
              <p className="mt-0.5 font-mono text-[11px] tabular-nums text-zinc-500">
                勝率 {fmtRate(data.headline.dev?.win_rate)} · n={data.headline.dev?.n ?? 0}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-zinc-400">OOS 中位超額（{data.meta.oos_range[0].slice(0, 4)}–）</p>
              <p className={`mt-1 font-mono text-3xl font-bold tabular-nums ${returnTone(data.headline.oos?.median)}`}>
                {fmtPct(data.headline.oos?.median)}
              </p>
              <p className="mt-0.5 font-mono text-[11px] tabular-nums text-zinc-500">
                勝率 {fmtRate(data.headline.oos?.win_rate)} · n={data.headline.oos?.n ?? 0}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-zinc-400">累計樣本數（DEV+OOS）</p>
              <p className="mt-1 font-mono text-3xl font-bold tabular-nums text-zinc-100">
                {(data.headline.dev?.n ?? 0) + (data.headline.oos?.n ?? 0)}
              </p>
              <p className="mt-0.5 text-[11px] text-zinc-500">A 級以上事件，長線價值桶</p>
            </div>
            <div>
              <p className="text-[11px] text-zinc-400">基準</p>
              <p className="mt-1 text-sm font-semibold text-zinc-200">{data.meta.benchmarks.excu}</p>
              <p className="mt-0.5 text-[11px] text-zinc-500">扣來回成本 {data.meta.round_trip_cost_bps}bp</p>
            </div>
          </div>
        </div>
      </div>

      {/* ── Honesty callouts ── */}
      <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
        <p className="mb-1 font-semibold">⚠️ 誠實標註（判讀前必讀）</p>
        <ul className="list-inside list-disc space-y-0.5">
          {data.meta.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      </div>

      {/* ── Yearly stability ── */}
      <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <SectionHeader
          eyebrow="Stability"
          title="分年穩定性——長線桶 A 級以上 T+60"
          hint={`每年中位超額報酬（${data.meta.benchmarks.excu}）；紅＝正、綠＝負，數字含正負號。`}
        />
        <YearlyBars rows={data.yearly.long} />
      </section>

      {/* ── Profit/loss distribution ── */}
      {data.histogram.long && (
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <SectionHeader
            eyebrow="Distribution"
            title={`獲利／虧損分佈——長線桶 T+${data.histogram.long.window} 原始報酬`}
            hint="S/A/B 級事件全樣本（未扣除基準），虛線標中位數、實線標 0%。"
          />
          <HistogramChart hist={data.histogram.long} />
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
            <span>n = {data.histogram.long.n.toLocaleString()}</span>
            <span>中位 = {fmtPct(data.histogram.long.median)}</span>
            <span>平均 = {fmtPct(data.histogram.long.mean)}</span>
            <span>正報酬比例 = {fmtRate(data.histogram.long.win_rate)}</span>
          </div>
        </section>
      )}

      {/* ── Grade monotonicity: long bucket ── */}
      <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <SectionHeader
            eyebrow="Monotonicity"
            title="S/A/B/C 分級單調性——長線桶（DEV vs OOS）"
            hint="理想上 S ≥ A ≥ B ≥ C；OOS 樣本較小，波動較大屬預期。"
          />
          <div className="flex shrink-0 gap-1 rounded-full border border-zinc-200 p-0.5 text-[11px] dark:border-zinc-700">
            {(['excu', 'exc'] as Metric[]).map((m) => (
              <button
                key={m}
                onClick={() => setMetric(m)}
                className={`rounded-full px-2.5 py-1 font-medium transition-colors ${
                  metric === m
                    ? 'bg-violet-600 text-white'
                    : 'text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
                }`}
              >
                {m === 'excu' ? '選股力（vs 可買池）' : '脈絡參考（vs TAIEX）'}
              </button>
            ))}
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="mb-1.5 text-xs font-semibold text-zinc-500 dark:text-zinc-400">
              DEV（{data.meta.dev_range[0]} ~ {data.meta.dev_range[1]}）
            </p>
            <GradeTable bucket={long} period="dev" metric={metric} />
          </div>
          <div>
            <p className="mb-1.5 text-xs font-semibold text-zinc-500 dark:text-zinc-400">
              OOS（{data.meta.oos_range[0]} ~，已開封一次）
            </p>
            <GradeTable bucket={long} period="oos" metric={metric} />
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <div className="space-y-1 pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
        <p>
          {data.meta.benchmarks.excu} ／ {data.meta.benchmarks.exc}——兩者衡量不同問題，不可互相替代。
        </p>
        <p>{data.disclaimer}</p>
      </div>
    </div>
  );
}
