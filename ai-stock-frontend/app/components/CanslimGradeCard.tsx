'use client';

import { useEffect, useState } from 'react';
import { getTwScreenFull } from '@/lib/api';
import type {
  CanslimFullResult,
  CanslimGrade,
  CanslimFactor,
  PillarStatus,
  StructureStatus,
} from '@/lib/types';

const FACTOR_LABELS: Record<CanslimFactor, string> = {
  C: '當季盈餘 (Current)',
  A: '年度盈餘 (Annual)',
  N: '創新高/題材 (New)',
  S: '籌碼供需 (Supply)',
  L: '相對強弱 (Leader)',
  I: '法人動向 (Institutional)',
  M: '大盤方向 (Market)',
};

const GRADE_STYLES: Record<CanslimGrade, string> = {
  S: 'bg-emerald-500 text-white',
  A: 'bg-green-500 text-white',
  B: 'bg-sky-500 text-white',
  C: 'bg-amber-500 text-white',
  D: 'bg-zinc-400 text-white dark:bg-zinc-600',
};

const STATUS_STYLES: Record<PillarStatus, string> = {
  Pass: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  Weak: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  Fail: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  AI_Review_Required: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  Neutral: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  Insufficient_Data: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
};

const STATUS_LABELS: Record<PillarStatus, string> = {
  Pass: '符合',
  Weak: '偏弱',
  Fail: '不符',
  AI_Review_Required: '待AI複核',
  Neutral: '中性',
  Insufficient_Data: '資料不足',
};

const PASS_STATUS_LABELS: Record<string, string> = {
  PASS: '全數符合',
  WATCHLIST: '觀察名單',
  FAIL: '未通過',
  INSUFFICIENT_DATA: '資料不足',
};

const PASS_STATUS_STYLES: Record<string, string> = {
  PASS: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  WATCHLIST: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  FAIL: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  INSUFFICIENT_DATA: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
};

const STRUCTURE_LABELS: Record<StructureStatus, string> = {
  intact: '結構完整',
  weakening: '短期轉弱',
  profit_watch: '延伸/獲利了結觀察區',
  invalidated: '結構失效',
};

const STRUCTURE_STYLES: Record<StructureStatus, string> = {
  intact: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  weakening: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  profit_watch: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  invalidated: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
};

const REGIME_LABELS: Record<string, string> = {
  risk_on: '偏多 (risk-on)',
  risk_off: '偏空 (risk-off)',
  severe: '嚴峻 (severe)',
  unknown: '未知',
};

const LEVEL_LABELS: Record<string, string> = { HIGH: '高', MEDIUM: '中', LOW: '低' };

const ORDER: CanslimFactor[] = ['C', 'A', 'N', 'S', 'L', 'I', 'M'];

export default function CanslimGradeCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<CanslimFullResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    getTwScreenFull(symbol)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((exc) => {
        if (!cancelled) {
          setError(
            exc?.response?.data?.detail ||
              (exc instanceof Error ? exc.message : '無法取得 CANSLIM 分級。')
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (loading) {
    return (
      <div className="rounded-2xl border border-zinc-200 bg-white p-5 text-sm text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
        正在計算 CANSLIM 七大面向分級…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-zinc-200 bg-white p-5 text-sm text-zinc-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
        CANSLIM 分級暫時無法取得：{error}
      </div>
    );
  }

  if (!data) return null;

  const regime = data.screening_result?.market_regime;
  const structure = data.screening_result?.structure_status;
  const exitSignals = data.screening_result?.exit_signals ?? [];
  const factorsByKey = new Map(data.per_factor_scores.map((f) => [f.factor, f]));

  return (
    <div className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {/* Header: grade + score + status badges */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div
            className={`flex h-16 w-16 items-center justify-center rounded-2xl text-3xl font-black ${GRADE_STYLES[data.grade]}`}
          >
            {data.grade}
          </div>
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold text-zinc-950 dark:text-zinc-50">
                {data.overall_score}
              </span>
              <span className="text-sm text-zinc-400 dark:text-zinc-500">/ 100 綜合分數</span>
            </div>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              CANSLIM 分級 · as of {data.as_of_date}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${PASS_STATUS_STYLES[data.pass_status] ?? PASS_STATUS_STYLES.FAIL}`}
          >
            {PASS_STATUS_LABELS[data.pass_status] ?? data.pass_status}
          </span>
          <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            信心 {LEVEL_LABELS[data.confidence] ?? data.confidence}
          </span>
          <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            風險 {LEVEL_LABELS[data.risk_level] ?? data.risk_level}
          </span>
          {regime && (
            <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              大盤 {REGIME_LABELS[regime] ?? regime}
            </span>
          )}
          {data.is_mock_or_fallback_data && (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
              ● 部分為模擬/回退資料
            </span>
          )}
        </div>
      </div>

      {/* Swing structure + exit signals */}
      {(structure || exitSignals.length > 0) && (
        <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950/50">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              波段結構
            </span>
            {structure && (
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STRUCTURE_STYLES[structure]}`}
              >
                {STRUCTURE_LABELS[structure]}
              </span>
            )}
          </div>
          {exitSignals.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
              {exitSignals.map((s, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-rose-500">▸</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* 7 factor grid */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          七大面向
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {ORDER.map((key) => {
            const f = factorsByKey.get(key);
            if (!f) return null;
            return (
              <div
                key={key}
                className="flex items-start gap-3 rounded-xl border border-zinc-200 p-3 dark:border-zinc-800"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-base font-bold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                  {key}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
                      {FACTOR_LABELS[key]}
                    </span>
                    <span className="flex items-center gap-1.5">
                      {f.score !== null && (
                        <span className="text-xs font-semibold text-zinc-500 dark:text-zinc-400">
                          {f.score}
                        </span>
                      )}
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLES[f.status]}`}
                      >
                        {STATUS_LABELS[f.status]}
                      </span>
                    </span>
                  </div>
                  {f.reason && (
                    <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
                      {f.reason}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Reasons */}
      {(data.positive_reasons.length > 0 || data.negative_reasons.length > 0) && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.positive_reasons.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                正向觀察
              </p>
              <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
                {data.positive_reasons.map((r, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-emerald-500">＋</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.negative_reasons.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold text-rose-600 dark:text-rose-400">
                風險/疑慮
              </p>
              <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
                {data.negative_reasons.map((r, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-rose-500">－</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Observation conditions + invalidation */}
      {(data.observation_conditions.length > 0 || data.invalidation_signals.length > 0) && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.observation_conditions.length > 0 && (
            <div className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-1 text-xs font-semibold text-zinc-500 dark:text-zinc-400">
                觀察條件
              </p>
              <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
                {data.observation_conditions.map((c, i) => (
                  <li key={i}>· {c}</li>
                ))}
              </ul>
            </div>
          )}
          {data.invalidation_signals.length > 0 && (
            <div className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-1 text-xs font-semibold text-zinc-500 dark:text-zinc-400">
                失效訊號
              </p>
              <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
                {data.invalidation_signals.map((c, i) => (
                  <li key={i}>· {c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {data.suggested_strategy && (
        <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-300">
          {data.suggested_strategy}
        </p>
      )}

      <p className="border-t border-zinc-100 pt-3 text-xs text-zinc-400 dark:border-zinc-800 dark:text-zinc-500">
        本分析僅供參考，不構成投資建議。分級為條件吻合度標籤，非保證報酬。
      </p>
    </div>
  );
}
