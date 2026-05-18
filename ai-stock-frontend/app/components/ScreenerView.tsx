'use client';

import { useState, useEffect, useRef } from 'react';
import PriceHistoryChart from './PriceHistoryChart';

const DEFAULT_SCAN_LIMIT = 1000;
const MAX_SCAN_LIMIT = 10000;

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
    range_90d: number;
    high_90d: number;
    low_90d: number;
    avg_volume_20_lots: number;
    relative_strength_20d: number | null;
    sector_category: string | null;
    sector_label: string | null;
  };
  reasons: string[];
  watch_conditions: string[];
  invalidation: string[];
  risk_flags: string[];
}

interface ScreenerData {
  strategy: string;
  generated_at: string;
  disclaimer: string;
  universe_size: number;
  matched_count: number;
  summary: Record<string, number>;
  parameters: {
    min_return_60d?: number;
    max_return_60d?: number;
    max_base_return?: number;
    min_return_20d?: number;
    min_avg_volume_lots?: number;
    min_avg_turnover?: number;
    scan_limit?: number;
    limit?: number;
  };
  data_warnings: string[];
  results: CandidateResult[];
  funnel_report?: FunnelReport | null;
}

interface FunnelExample {
  stock_id: string;
  stock_name: string;
  key_metrics: Record<string, unknown>;
  threshold: Record<string, unknown> | string | number;
  distance_to_pass: number;
}

interface FunnelConditionReport {
  condition: string;
  pass_count: number;
  fail_count: number;
  pass_rate: number;
  top_10_closest_failed_examples: FunnelExample[];
}

interface FunnelReport {
  stage_counts: Record<string, number>;
  condition_reports: Record<string, FunnelConditionReport>;
  ema_spread_distribution?: Record<string, number>;
  ema_slope_distribution?: Record<string, Record<string, number | string>>;
  ema_near_convergence_count?: number;
  ema_micro_upturn_count?: number;
  ema_full_bullish_alignment_count?: number;
  notes: string[];
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

const delay = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms));
const formatPct = (value: number | undefined, fallback: number) => `${((value ?? fallback) * 100).toFixed(0)}%`;
const formatMoney = (value: number | undefined, fallback: number) => `${Math.round((value ?? fallback) / 10_000).toLocaleString()} 萬`;
const PENDING_JOB_KEY = 'surge_screener_pending_job_id';
const readPendingJobId = (): string | null => {
  if (typeof window === 'undefined') return null;
  try { return localStorage.getItem(PENDING_JOB_KEY) ?? null; } catch { return null; }
};
const writePendingJobId = (id: string | null) => {
  try {
    if (id) localStorage.setItem(PENDING_JOB_KEY, id);
    else localStorage.removeItem(PENDING_JOB_KEY);
  } catch {}
};

const readSavedScreenerData = (): ScreenerData | null => {
  if (typeof window === 'undefined') return null;
  try {
    const saved = window.localStorage.getItem('surge_screener_results');
    return saved ? JSON.parse(saved) as ScreenerData : null;
  } catch {
    window.localStorage.removeItem('surge_screener_results');
    return null;
  }
};

export default function ScreenerView() {
  const [data, setData] = useState<ScreenerData | null>(() => readSavedScreenerData());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [job, setJob] = useState<ScreenerJob | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [scanStartedAt, setScanStartedAt] = useState(() => Date.now());
  const [scanLimitInput, setScanLimitInput] = useState(String(DEFAULT_SCAN_LIMIT));
  const [debugMode, setDebugMode] = useState(false);
  const [hasScanStarted, setHasScanStarted] = useState(() => Boolean(readSavedScreenerData()));
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [chartOpenIds, setChartOpenIds] = useState<Set<string>>(new Set());
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(() => new Set(['起漲前觀察', '初動候選']));
  const [aiTechOnly, setAiTechOnly] = useState(true);
  const scanAbortRef = useRef(false);
  const [request, setRequest] = useState({
    scanLimit: DEFAULT_SCAN_LIMIT,
    forceRefresh: false,
    debug: false,
    aiTechOnly: true,
    nonce: 0,
  });

  useEffect(() => {
    if (!hasScanStarted) return;
    const apiBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');
    const params = new URLSearchParams({
      scan_limit: String(request.scanLimit),
      limit: '100',
      ai_tech_only: request.aiTechOnly ? 'true' : 'false',
    });
    if (request.forceRefresh) params.set('force_refresh', 'true');
    if (request.debug) params.set('debug', 'true');

    let canceled = false;
    async function parseError(res: Response) {
      try {
        const payload = await res.json();
        return payload?.detail || '無法取得篩選結果，請確認後端 API 已啟動並可連線。';
      } catch {
        return '無法取得篩選結果，請確認後端 API 已啟動並可連線。';
      }
    }

    async function startAndPollJob() {
      try {
        scanAbortRef.current = false;
        let currentJob: ScreenerJob | null = null;

        // On initial mount (nonce === 0), try to reconnect to a job that was running when
        // the user navigated away. This avoids restarting a long scan from scratch.
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
                  try { localStorage.setItem('surge_screener_results', JSON.stringify(saved.result)); } catch {}
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
          // Explicit user-triggered rescan — discard any stale saved job.
          writePendingJobId(null);
        }

        if (!currentJob) {
          const startRes = await fetch(`${apiBase}/screeners/surge-candidates/jobs?${params.toString()}`, {
            method: 'POST',
            cache: 'no-store',
          });
          if (startRes.status === 429) {
            throw new Error('重新掃描太頻繁，請稍等 5 分鐘或調整掃描檔數後再試。');
          }
          if (!startRes.ok) {
            throw new Error(await parseError(startRes));
          }
          currentJob = await startRes.json();
          writePendingJobId(currentJob!.job_id);
        }

        if (canceled) return;
        if (scanAbortRef.current) {
          try {
            await fetch(`${apiBase}/screeners/surge-candidates/jobs/${currentJob!.job_id}/cancel`, {
              method: 'POST',
              cache: 'no-store',
            });
          } catch {
            // The UI is already paused; the explicit cancel is best-effort in this narrow timing window.
          }
          writePendingJobId(null);
          return;
        }
        setJob(currentJob!);
        setProgress(currentJob!.progress_pct ?? 0);

        while (!canceled && !scanAbortRef.current && currentJob!.status !== 'completed' && currentJob!.status !== 'failed' && currentJob!.status !== 'cancelled') {
          await delay(1000);
          if (canceled) return;
          const pollRes = await fetch(`${apiBase}/screeners/surge-candidates/jobs/${currentJob!.job_id}`, {
            cache: 'no-store',
          });
          if (!pollRes.ok) {
            throw new Error(await parseError(pollRes));
          }
          currentJob = await pollRes.json();
          if (canceled) return;
          setJob(currentJob!);
          setProgress(currentJob!.progress_pct ?? 0);
        }

        if (canceled) return;
        if (scanAbortRef.current || currentJob!.status === 'cancelled') {
          writePendingJobId(null);
          setLoading(false);
          return;
        }
        if (currentJob!.status === 'completed' && currentJob!.result) {
          writePendingJobId(null);
          setData(currentJob!.result);
          try { localStorage.setItem('surge_screener_results', JSON.stringify(currentJob!.result)); } catch { /* quota exceeded — skip */ }
          setLoading(false);
          setProgress(100);
          return;
        }
        writePendingJobId(null);
        throw new Error(currentJob!.error || '掃描失敗，請稍後再試。');
      } catch (e) {
        if (canceled || scanAbortRef.current) return;
        writePendingJobId(null);
        setError(e instanceof Error ? e.message : '掃描失敗，請稍後再試。');
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
      debug: debugMode,
      aiTechOnly,
      nonce: Date.now(),
    });
  }

  async function pauseScan() {
    scanAbortRef.current = true;
    writePendingJobId(null);
    setLoading(false);
    setError(null);
    setJob((current) => current ? { ...current, status: 'cancelled', message: '掃描已暫停，可調整檔數後重新開始' } : current);
    const jobId = job?.job_id;
    if (!jobId) return;
    const apiBase = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');
    try {
      await fetch(`${apiBase}/screeners/surge-candidates/jobs/${jobId}/cancel`, {
        method: 'POST',
        cache: 'no-store',
      });
    } catch {
      // Frontend pause still unlocks controls even if the cancel request cannot reach the backend.
    }
  }

  function toggleExpanded(id: string) {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleChart(id: string) {
    setChartOpenIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function getScoreTier(score: number): { label: string; colorClass: string } {
    if (score >= 80) return { label: '高優先觀察', colorClass: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300' };
    if (score >= 70) return { label: '值得觀察', colorClass: 'bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-300' };
    if (score >= 60) return { label: '初步觀察', colorClass: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300' };
    return { label: '僅供參考', colorClass: 'bg-zinc-100 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-500' };
  }

  function formatDateTime(isoStr: string): string {
    try {
      const d = new Date(isoStr);
      const pad = (n: number) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    } catch {
      return isoStr;
    }
  }

  const progressPct = Math.min(100, Math.max(0, Math.round(progress)));
  const elapsedLabel = elapsedSeconds < 60
    ? `${elapsedSeconds} 秒`
    : `${Math.floor(elapsedSeconds / 60)} 分 ${elapsedSeconds % 60} 秒`;
  const progressCount = job?.total ? `${job.processed}/${job.total} 檔` : '準備中';
  const currentStock = job?.current_stock_id
    ? `${job.current_stock_id} ${job.current_stock_name ?? ''}`.trim()
    : null;
  const effectiveParams = data?.parameters;
  const stageLabels: Record<string, string> = {
    universe_size: '股票清單',
    ohlcv_sufficient_count: 'K 線足夠',
    liquidity_pass_count: '流動性通過',
    return_60d_range_pass_count: '60 日漲幅',
    return_90d_range_pass_count: '近三月漲幅(寬)',
    return_90d_ideal_range_pass_count: '近三月理想區間',
    volume_not_dried_up_pass_count: '基本量能仍在',
    return_20d_not_surged_pass_count: '近月未噴發',
    close_not_far_from_ema20_pass_count: '均線距離未拉開',
    ema_not_spread_out_pass_count: 'EMA 未分叉',
    return_60_to_20_pass_count: '前期盤整',
    return_20d_pass_count: '20 日漲幅',
    return_5d_not_overheat_count: '5 日未過熱',
    base_range_pass_count: '整理振幅',
    volume_contraction_pass_count: '縮量整理',
    volume_recovery_pass_count: '量能回溫',
    ema_spread_pass_count: '均線糾結',
    ema_structure_pass_count: '均線結構',
    relative_strength_20d_pass_count: '20 日相對強勢',
    relative_strength_60d_pass_count: '60 日相對強勢',
    risk_filter_pass_count: '風險過濾',
    final_matched_count: '最後符合',
    ema_near_convergence_count: 'EMA 接近糾結',
    ema_micro_upturn_count: 'EMA 微上彎',
    ema_full_bullish_alignment_count: '完整多頭排列',
  };
  const conditionLabels: Record<string, string> = {
    ohlcv_sufficient: 'K 線資料足夠',
    liquidity: '流動性',
    return_60d_range: '60 日漲幅區間',
    return_90d_range: '近三月漲幅(寬鬆硬篩)',
    return_90d_ideal_range: '近三月理想漲幅區間',
    volume_not_dried_up: '基本流動性仍在',
    return_20d_not_surged: '近一個月尚未噴發',
    close_not_far_from_ema20: '收盤距 EMA20 ≤ 8%',
    ema_not_spread_out: 'EMA 糾結度 ≤ 5%',
    return_20d_pre_breakout: '前期未大幅上漲(診斷參考)',
    return_60_to_20: '前 60-20 日盤整',
    return_20d: '20 日漲幅',
    return_5d_not_overheat: '5 日未過熱',
    base_range: '整理振幅',
    volume_contraction: '縮量整理',
    volume_recovery: '量能回溫',
    ema_spread: 'EMA 糾結度',
    ema_structure: 'EMA 結構',
    relative_strength_20d: '20 日相對強勢',
    relative_strength_60d: '60 日相對強勢',
    risk_filter: '風險過濾',
  };
  const metricToText = (value: unknown): string => {
    if (value == null) return 'null';
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object') {
      return Object.entries(value as Record<string, unknown>)
        .map(([key, item]) => `${key}: ${metricToText(item)}`)
        .join(' / ');
    }
    if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4);
    return String(value);
  };
  const emaSpreadLabels: Record<string, string> = {
    lt_3pct: '< 3%',
    '3pct_to_5pct': '3% - 5%',
    '5pct_to_8pct': '5% - 8%',
    gte_8pct: '>= 8%',
  };
  const emaSlopeLabels: Record<string, string> = {
    ema5_slope_5d: 'EMA5 5日斜率',
    ema10_slope_5d: 'EMA10 5日斜率',
    ema20_slope_10d: 'EMA20 10日斜率',
  };
  const criteria = [
    {
      title: '價格位置',
      items: [
        `近 60 日漲幅 ${formatPct(effectiveParams?.min_return_60d, 0.1)} 到 ${formatPct(effectiveParams?.max_return_60d, 0.3)}`,
        `前 60-20 日盤整漲跌幅不超過 ±${formatPct(effectiveParams?.max_base_return, 0.05)}`,
        `近 20 日漲幅至少 ${formatPct(effectiveParams?.min_return_20d, 0.08)}，近 5 日低於 15%`,
      ],
    },
    {
      title: '整理與量能',
      items: [
        '整理區間振幅小於 20%',
        '整理後半段均量低於前半段 80%',
        '近 5 日均量大於 20 日均量 1.2 倍，或今日量大於 20 日均量 1.5 倍',
      ],
    },
    {
      title: '流動性',
      items: [
        `20 日均量至少 ${(effectiveParams?.min_avg_volume_lots ?? 500).toLocaleString()} 張`,
        `或 20 日均成交金額至少 ${formatMoney(effectiveParams?.min_avg_turnover, 50_000_000)}`,
      ],
    },
    {
      title: '均線與相對強勢',
      items: [
        'EMA5/EMA10/EMA20 糾結度小於 3%',
        '收盤站上 EMA5、EMA10、EMA20，短均線開始向上',
        '近 20 日與近 60 日表現強於加權指數',
      ],
    },
    {
      title: '排除過熱風險',
      items: [
        '近 5 日急漲超過 15% 會標記偏熱',
        '爆量長上影、量能高潮、距 EMA20 超過 15% 會提高風險',
        '輸出為觀察名單，不構成買賣交易訊號',
      ],
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h2 className="text-xl font-bold text-pink-700 dark:text-pink-300">✨ 挑選潛力小股票 🌸</h2>
          <p className="text-sm text-zinc-500 mt-1">幫你掃前 {data?.parameters?.scan_limit ?? request.scanLimit} 檔，找出可能準備起跳的小寶貝 ♡（僅供參考，不是買賣建議）</p>
          <p className="text-xs text-zinc-400 mt-1">
            {!hasScanStarted
              ? '還沒開始找呢～'
              : data
                ? `上次挑選時間：${formatDateTime(data.generated_at)}`
                : loading
                  ? '正在認真找... ♡'
                  : ''}
          </p>
        </div>
        <div className="flex flex-col gap-3 rounded-2xl border border-pink-200 bg-white/80 p-3 backdrop-blur-sm dark:border-pink-900/40 dark:bg-zinc-900/80 sm:flex-row sm:items-center">
          <label className="text-sm font-medium text-zinc-600 dark:text-zinc-300">
            找幾檔
            <input
              type="number"
              min={1}
              max={MAX_SCAN_LIMIT}
              value={scanLimitInput}
              onChange={(event) => setScanLimitInput(event.target.value)}
              className="ml-2 w-28 rounded-full border border-pink-300 bg-white px-3 py-1.5 text-sm text-zinc-900 outline-none focus:border-pink-500 focus:ring-2 focus:ring-pink-200 dark:border-pink-900/60 dark:bg-zinc-950 dark:text-zinc-50"
            />
          </label>
          <label className="flex items-center gap-2 text-sm font-medium text-pink-700 dark:text-pink-300">
            <input
              type="checkbox"
              checked={aiTechOnly}
              onChange={(event) => setAiTechOnly(event.target.checked)}
              className="h-4 w-4 rounded border-pink-300 text-pink-500 focus:ring-pink-400"
            />
            🤖 只看 AI 科技股
          </label>
          <label className="flex items-center gap-2 text-sm font-medium text-zinc-600 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={debugMode}
              onChange={(event) => setDebugMode(event.target.checked)}
              className="h-4 w-4 rounded border-pink-300 text-pink-500 focus:ring-pink-400"
            />
            開發者模式
          </label>
          <button
            type="button"
            disabled={loading}
            onClick={() => startScan(false)}
            className="rounded-full bg-gradient-to-r from-pink-500 to-rose-500 px-4 py-2 text-sm font-semibold text-white shadow-md hover:from-pink-600 hover:to-rose-600 disabled:cursor-not-allowed disabled:opacity-50 transition-all"
          >
            {loading ? '🌸 找尋中...' : '🔍 開始找'}
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => startScan(true)}
            className="rounded-full border border-pink-300 bg-white px-4 py-2 text-sm font-semibold text-pink-600 hover:bg-pink-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-pink-900/60 dark:bg-zinc-900 dark:text-pink-300 dark:hover:bg-pink-950/30"
          >
            {loading ? '🌸 找尋中...' : '♻️ 重新找'}
          </button>
          <button
            type="button"
            disabled={!loading}
            onClick={pauseScan}
            className="rounded-full border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-700 dark:text-amber-300"
          >
            ⏸ 暫停
          </button>
        </div>
        <div className="text-sm font-medium text-pink-700 dark:text-pink-300 bg-pink-50/80 dark:bg-pink-950/30 px-4 py-2 rounded-2xl border border-pink-200 dark:border-pink-900/40">
          掃了 {data?.universe_size ?? request.scanLimit} 檔 ♡ 找到 {data?.matched_count ?? 0} 檔
        </div>
      </div>

      {loading && (
        <div className="rounded-2xl border border-pink-200 bg-gradient-to-r from-pink-50 to-purple-50 p-3 text-sm text-pink-800 dark:border-pink-900/40 dark:from-pink-950/30 dark:to-purple-950/30 dark:text-pink-300">
          <div className="mb-2 flex items-center justify-between">
            <span>{job?.message || `正在認真翻看前 ${request.scanLimit} 檔...`}</span>
            <span>{progressPct}% · {progressCount}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-pink-100 dark:bg-pink-950">
            <div
              className="h-full rounded-full bg-gradient-to-r from-pink-400 to-rose-400 transition-all duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="mt-2 flex flex-col gap-1 text-xs text-pink-700 dark:text-pink-300 sm:flex-row sm:items-center sm:justify-between">
            <span>{currentStock ? `目前：${currentStock}` : '正在等待後端回報逐檔進度'}</span>
            <span>已用時：{elapsedLabel}</span>
          </div>
        </div>
      )}

      {!loading && job?.status === 'cancelled' && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          掃描已暫停。你可以修改掃描檔數，再按「套用掃描」或「重新掃描」重新開始。
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      <details className="rounded-2xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900" open>
        <summary className="cursor-pointer select-none font-semibold text-zinc-800 dark:text-zinc-100">
          篩選標準
        </summary>
        <div className="mt-4 grid gap-3 lg:grid-cols-5">
          {criteria.map((group) => (
            <div key={group.title} className="rounded-2xl border border-zinc-100 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
              <div className="font-semibold text-zinc-800 dark:text-zinc-100">{group.title}</div>
              <ul className="mt-2 space-y-1.5 text-xs leading-5 text-zinc-600 dark:text-zinc-400">
                {group.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </details>

      <div>
        <div className="mb-2 flex items-center justify-between gap-3 text-xs text-zinc-500 dark:text-zinc-400">
          <span>🌸 點分類卡片切換要看哪幾種</span>
          <button
            type="button"
            onClick={() => setSelectedTypes(new Set(['起漲前觀察', '初動候選']))}
            className="rounded-full border border-pink-200 px-3 py-1 text-pink-600 hover:border-pink-400 hover:bg-pink-50 dark:border-pink-900/40 dark:text-pink-300 dark:hover:bg-pink-950/30"
          >
            ↺ 重設
          </button>
        </div>
        <div className="grid gap-3 md:grid-cols-5">
          {['起漲前觀察', '初動候選', '動能確認', '偏熱觀察', '不符合'].map(type => {
            const isSelected = selectedTypes.has(type);
            return (
              <button
                key={type}
                type="button"
                onClick={() => setSelectedTypes(prev => {
                  const next = new Set(prev);
                  if (next.has(type)) next.delete(type); else next.add(type);
                  return next;
                })}
                className={`text-left rounded-3xl border p-3 text-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md ${
                  isSelected
                    ? 'border-pink-400 bg-gradient-to-br from-pink-50 to-purple-50 shadow-md dark:border-pink-500 dark:from-pink-950/30 dark:to-purple-950/30'
                    : 'border-pink-100 bg-white hover:border-pink-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-pink-700'
                }`}
              >
                <div className="flex items-center gap-1">
                  <span className={isSelected ? 'text-pink-700 dark:text-pink-300 font-medium' : 'text-zinc-500 dark:text-zinc-400'}>
                    {isSelected ? '♡ ' : ''}{type}
                  </span>
                </div>
                <div className="mt-1 text-xl font-bold text-zinc-900 dark:text-zinc-50">{data?.summary?.[type] ?? 0}</div>
              </button>
            );
          })}
        </div>
      </div>

      {data?.data_warnings?.length ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          資料提醒：{data.data_warnings.join('、')}
        </div>
      ) : null}

      {data?.funnel_report ? (
        <details className="rounded-2xl border border-blue-200 bg-white p-4 text-sm dark:border-blue-900 dark:bg-zinc-900" open>
          <summary className="cursor-pointer select-none font-semibold text-zinc-800 dark:text-zinc-100">
            Debug 漏斗報告
          </summary>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(data.funnel_report.stage_counts).map(([key, value]) => (
              <div key={key} className="rounded-2xl border border-zinc-100 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
                <div className="text-xs text-zinc-500 dark:text-zinc-400">{stageLabels[key] ?? key}</div>
                <div className="mt-1 text-lg font-bold text-zinc-900 dark:text-zinc-50">{value.toLocaleString()}</div>
              </div>
            ))}
          </div>
          {(data.funnel_report.ema_spread_distribution || data.funnel_report.ema_slope_distribution) && (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {data.funnel_report.ema_spread_distribution && (
                <div className="rounded-2xl border border-zinc-100 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
                  <div className="font-semibold text-zinc-800 dark:text-zinc-100">EMA 糾結分布</div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                    {Object.entries(data.funnel_report.ema_spread_distribution).map(([key, value]) => (
                      <div key={key} className="rounded-xl bg-white p-2 dark:bg-zinc-900">
                        <div>{emaSpreadLabels[key] ?? key}</div>
                        <div className="mt-1 text-base font-bold text-zinc-900 dark:text-zinc-50">{value.toLocaleString()}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {data.funnel_report.ema_slope_distribution && (
                <div className="rounded-2xl border border-zinc-100 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950/50">
                  <div className="font-semibold text-zinc-800 dark:text-zinc-100">EMA 斜率分布</div>
                  <div className="mt-3 space-y-2 text-xs text-zinc-600 dark:text-zinc-400">
                    {Object.entries(data.funnel_report.ema_slope_distribution).map(([key, value]) => (
                      <div key={key} className="rounded-xl bg-white p-2 dark:bg-zinc-900">
                        <div className="font-medium text-zinc-800 dark:text-zinc-100">{emaSlopeLabels[key] ?? key}</div>
                        <div className="mt-1">{metricToText(value)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="mt-4 overflow-x-auto rounded-2xl border border-zinc-100 dark:border-zinc-800">
            <table className="min-w-full divide-y divide-zinc-100 text-xs dark:divide-zinc-800">
              <thead className="bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-950 dark:text-zinc-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">條件</th>
                  <th className="px-3 py-2 font-semibold">通過</th>
                  <th className="px-3 py-2 font-semibold">失敗</th>
                  <th className="px-3 py-2 font-semibold">通過率</th>
                  <th className="px-3 py-2 font-semibold">最接近失敗範例</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {Object.entries(data.funnel_report.condition_reports).map(([key, report]) => {
                  const firstExample = report.top_10_closest_failed_examples[0];
                  return (
                    <tr key={key} className="align-top text-zinc-700 dark:text-zinc-300">
                      <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">{conditionLabels[key] ?? report.condition}</td>
                      <td className="px-3 py-2">{report.pass_count.toLocaleString()}</td>
                      <td className="px-3 py-2">{report.fail_count.toLocaleString()}</td>
                      <td className="px-3 py-2">{(report.pass_rate * 100).toFixed(1)}%</td>
                      <td className="max-w-xl px-3 py-2">
                        {firstExample ? (
                          <div className="space-y-1">
                            <div className="font-medium">{firstExample.stock_id} {firstExample.stock_name}</div>
                            <div className="text-zinc-500 dark:text-zinc-400">{metricToText(firstExample.key_metrics)}</div>
                            <div className="text-zinc-400">threshold: {metricToText(firstExample.threshold)}</div>
                          </div>
                        ) : (
                          <span className="text-zinc-400">無失敗範例</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}

      {!hasScanStarted && !loading && (
        <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-10 text-center dark:border-zinc-800 dark:bg-zinc-900/50">
          <p className="text-zinc-500 dark:text-zinc-400">尚未執行篩選，請按下篩選按鈕開始掃描。</p>
        </div>
      )}

      {hasScanStarted && (
        <>
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            分數只代表符合飆股前兆程度，不代表可直接進場。80 分以上為高優先觀察，70 分附近也建議看圖確認。
          </p>
          {(() => {
            const filteredResults = data?.results.filter(r => selectedTypes.has(r.candidate_type)) ?? [];
            const totalCount = data?.results.length ?? 0;
            if (selectedTypes.size === 0) {
              return (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                  尚未選擇任何分類，請點上方分類卡片至少選一個。
                </div>
              );
            }
            if (filteredResults.length === 0 && totalCount > 0) {
              return (
                <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-400">
                  目前篩選條件下沒有股票（共 {totalCount} 檔被掃描）。可點上方其他分類卡片擴大範圍。
                </div>
              );
            }
            return (
              <>
                {filteredResults.length < totalCount && (
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    顯示 {filteredResults.length} / {totalCount} 檔（已套用分類篩選：{Array.from(selectedTypes).join('、')}）
                  </p>
                )}
                <div className="grid gap-4 stagger-children">
                  {filteredResults.map((item, index) => {
              const cardId = `${item.stock_id}-${index}`;
              const isExpanded = expandedIds.has(cardId);
              const isChartOpen = chartOpenIds.has(cardId);
              const tier = getScoreTier(item.surge_candidate_score);
              return (
                <div key={cardId} className="border border-pink-100 dark:border-pink-900/40 rounded-3xl bg-white dark:bg-zinc-900 shadow-sm hover:border-pink-300 hover:shadow-lg hover:-translate-y-0.5 dark:hover:border-pink-700 transition-all duration-300 animate-fade-in-up">
                  <div className="p-5">
                    <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                      <div className="flex items-center gap-3 flex-wrap">
                        <span className="text-sm font-semibold text-zinc-400">#{item.rank}</span>
                        <h3 className="text-lg font-bold text-zinc-800 dark:text-zinc-100">{item.stock_id} {item.stock_name}</h3>
                <span className={`px-2.5 py-1 text-xs font-semibold rounded-full ${
                  item.candidate_type === '起漲前觀察' ? 'bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-300' :
                  item.candidate_type === '初動候選' ? 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300' :
                  item.candidate_type === '動能確認' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300' :
                          'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                        }`}>♡ {item.candidate_type}</span>
                        <span className={`px-2 py-0.5 text-xs font-semibold rounded-full ${tier.colorClass}`}>{tier.label}</span>
                        {item.metrics.sector_label && (
                          <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-gradient-to-r from-cyan-100 to-blue-100 text-cyan-700 dark:from-cyan-900 dark:to-blue-900 dark:text-cyan-300">
                            🤖 {item.metrics.sector_label}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-4 text-sm font-medium">
                        <span className="text-pink-600 dark:text-pink-400">分數: {item.surge_candidate_score}</span>
                        <span className="text-emerald-600 dark:text-emerald-400">信心: {item.confidence_score}</span>
                        <span className="text-rose-600 dark:text-rose-400">風險: {item.risk_score}</span>
                      </div>
                    </div>
                    <div className="mb-3 grid gap-2 text-xs text-zinc-600 dark:text-zinc-400 sm:grid-cols-4">
                      <span>90日擺盪 {(item.metrics.range_90d * 100).toFixed(1)}%</span>
                      <span>20日漲幅 {(item.metrics.return_20d * 100).toFixed(1)}%</span>
                      <span>20日均量 {item.metrics.avg_volume_20_lots.toLocaleString(undefined, { maximumFractionDigits: 0 })} 張</span>
                      <span>相對強勢 {item.metrics.relative_strength_20d == null ? '缺資料' : `${(item.metrics.relative_strength_20d * 100).toFixed(1)}%`}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => toggleExpanded(cardId)}
                      className="flex items-center gap-1.5 text-xs font-medium text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100 transition-colors"
                    >
                      {isExpanded ? '▲ 收合詳情' : '▼ 展開詳情'}
                    </button>
                  </div>

                  {isExpanded && (
                    <div className="border-t border-zinc-100 dark:border-zinc-800 p-5 space-y-5">
                      <div className="grid md:grid-cols-3 gap-5 text-sm">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-3 rounded-2xl">
                          <h4 className="font-semibold text-zinc-800 dark:text-zinc-200 mb-2 flex items-center gap-2"><span className="text-blue-500">✓</span> 入選理由</h4>
                          <ul className="space-y-1.5 text-zinc-600 dark:text-zinc-400">{item.reasons.map((r, i) => <li key={i} className="flex gap-2"><span className="text-zinc-400">•</span> {r}</li>)}</ul>
                        </div>
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-3 rounded-2xl">
                          <h4 className="font-semibold text-zinc-800 dark:text-zinc-200 mb-2 flex items-center gap-2"><span className="text-amber-500">👁</span> 觀察條件</h4>
                          <ul className="space-y-1.5 text-zinc-600 dark:text-zinc-400">{item.watch_conditions.map((r, i) => <li key={i} className="flex gap-2"><span className="text-zinc-400">•</span> {r}</li>)}</ul>
                        </div>
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-3 rounded-2xl">
                          <h4 className="font-semibold text-zinc-800 dark:text-zinc-200 mb-2 flex items-center gap-2"><span className="text-rose-500">✕</span> 失效條件</h4>
                          <ul className="space-y-1.5 text-zinc-600 dark:text-zinc-400">{item.invalidation.map((r, i) => <li key={i} className="flex gap-2"><span className="text-zinc-400">•</span> {r}</li>)}</ul>
                        </div>
                      </div>
                      {item.risk_flags.length > 0 && (
                        <div className="flex gap-2 text-sm items-center text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/30 p-2.5 rounded-2xl">
                          <span className="font-bold">⚠️ 風險提示:</span><span>{item.risk_flags.join('、')}</span>
                        </div>
                      )}
                      <div className="rounded-2xl border border-zinc-100 dark:border-zinc-800 p-3">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">K 線圖觀察</span>
                          <button
                            type="button"
                            onClick={() => toggleChart(cardId)}
                            className="px-3 py-1 text-xs rounded-full font-semibold bg-gradient-to-r from-pink-400 to-rose-400 text-white shadow-sm hover:from-pink-500 hover:to-rose-500 hover:shadow-md transition-all"
                          >
                            {isChartOpen ? '關閉圖表' : '查看 K 線'}
                          </button>
                        </div>
                        {isChartOpen ? (
                          <PriceHistoryChart stockCode={item.stock_id} />
                        ) : (
                          <p className="text-xs text-zinc-400 dark:text-zinc-500">點擊「查看 K 線」載入圖表（{item.stock_id}）</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
                  {!loading && data?.results.length === 0 && (
                    <div className="text-center py-10 text-zinc-500">本次掃描無符合條件的候選股</div>
                  )}
                </div>
              </>
            );
          })()}
        </>
      )}
    </div>
  );
}
