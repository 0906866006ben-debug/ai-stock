'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';

const DEFAULT_SCAN_LIMIT = 1000;
const MAX_SCAN_LIMIT = 10000;
const PENDING_JOB_KEY = 'canslim_screener_pending_job_id';
const SAVED_RESULT_KEY = 'canslim_screener_results';

type CanslimGrade = 'S' | 'A' | 'B' | 'C' | 'D' | 'NA';
type RiskFilter = 'all' | 'clear' | 'blocked';
type PillarStatus = 'Pass' | 'Weak' | 'Fail' | 'AI_Review_Required' | 'Neutral' | 'Insufficient_Data';

interface ScreeningEvidence {
  pillar: string;
  source_url: string | null;
  published_date: string | null;
  summary: string;
  catalyst_type?: string | null;
}

interface ScreeningResult {
  stock_id: string;
  as_of_date: string;
  is_mock: boolean;
  candidate_grade: Exclude<CanslimGrade, 'NA'>;
  canslim_match: string;
  pillars: Record<'C' | 'A' | 'N' | 'S' | 'L' | 'I' | 'M', PillarStatus>;
  pillar_metrics?: Partial<Record<'C' | 'A' | 'N' | 'S' | 'L' | 'I' | 'M', string>>;
  scores?: { signal?: number; risk?: number; confidence?: number };
  market_regime: 'risk_on' | 'risk_off' | 'severe' | 'unknown';
  n_catalyst_score?: number | null;
  interpretation: string;
  evidence: ScreeningEvidence[];
  data_warnings: string[];
  needs_manual_review: string[];
  action_type: string;
}

interface HorizonObservation {
  horizon: string;
  status: string;
  direction_hint: string;
  evidence_based_reasons: string[];
  triggered_rule_ids: string[];
  key_observation_conditions: string[];
  invalidation_signals: string[];
  risk_level: string;
  confidence_level: string;
  scores: Record<string, unknown>;
  data_warnings: string[];
}

interface CandidateResult {
  rank: number;
  stock_id: string;
  stock_name: string;
  candidate_type: string;
  surge_candidate_score: number;
  confidence_score: number;
  risk_score: number;
  metrics: {
    return_60d: number;
    return_90d: number | null;
    return_20d: number;
    return_5d?: number | null;
    range_90d: number;
    avg_volume_20_lots: number;
    avg_turnover_20?: number | null;
    relative_strength_20d: number | null;
    relative_strength_60d?: number | null;
    sector_category: string | null;
    sector_label: string | null;
    canslim_grade?: string | null;
    canslim_signal?: number | null;
    canslim_risk?: number | null;
    canslim_confidence?: number | null;
    canslim_hard_blocked?: boolean | null;
    entry_tier?: number | null;
  };
  reasons: string[];
  watch_conditions: string[];
  invalidation: string[];
  risk_flags: string[];
  missing_data?: string[];
  data_quality_flags?: string[];
  extras?: {
    canslim?: Record<string, HorizonObservation>;
    canslim_error?: string;
  };
}

interface ScreenerData {
  generated_at: string;
  universe_size: number;
  matched_count: number;
  summary: Record<string, number>;
  parameters: {
    scan_limit?: number;
    limit?: number;
  };
  data_warnings: string[];
  results: CandidateResult[];
}

interface ScreenerJob {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress_pct: number;
  processed: number;
  total: number;
  message: string;
  current_stock_id: string | null;
  current_stock_name: string | null;
  result: ScreenerData | null;
  error: string | null;
}

const GRADE_ORDER: CanslimGrade[] = ['S', 'A', 'B', 'C', 'D', 'NA'];
const GRADE_RANK: Record<CanslimGrade, number> = { S: 5, A: 4, B: 3, C: 2, D: 1, NA: 0 };
const GRADE_META: Record<CanslimGrade, { label: string; title: string; tone: string; active: string; bar: string }> = {
  S: {
    label: 'S',
    title: 'S 級',
    tone: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200',
    active: 'border-emerald-500 bg-emerald-100 shadow-sm dark:border-emerald-400 dark:bg-emerald-950/50',
    bar: 'bg-emerald-500',
  },
  A: {
    label: 'A',
    title: 'A 級',
    tone: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200',
    active: 'border-sky-500 bg-sky-100 shadow-sm dark:border-sky-400 dark:bg-sky-950/50',
    bar: 'bg-sky-500',
  },
  B: {
    label: 'B',
    title: 'B 級',
    tone: 'border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200',
    active: 'border-violet-500 bg-violet-100 shadow-sm dark:border-violet-400 dark:bg-violet-950/50',
    bar: 'bg-violet-500',
  },
  C: {
    label: 'C',
    title: 'C 級',
    tone: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200',
    active: 'border-amber-500 bg-amber-100 shadow-sm dark:border-amber-400 dark:bg-amber-950/50',
    bar: 'bg-amber-500',
  },
  D: {
    label: 'D',
    title: 'D 級',
    tone: 'border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300',
    active: 'border-zinc-500 bg-zinc-100 shadow-sm dark:border-zinc-500 dark:bg-zinc-800',
    bar: 'bg-zinc-500',
  },
  NA: {
    label: '-',
    title: '未分級',
    tone: 'border-zinc-200 bg-white text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400',
    active: 'border-zinc-400 bg-zinc-50 shadow-sm dark:border-zinc-600 dark:bg-zinc-900',
    bar: 'bg-zinc-300',
  },
};

const PILLAR_LABELS: Record<keyof ScreeningResult['pillars'], string> = {
  C: 'C 成長',
  A: 'A 年度品質',
  N: 'N 新題材',
  S: 'S 籌碼供需',
  L: 'L 領導股',
  I: 'I 法人',
  M: 'M 大盤',
};

const PILLAR_STATUS_LABELS: Record<PillarStatus, string> = {
  Pass: '通過',
  Weak: '偏弱',
  Fail: '未通過',
  AI_Review_Required: '需檢視',
  Neutral: '中性',
  Insufficient_Data: '資料不足',
};

const CATALYST_TYPE_LABELS: Record<string, string> = {
  new_product: '新產品',
  new_order: '新訂單',
  earnings: '法說/財報',
  m_and_a: '併購投資',
  capacity: '產能擴充',
  other: '其他',
};

const delay = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms));

function readPendingJobId(): string | null {
  if (typeof window === 'undefined') return null;
  try { return localStorage.getItem(PENDING_JOB_KEY); } catch { return null; }
}

function writePendingJobId(id: string | null) {
  try {
    if (id) localStorage.setItem(PENDING_JOB_KEY, id);
    else localStorage.removeItem(PENDING_JOB_KEY);
  } catch {}
}

function readSavedData(): ScreenerData | null {
  if (typeof window === 'undefined') return null;
  try {
    const saved = window.localStorage.getItem(SAVED_RESULT_KEY);
    return saved ? JSON.parse(saved) as ScreenerData : null;
  } catch {
    window.localStorage.removeItem(SAVED_RESULT_KEY);
    return null;
  }
}

function normalizeGrade(value: string | null | undefined): CanslimGrade {
  const grade = value?.trim().toUpperCase();
  if (grade === 'S' || grade === 'A' || grade === 'B' || grade === 'C' || grade === 'D') return grade;
  return 'NA';
}

function scoreText(value: number | null | undefined): string {
  return value == null ? '-' : String(Math.round(value));
}

function pctText(value: number | null | undefined): string {
  return value == null ? '-' : `${(value * 100).toFixed(1)}%`;
}

function compactMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-';
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 億`;
  if (value >= 10_000) return `${Math.round(value / 10_000).toLocaleString()} 萬`;
  return Math.round(value).toLocaleString();
}

function formatDateTime(isoStr: string): string {
  try {
    return new Date(isoStr).toLocaleString('zh-TW', { hour12: false });
  } catch {
    return isoStr;
  }
}

const STORAGE_FAVORITES = 'stockAssistant.favorites';
const ALWAYS_UNAVAILABLE_TOKENS = ['day_trade', 'chip_concentration', 'ex-tsmc', 'ex-TSMC', 'proprietary'];

function dataCompleteness(pillars: ScreeningResult['pillars']): number {
  return Object.values(pillars).filter((s) => s !== 'Insufficient_Data' && s !== 'AI_Review_Required').length;
}

function stalenessHint(asOf: string): string {
  const d = new Date(asOf);
  if (Number.isNaN(d.getTime())) return '';
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  return days > 5 ? ` (已 ${days} 天)` : '';
}

function partitionWarnings(warnings: string[]): { always: string[]; specific: string[] } {
  const always: string[] = [];
  const specific: string[] = [];
  for (const w of warnings) {
    const lower = w.toLowerCase();
    if (ALWAYS_UNAVAILABLE_TOKENS.some((t) => lower.includes(t.toLowerCase()))) always.push(w);
    else specific.push(w);
  }
  return { always, specific };
}

function pillarStatusTone(status: PillarStatus): string {
  switch (status) {
    case 'Pass':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200';
    case 'Weak':
      return 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200';
    case 'Fail':
      return 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200';
    case 'AI_Review_Required':
    case 'Insufficient_Data':
      return 'border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950/50 dark:text-zinc-300';
    default:
      return 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200';
  }
}

function regimeLabel(regime: ScreeningResult['market_regime']): string {
  const labels: Record<ScreeningResult['market_regime'], string> = {
    risk_on: 'Risk On',
    risk_off: 'Risk Off',
    severe: 'Severe',
    unknown: 'Unknown',
  };
  return labels[regime] ?? regime;
}

function swingCard(item: CandidateResult): HorizonObservation | null {
  return item.extras?.canslim?.swing_term ?? null;
}

function candidateHasCanslim(item: CandidateResult): boolean {
  return Boolean(
    item.metrics.canslim_grade ||
    item.metrics.canslim_signal != null ||
    item.metrics.canslim_risk != null ||
    item.metrics.canslim_confidence != null ||
    item.metrics.canslim_hard_blocked != null ||
    item.extras?.canslim
  );
}

function actionLabel(item: CandidateResult): string {
  if (item.extras?.canslim_error) return '資料待檢';
  if (item.metrics.canslim_hard_blocked) return '風險阻擋';
  const grade = normalizeGrade(item.metrics.canslim_grade);
  if (grade === 'S' || grade === 'A') return '高匹配觀察';
  if (grade === 'B') return '中匹配觀察';
  if (grade === 'C' || grade === 'D') return '低匹配追蹤';
  return '未分級';
}

function scoreWidth(value: number | null | undefined): string {
  return `${Math.min(100, Math.max(0, value ?? 0))}%`;
}

export default function ScreenerView() {
  const [data, setData] = useState<ScreenerData | null>(() => readSavedData());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<ScreenerJob | null>(null);
  const [progress, setProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [scanStartedAt, setScanStartedAt] = useState(() => Date.now());
  const [scanLimitInput, setScanLimitInput] = useState(String(DEFAULT_SCAN_LIMIT));
  const [aiTechOnly, setAiTechOnly] = useState(true);
  const [selectedGrades, setSelectedGrades] = useState<Set<CanslimGrade>>(() => new Set(['S', 'A', 'B']));
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [sortBy, setSortBy] = useState<'grade' | 'rs' | 'signal'>('grade');
  const [hideIncomplete, setHideIncomplete] = useState(true);
  const [watchlisted, setWatchlisted] = useState<Set<string>>(new Set());

  function addToWatchlist(code: string) {
    try {
      const raw = localStorage.getItem(STORAGE_FAVORITES);
      const list: { code: string; name: string }[] = raw ? JSON.parse(raw) : [];
      if (!list.some((f) => f.code === code)) {
        list.push({ code, name: code });
        localStorage.setItem(STORAGE_FAVORITES, JSON.stringify(list));
      }
      setWatchlisted((prev) => new Set(prev).add(code));
    } catch {
      /* ignore localStorage failures */
    }
  }
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [singleSymbol, setSingleSymbol] = useState('2330');
  const [singleScreening, setSingleScreening] = useState<ScreeningResult | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);
  const [singleError, setSingleError] = useState<string | null>(null);
  const [hasScanStarted, setHasScanStarted] = useState(() => Boolean(readSavedData()));
  const [request, setRequest] = useState({
    scanLimit: DEFAULT_SCAN_LIMIT,
    forceRefresh: false,
    aiTechOnly: true,
    nonce: 0,
  });
  const abortRef = useRef(false);

  useEffect(() => {
    if (!hasScanStarted) return;

    const apiBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');
    const params = new URLSearchParams({
      scan_limit: String(request.scanLimit),
      limit: '300',
      ai_tech_only: request.aiTechOnly ? 'true' : 'false',
      include_canslim: 'true',
      include_unfit: 'true',
    });
    if (request.forceRefresh) params.set('force_refresh', 'true');

    let canceled = false;

    async function parseError(res: Response) {
      try {
        const payload = await res.json();
        return payload?.detail || '無法取得 CANSLIM 篩選結果，請確認後端 API 已啟動。';
      } catch {
        return '無法取得 CANSLIM 篩選結果，請確認後端 API 已啟動。';
      }
    }

    async function startAndPollJob() {
      try {
        abortRef.current = false;
        let currentJob: ScreenerJob | null = null;

        if (request.nonce === 0) {
          const savedId = readPendingJobId();
          if (savedId) {
            try {
              const checkRes = await fetch(`${apiBase}/screeners/surge-candidates/jobs/${savedId}`, { cache: 'no-store' });
              if (checkRes.ok) {
                const saved: ScreenerJob = await checkRes.json();
                if (saved.status === 'completed' && saved.result) {
                  writePendingJobId(null);
                  setData(saved.result);
                  try { localStorage.setItem(SAVED_RESULT_KEY, JSON.stringify(saved.result)); } catch {}
                  setLoading(false);
                  setProgress(100);
                  return;
                }
                if (saved.status === 'running' || saved.status === 'queued') {
                  currentJob = saved;
                  setJob(currentJob);
                  setProgress(currentJob.progress_pct ?? 0);
                  setLoading(true);
                  setScanStartedAt(Date.now());
                } else {
                  writePendingJobId(null);
                }
              } else {
                writePendingJobId(null);
              }
            } catch {
              writePendingJobId(null);
            }
          }
        } else {
          writePendingJobId(null);
        }

        if (!currentJob) {
          const startRes = await fetch(`${apiBase}/screeners/surge-candidates/jobs?${params.toString()}`, {
            method: 'POST',
            cache: 'no-store',
          });
          if (startRes.status === 429) {
            throw new Error('重新掃描太頻繁，請稍等幾分鐘後再試。');
          }
          if (!startRes.ok) {
            throw new Error(await parseError(startRes));
          }
          currentJob = await startRes.json();
          writePendingJobId(currentJob!.job_id);
        }

        if (canceled) return;
        if (!currentJob) throw new Error('CANSLIM 掃描工作沒有正確建立。');
        let activeJob = currentJob;
        setJob(activeJob);
        setProgress(activeJob.progress_pct ?? 0);

        while (!canceled && !abortRef.current && activeJob.status !== 'completed' && activeJob.status !== 'failed' && activeJob.status !== 'cancelled') {
          await delay(1000);
          const pollRes = await fetch(`${apiBase}/screeners/surge-candidates/jobs/${activeJob.job_id}`, { cache: 'no-store' });
          if (!pollRes.ok) {
            throw new Error(await parseError(pollRes));
          }
          activeJob = await pollRes.json();
          if (canceled) return;
          setJob(activeJob);
          setProgress(activeJob.progress_pct ?? 0);
        }

        if (canceled) return;
        if (abortRef.current || activeJob.status === 'cancelled') {
          writePendingJobId(null);
          setLoading(false);
          return;
        }
        if (activeJob.status === 'completed' && activeJob.result) {
          writePendingJobId(null);
          setData(activeJob.result);
          try { localStorage.setItem(SAVED_RESULT_KEY, JSON.stringify(activeJob.result)); } catch {}
          setLoading(false);
          setProgress(100);
          return;
        }

        writePendingJobId(null);
        throw new Error(activeJob.error || 'CANSLIM 掃描失敗，請稍後再試。');
      } catch (exc) {
        if (canceled || abortRef.current) return;
        writePendingJobId(null);
        setError(exc instanceof Error ? exc.message : 'CANSLIM 掃描失敗，請稍後再試。');
        setLoading(false);
      }
    }

    startAndPollJob();
    return () => {
      canceled = true;
    };
  }, [request, hasScanStarted]);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - scanStartedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [loading, scanStartedAt]);

  const canslimRows = useMemo(() => {
    const rs = (item: CandidateResult) => item.metrics.relative_strength_60d ?? item.metrics.relative_strength_20d ?? -Infinity;
    const byGrade = (a: CandidateResult, b: CandidateResult) => {
      const gradeDelta = GRADE_RANK[normalizeGrade(b.metrics.canslim_grade)] - GRADE_RANK[normalizeGrade(a.metrics.canslim_grade)];
      if (gradeDelta !== 0) return gradeDelta;
      const signalDelta = (b.metrics.canslim_signal ?? -1) - (a.metrics.canslim_signal ?? -1);
      if (signalDelta !== 0) return signalDelta;
      return (a.metrics.canslim_risk ?? 999) - (b.metrics.canslim_risk ?? 999);
    };
    return (data?.results ?? [])
      .filter(candidateHasCanslim)
      .sort((a, b) => {
        if (sortBy === 'rs') {
          const d = rs(b) - rs(a);
          if (d !== 0) return d;
          return byGrade(a, b);
        }
        if (sortBy === 'signal') {
          const d = (b.metrics.canslim_signal ?? -1) - (a.metrics.canslim_signal ?? -1);
          if (d !== 0) return d;
          return byGrade(a, b);
        }
        return byGrade(a, b);
      });
  }, [data, sortBy]);

  const gradeCounts = useMemo(() => {
    const counts = GRADE_ORDER.reduce<Record<CanslimGrade, number>>((acc, grade) => {
      acc[grade] = 0;
      return acc;
    }, {} as Record<CanslimGrade, number>);
    for (const row of canslimRows) counts[normalizeGrade(row.metrics.canslim_grade)] += 1;
    return counts;
  }, [canslimRows]);

  const filteredRows = useMemo(() => {
    return canslimRows.filter(row => {
      if (hideIncomplete && (row.extras?.canslim_error || normalizeGrade(row.metrics.canslim_grade) === 'NA')) return false;
      if (!selectedGrades.has(normalizeGrade(row.metrics.canslim_grade))) return false;
      if (riskFilter === 'blocked') return Boolean(row.metrics.canslim_hard_blocked);
      if (riskFilter === 'clear') return !row.metrics.canslim_hard_blocked;
      return true;
    });
  }, [canslimRows, selectedGrades, riskFilter, hideIncomplete]);

  const blockedCount = canslimRows.filter(row => row.metrics.canslim_hard_blocked).length;
  const progressPct = Math.min(100, Math.max(0, Math.round(progress)));
  const elapsedLabel = elapsedSeconds < 60 ? `${elapsedSeconds} 秒` : `${Math.floor(elapsedSeconds / 60)} 分 ${elapsedSeconds % 60} 秒`;
  const currentStock = job?.current_stock_id ? `${job.current_stock_id} ${job.current_stock_name ?? ''}`.trim() : null;

  function parseScanLimit() {
    const parsed = Number.parseInt(scanLimitInput, 10);
    if (!Number.isFinite(parsed)) return DEFAULT_SCAN_LIMIT;
    return Math.min(MAX_SCAN_LIMIT, Math.max(1, parsed));
  }

  function startScan(forceRefresh: boolean) {
    const scanLimit = parseScanLimit();
    setScanLimitInput(String(scanLimit));
    setHasScanStarted(true);
    setLoading(true);
    setError(null);
    setJob(null);
    setElapsedSeconds(0);
    setScanStartedAt(Date.now());
    setProgress(0);
    setRequest({
      scanLimit,
      forceRefresh,
      aiTechOnly,
      nonce: Date.now(),
    });
  }

  async function pauseScan() {
    abortRef.current = true;
    writePendingJobId(null);
    setLoading(false);
    setError(null);
    const jobId = job?.job_id;
    if (!jobId) return;
    const apiBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');
    try {
      await fetch(`${apiBase}/screeners/surge-candidates/jobs/${jobId}/cancel`, { method: 'POST', cache: 'no-store' });
    } catch {}
  }

  function toggleExpanded(id: string) {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function screenSingleSymbol(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const symbol = singleSymbol.trim();
    if (!/^\d{4,6}$/.test(symbol)) {
      setSingleError('請輸入 4 到 6 位數台股代號。');
      return;
    }
    const apiBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');
    setSingleLoading(true);
    setSingleError(null);
    try {
      const res = await fetch(`${apiBase}/tw/screen?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store' });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.detail || '無法取得單檔 CANSLIM 條件。');
      }
      setSingleScreening(await res.json());
    } catch (exc) {
      setSingleError(exc instanceof Error ? exc.message : '無法取得單檔 CANSLIM 條件。');
    } finally {
      setSingleLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      {singleScreening && <RegimeBanner regime={singleScreening.market_regime} />}
      <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">CANSLIM Screener</p>
            <h2 className="mt-1 text-2xl font-bold text-zinc-950 dark:text-zinc-50">CANSLIM 條件分類</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
              以 CANSLIM 觀察卡為主，顯示分級、signal、risk、confidence、風險阻擋與資料缺口，協助你篩選符合條件的股票後自行判斷。
            </p>
            {data?.generated_at && (
              <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">更新時間：{formatDateTime(data.generated_at)}</p>
            )}
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50 sm:flex-row sm:items-center xl:flex-wrap xl:justify-end">
            <label className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
              掃描檔數
              <input
                type="number"
                min={1}
                max={MAX_SCAN_LIMIT}
                value={scanLimitInput}
                onChange={(event) => setScanLimitInput(event.target.value)}
                className="ml-2 w-28 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
              />
            </label>
            <label className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-200">
              <input
                type="checkbox"
                checked={aiTechOnly}
                onChange={(event) => setAiTechOnly(event.target.checked)}
                className="h-4 w-4 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-400"
              />
              AI 科技股池
            </label>
            <button
              type="button"
              disabled={loading}
              onClick={() => startScan(false)}
              className="rounded-lg bg-zinc-950 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white"
            >
              開始掃描
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => startScan(true)}
              className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-semibold text-zinc-700 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900"
            >
              重新掃描
            </button>
            <button
              type="button"
              disabled={!loading}
              onClick={pauseScan}
              className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-700 dark:text-amber-300"
            >
              暫停
            </button>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Single Symbol</p>
            <h3 className="mt-1 text-xl font-bold text-zinc-950 dark:text-zinc-50">單檔 CANSLIM 觀察</h3>
            <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
              直接讀取本機 OHLCV / PIT 基本面 / 大盤 regime / 新聞來源，整理成七大支柱狀態。
            </p>
          </div>
          <form onSubmit={screenSingleSymbol} className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              value={singleSymbol}
              onChange={(event) => setSingleSymbol(event.target.value)}
              inputMode="numeric"
              placeholder="2330"
              className="h-10 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50 sm:w-36"
            />
            <button
              type="submit"
              disabled={singleLoading}
              className="h-10 rounded-lg bg-zinc-950 px-4 text-sm font-semibold text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white"
            >
              {singleLoading ? '讀取中' : '觀察單檔'}
            </button>
          </form>
        </div>

        {singleError && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            {singleError}
          </div>
        )}

        {singleScreening && (
          <div className="mt-5 grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)]">
            <div className={`rounded-2xl border p-5 ${GRADE_META[normalizeGrade(singleScreening.candidate_grade)].tone}`}>
              <div className="text-xs font-semibold uppercase tracking-wide opacity-70">Grade</div>
              <div className="mt-2 text-6xl font-black leading-none">{singleScreening.candidate_grade}</div>
              <div className="mt-3 flex items-center gap-2">
                <span className="text-sm font-semibold">{singleScreening.canslim_match} 支柱匹配</span>
                <span className="rounded-md border border-current/30 px-1.5 py-0.5 text-[11px] font-semibold opacity-80">
                  資料完整度 {dataCompleteness(singleScreening.pillars)}/7
                </span>
              </div>
              <div className="mt-4 space-y-2 text-sm">
                <div className="flex justify-between gap-3">
                  <span className="opacity-70">代號</span>
                  <span className="font-semibold">{singleScreening.stock_id}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="opacity-70">資料截至</span>
                  <span className="font-semibold">{singleScreening.as_of_date}{stalenessHint(singleScreening.as_of_date)}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="opacity-70">大盤</span>
                  <span className="font-semibold">{regimeLabel(singleScreening.market_regime)}</span>
                </div>
                {singleScreening.scores && (
                  <div className="flex justify-between gap-2 text-xs">
                    <span className="opacity-70">Signal / Risk / Conf</span>
                    <span className="font-semibold">
                      {singleScreening.scores.signal ?? '-'} / {singleScreening.scores.risk ?? '-'} / {singleScreening.scores.confidence ?? '-'}
                    </span>
                  </div>
                )}
                {singleScreening.is_mock && (
                  <div className="rounded-lg border border-amber-300 bg-amber-100/70 px-2 py-1 text-xs font-semibold text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
                    部分資料為 fallback / mock
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => addToWatchlist(singleScreening.stock_id)}
                  disabled={watchlisted.has(singleScreening.stock_id)}
                  className="mt-1 w-full rounded-lg border border-current/40 px-2 py-1.5 text-xs font-semibold opacity-90 hover:opacity-100 disabled:opacity-60"
                >
                  {watchlisted.has(singleScreening.stock_id) ? '✓ 已加入觀察清單' : '＋ 加入觀察清單'}
                </button>
              </div>
            </div>

            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-7">
                {(Object.keys(PILLAR_LABELS) as (keyof ScreeningResult['pillars'])[]).map((pillar) => {
                  const status = singleScreening.pillars[pillar];
                  const metric = singleScreening.pillar_metrics?.[pillar];
                  return (
                    <div key={pillar} className={`rounded-xl border p-3 ${pillarStatusTone(status)}`}>
                      <div className="text-xs font-semibold opacity-70">{PILLAR_LABELS[pillar]}</div>
                      <div className="mt-1 text-sm font-bold">{PILLAR_STATUS_LABELS[status]}</div>
                      {metric && <div className="mt-1 text-[11px] font-medium leading-tight opacity-80">{metric}</div>}
                    </div>
                  );
                })}
              </div>

              <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950/50">
                <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Interpretation</div>
                <p className="mt-2 text-sm leading-6 text-zinc-700 dark:text-zinc-300">{singleScreening.interpretation}</p>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <WarningsPanel warnings={singleScreening.data_warnings} />
                <DetailPanel title="需人工檢視" items={singleScreening.needs_manual_review} empty="無需人工檢視項目" />
              </div>

              {singleScreening.evidence.length > 0 && (
                <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950/50">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    Evidence · 證據（{singleScreening.evidence.length}）
                  </div>
                  <div className="space-y-4">
                    {(() => {
                      const groups = new Map<string, ScreeningEvidence[]>();
                      for (const item of singleScreening.evidence) {
                        const key = item.pillar || 'General';
                        if (!groups.has(key)) groups.set(key, []);
                        groups.get(key)!.push(item);
                      }
                      return Array.from(groups.entries()).map(([pillar, items]) => (
                        <div key={pillar}>
                          <div className="mb-2 text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                            {pillar}（{items.length}）
                          </div>
                          <div className="grid gap-2 md:grid-cols-2">
                            {items.map((item, index) => (
                              <div key={`${pillar}-${index}`} className="rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
                                <div className="mb-1 flex items-center justify-between gap-3 text-xs text-zinc-500 dark:text-zinc-400">
                                  <span className="flex items-center gap-1.5">
                                    <span className="font-semibold">{item.pillar}</span>
                                    {item.catalyst_type && (
                                      <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">
                                        {CATALYST_TYPE_LABELS[item.catalyst_type] ?? item.catalyst_type}
                                      </span>
                                    )}
                                  </span>
                                  <span>{item.published_date ?? '未標日期'}</span>
                                </div>
                                <p className="leading-5 text-zinc-700 dark:text-zinc-300">{item.summary}</p>
                                {item.source_url && (
                                  <a
                                    href={item.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="mt-2 inline-flex text-xs font-semibold text-sky-700 hover:text-sky-900 dark:text-sky-300 dark:hover:text-sky-200"
                                  >
                                    來源連結
                                  </a>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      ));
                    })()}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {loading && (
        <section className="rounded-2xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mb-2 flex items-center justify-between gap-3 text-zinc-700 dark:text-zinc-200">
            <span>{job?.message || `正在掃描 ${request.scanLimit} 檔`}</span>
            <span>{progressPct}% · {job?.total ? `${job.processed}/${job.total}` : '準備中'}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
            <div className="h-full rounded-full bg-zinc-950 transition-all duration-300 dark:bg-zinc-100" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="mt-2 flex flex-col gap-1 text-xs text-zinc-500 dark:text-zinc-400 sm:flex-row sm:items-center sm:justify-between">
            <span>{currentStock ? `目前：${currentStock}` : '等待後端回報逐檔進度'}</span>
            <span>已用時：{elapsedLabel}</span>
          </div>
        </section>
      )}

      {error && (
        <section className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </section>
      )}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">CANSLIM 筆數</div>
          <div className="mt-1 text-2xl font-bold text-zinc-950 dark:text-zinc-50">{canslimRows.length.toLocaleString()}</div>
        </div>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">掃描母體</div>
          <div className="mt-1 text-2xl font-bold text-zinc-950 dark:text-zinc-50">{(data?.universe_size ?? 0).toLocaleString()}</div>
        </div>
        <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">風險阻擋</div>
          <div className="mt-1 text-2xl font-bold text-rose-700 dark:text-rose-300">{blockedCount.toLocaleString()}</div>
        </div>
        {(['S', 'A', 'B'] as CanslimGrade[]).map(grade => (
          <div key={grade} className={`rounded-2xl border p-4 ${GRADE_META[grade].tone}`}>
            <div className="text-xs opacity-75">{GRADE_META[grade].title}</div>
            <div className="mt-1 text-2xl font-bold">{gradeCounts[grade].toLocaleString()}</div>
          </div>
        ))}
      </section>

      <section className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-base font-semibold text-zinc-950 dark:text-zinc-50">分級篩選</h3>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">目前顯示 {filteredRows.length.toLocaleString()} / {canslimRows.length.toLocaleString()} 筆</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-300">
              排序
              <select
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value as 'grade' | 'rs' | 'signal')}
                className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-xs text-zinc-700 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200"
              >
                <option value="grade">分級</option>
                <option value="rs">強勢 RS</option>
                <option value="signal">Signal</option>
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-300">
              <input
                type="checkbox"
                checked={hideIncomplete}
                onChange={(event) => setHideIncomplete(event.target.checked)}
                className="h-4 w-4 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-400"
              />
              只看完整可篩
            </label>
            <button
              type="button"
              onClick={() => setSelectedGrades(new Set(GRADE_ORDER))}
              className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-semibold text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              全部分級
            </button>
            <button
              type="button"
              onClick={() => setSelectedGrades(new Set(['S', 'A', 'B']))}
              className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-semibold text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              S/A/B
            </button>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-6">
          {GRADE_ORDER.map(grade => {
            const meta = GRADE_META[grade];
            const selected = selectedGrades.has(grade);
            return (
              <button
                key={grade}
                type="button"
                onClick={() => setSelectedGrades(prev => {
                  const next = new Set(prev);
                  if (next.has(grade)) next.delete(grade);
                  else next.add(grade);
                  return next;
                })}
                className={`rounded-2xl border p-3 text-left transition hover:-translate-y-0.5 hover:shadow-sm ${
                  selected ? meta.active : 'border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{meta.title}</span>
                  <span className={`h-2 w-8 rounded-full ${meta.bar}`} />
                </div>
                <div className="mt-2 text-2xl font-bold text-zinc-950 dark:text-zinc-50">{gradeCounts[grade].toLocaleString()}</div>
              </button>
            );
          })}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {([
            ['all', '全部風險狀態'],
            ['clear', '未被阻擋'],
            ['blocked', '風險阻擋'],
          ] as [RiskFilter, string][]).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setRiskFilter(key)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${
                riskFilter === key
                  ? 'border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-950'
                  : 'border-zinc-300 text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      {data?.data_warnings?.length ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          資料提醒：{data.data_warnings.join('、')}
        </section>
      ) : null}

      {!hasScanStarted && !loading && (
        <section className="rounded-2xl border border-zinc-200 bg-zinc-50 p-10 text-center dark:border-zinc-800 dark:bg-zinc-900/50">
          <p className="text-zinc-500 dark:text-zinc-400">尚未執行 CANSLIM 掃描。</p>
        </section>
      )}

      {hasScanStarted && filteredRows.length === 0 && !loading && (
        <section className="rounded-2xl border border-zinc-200 bg-zinc-50 p-10 text-center dark:border-zinc-800 dark:bg-zinc-900/50">
          <p className="text-zinc-500 dark:text-zinc-400">目前篩選條件下沒有 CANSLIM 項目。</p>
        </section>
      )}

      <section className="grid gap-4">
        {filteredRows.map((item) => {
          const grade = normalizeGrade(item.metrics.canslim_grade);
          const meta = GRADE_META[grade];
          const card = swingCard(item);
          const cardId = item.stock_id;
          const expanded = expandedIds.has(cardId);
          const warnings = [
            ...(card?.data_warnings ?? []),
            ...(item.missing_data ?? []),
            ...(item.data_quality_flags ?? []),
          ];

          return (
            <article key={cardId} className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="grid gap-0 lg:grid-cols-[160px_minmax(0,1fr)]">
                <div className={`flex flex-col justify-between border-b p-5 lg:border-b-0 lg:border-r ${meta.tone}`}>
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide opacity-70">Grade</div>
                    <div className="mt-2 text-5xl font-black leading-none">{meta.label}</div>
                    <div className="mt-2 text-sm font-semibold">{actionLabel(item)}</div>
                  </div>
                  <div className="mt-4 text-xs opacity-75">{item.metrics.canslim_hard_blocked ? 'Hard block' : 'Open status'}</div>
                </div>

                <div className="p-5">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-xl font-bold text-zinc-950 dark:text-zinc-50">{item.stock_id} {item.stock_name}</h3>
                        {item.metrics.sector_label && (
                          <span className="rounded-lg border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs font-semibold text-cyan-700 dark:border-cyan-900/60 dark:bg-cyan-950/30 dark:text-cyan-300">
                            {item.metrics.sector_label}
                          </span>
                        )}
                        {item.extras?.canslim_error && (
                          <span className="rounded-lg border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-semibold text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
                            CANSLIM 資料錯誤
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                        {card?.status ?? 'unknown'} · {card?.risk_level ?? 'risk unknown'} risk · {card?.confidence_level ?? 'confidence unknown'} confidence
                      </p>
                    </div>
                    <div className="grid min-w-[280px] grid-cols-3 gap-2">
                      {[
                        ['Signal', item.metrics.canslim_signal],
                        ['Risk', item.metrics.canslim_risk],
                        ['Confidence', item.metrics.canslim_confidence],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
                          <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
                          <div className="mt-1 text-lg font-bold text-zinc-950 dark:text-zinc-50">{scoreText(value as number | null | undefined)}</div>
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                            <div className="h-full rounded-full bg-zinc-950 dark:bg-zinc-100" style={{ width: scoreWidth(value as number | null | undefined) }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-5">
                    <Metric label="20 日" value={pctText(item.metrics.return_20d)} />
                    <Metric label="60 日" value={pctText(item.metrics.return_60d)} />
                    <Metric label="相對強勢 20D" value={pctText(item.metrics.relative_strength_20d)} />
                    <Metric label="相對強勢 60D" value={pctText(item.metrics.relative_strength_60d)} />
                    <Metric label="20 日均額" value={compactMoney(item.metrics.avg_turnover_20)} />
                  </div>

                  <div className="mt-4">
                    <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Evidence</div>
                    <ul className="mt-2 grid gap-2 text-sm text-zinc-700 dark:text-zinc-300 md:grid-cols-2">
                      {(card?.evidence_based_reasons?.length ? card.evidence_based_reasons : item.reasons).slice(0, 4).map((reason, index) => (
                        <li key={`${item.stock_id}-reason-${index}`} className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
                          {reason}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <button
                    type="button"
                    onClick={() => toggleExpanded(cardId)}
                    className="mt-4 rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-semibold text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  >
                    {expanded ? '收合細節' : '查看細節'}
                  </button>

                  {expanded && (
                    <div className="mt-4 grid gap-4 border-t border-zinc-200 pt-4 dark:border-zinc-800 lg:grid-cols-3">
                      <DetailPanel title="觸發規則" items={card?.triggered_rule_ids ?? []} empty="無規則清單" />
                      <DetailPanel title="觀察條件" items={card?.key_observation_conditions ?? item.watch_conditions} empty="無觀察條件" />
                      <DetailPanel title="失效訊號" items={card?.invalidation_signals ?? item.invalidation} empty="無失效訊號" />
                      <DetailPanel title="風險提示" items={item.risk_flags} empty="無風險提示" />
                      <DetailPanel title="資料缺口" items={warnings} empty="無資料缺口" />
                    </div>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}

function RegimeBanner({ regime }: { regime: ScreeningResult['market_regime'] }) {
  const meta: Record<ScreeningResult['market_regime'], { label: string; cls: string }> = {
    risk_on: {
      label: '市場 Risk On — 動能環境有利，符合條件的強勢股較值得追蹤',
      cls: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200',
    },
    risk_off: {
      label: '市場 Risk Off — 大盤轉弱，篩選結果僅供觀察，進場宜謹慎',
      cls: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200',
    },
    severe: {
      label: '市場 Severe — 大盤弱勢，建議以觀察為主、降低曝險',
      cls: 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200',
    },
    unknown: {
      label: '市場狀態未知 — 指數資料不足，無法判斷大盤環境',
      cls: 'border-zinc-300 bg-zinc-50 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300',
    },
  };
  const m = meta[regime] ?? meta.unknown;
  return <div className={`rounded-2xl border px-4 py-3 text-sm font-semibold ${m.cls}`}>{m.label}</div>;
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
  const { always, specific } = partitionWarnings(warnings.filter(Boolean));
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
      <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">資料提醒</h4>
      {specific.length ? (
        <ul className="mt-2 space-y-1.5 text-sm text-zinc-600 dark:text-zinc-400">
          {specific.slice(0, 8).map((w, i) => (
            <li key={`spec-${i}`}>{w}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-zinc-400 dark:text-zinc-500">無此檔特有的資料缺口</p>
      )}
      {always.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-zinc-500 dark:text-zinc-400">
            常駐限制（免費版無此資料）· {always.length}
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-zinc-400 dark:text-zinc-500">
            {always.map((w, i) => (
              <li key={`always-${i}`}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
      <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="mt-1 font-semibold text-zinc-950 dark:text-zinc-50">{value}</div>
    </div>
  );
}

function DetailPanel({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  const visibleItems = items.filter(Boolean);
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
      <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h4>
      {visibleItems.length ? (
        <ul className="mt-2 space-y-1.5 text-sm text-zinc-600 dark:text-zinc-400">
          {visibleItems.slice(0, 8).map((item, index) => (
            <li key={`${title}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-zinc-400 dark:text-zinc-500">{empty}</p>
      )}
    </div>
  );
}
