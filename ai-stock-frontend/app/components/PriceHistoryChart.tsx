'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  createChart, IChartApi, CandlestickSeries, LineSeries, HistogramSeries,
  CrosshairMode,
} from 'lightweight-charts';
import { getTwPriceHistory } from '@/lib/api';
import type { PriceHistoryResponse, CandlePoint } from '@/lib/types';

type Range = 'D' | 'W' | 'M' | 'Y';
const RANGES: { code: Range; label: string }[] = [
  { code: 'D', label: '日線' },
  { code: 'W', label: '週線' },
  { code: 'M', label: '月線' },
  { code: 'Y', label: '年線' },
];

interface IndicatorToggles {
  ma5: boolean;
  ma20: boolean;
  ma60: boolean;
  volume: boolean;
  rsi: boolean;
  macd: boolean;
}

const DEFAULT_TOGGLES: IndicatorToggles = {
  ma5: false,
  ma20: true,
  ma60: false,
  volume: true,
  rsi: false,
  macd: false,
};

const COLORS = {
  ma5: '#f97316',   // orange
  ma20: '#3b82f6',  // blue
  ma60: '#a855f7',  // purple
  rsi: '#06b6d4',   // cyan
  macdLine: '#3b82f6',
  signalLine: '#ef4444',
  upBar: '#22c55e',
  downBar: '#ef4444',
  rsiOverbought: '#ef4444',
  rsiOversold: '#22c55e',
};

interface Props {
  stockCode: string;
  initialCandles?: CandlePoint[];
}

function indicatorParam(t: IndicatorToggles): string {
  const parts: string[] = [];
  if (t.ma5 || t.ma20 || t.ma60) parts.push('ma');
  if (t.volume) parts.push('volume');
  if (t.rsi) parts.push('rsi');
  if (t.macd) parts.push('macd');
  return parts.join(',');
}

export default function PriceHistoryChart({ stockCode, initialCandles }: Props) {
  const [range, setRange] = useState<Range>('D');
  const [toggles, setToggles] = useState<IndicatorToggles>(DEFAULT_TOGGLES);
  const [data, setData] = useState<PriceHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Chart refs
  const priceContainerRef = useRef<HTMLDivElement>(null);
  const volumeContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const chartsRef = useRef<IChartApi[]>([]);

  const fetchHistory = useCallback(async (r: Range, t: IndicatorToggles) => {
    setLoading(true);
    setError(null);
    try {
      const param = indicatorParam(t);
      const result = await getTwPriceHistory(stockCode, r, param);
      setData(result);
    } catch {
      setError('無法載入價格歷史');
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    fetchHistory(range, toggles);
  }, [fetchHistory, range, toggles]);

  const candles = data?.candles ?? initialCandles ?? [];
  const indicators = data?.indicators ?? null;

  // Render charts
  useEffect(() => {
    // Cleanup previous
    chartsRef.current.forEach((c) => c.remove());
    chartsRef.current = [];

    if (!priceContainerRef.current || candles.length === 0) return;

    // Tune candle width by visible-bar count so each chart still feels readable
    const desiredBarSpacing =
      candles.length > 100 ? 6 :
      candles.length > 50  ? 10 :
      candles.length > 20  ? 16 :
      24;

    const baseOptions = {
      layout: { background: { color: 'transparent' }, textColor: '#6b7280', fontSize: 12 },
      grid: {
        vertLines: { color: 'rgba(229, 231, 235, 0.5)' },
        horzLines: { color: 'rgba(229, 231, 235, 0.5)' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: {
        borderColor: '#e5e7eb',
        timeVisible: true,
        rightOffset: 6,
        barSpacing: desiredBarSpacing,
        minBarSpacing: 3,
      },
      rightPriceScale: {
        borderColor: '#e5e7eb',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    };

    // ── Price pane (with MA overlays) ────────────────────────────────────────
    const priceChart = createChart(priceContainerRef.current, {
      ...baseOptions,
      width: priceContainerRef.current.clientWidth,
      height: 460,
    });
    chartsRef.current.push(priceChart);

    const candleSeries = priceChart.addSeries(CandlestickSeries, {
      upColor: COLORS.upBar,
      downColor: COLORS.downBar,
      borderUpColor: COLORS.upBar,
      borderDownColor: COLORS.downBar,
      wickUpColor: COLORS.upBar,
      wickDownColor: COLORS.downBar,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
    candleSeries.setData(candles);

    addMaLine(priceChart, candles, indicators?.ma5, toggles.ma5, COLORS.ma5);
    addMaLine(priceChart, candles, indicators?.ma20, toggles.ma20, COLORS.ma20);
    addMaLine(priceChart, candles, indicators?.ma60, toggles.ma60, COLORS.ma60);

    // ── Volume pane ──────────────────────────────────────────────────────────
    if (toggles.volume && volumeContainerRef.current) {
      const volChart = createChart(volumeContainerRef.current, {
        ...baseOptions,
        width: volumeContainerRef.current.clientWidth,
        height: 130,
        rightPriceScale: {
          borderColor: '#e5e7eb',
          scaleMargins: { top: 0.2, bottom: 0 },
        },
      });
      chartsRef.current.push(volChart);

      const volSeries = volChart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
      });
      const volData = candles.map((c, i) => ({
        time: c.time,
        value: indicators?.volume?.[i] ?? c.volume ?? 0,
        color: c.close >= c.open ? `${COLORS.upBar}80` : `${COLORS.downBar}80`,
      }));
      volSeries.setData(volData);
      syncTimeScale(priceChart, volChart);
    }

    // ── RSI pane ─────────────────────────────────────────────────────────────
    if (toggles.rsi && rsiContainerRef.current && indicators?.rsi) {
      const rsiChart = createChart(rsiContainerRef.current, {
        ...baseOptions,
        width: rsiContainerRef.current.clientWidth,
        height: 140,
        rightPriceScale: {
          borderColor: '#e5e7eb',
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });
      chartsRef.current.push(rsiChart);

      const rsiSeries = rsiChart.addSeries(LineSeries, {
        color: COLORS.rsi,
        lineWidth: 2,
      });
      const rsiData = candles
        .map((c, i) => ({ time: c.time, value: indicators.rsi![i] ?? null }))
        .filter((p) => p.value !== null) as { time: string; value: number }[];
      rsiSeries.setData(rsiData);

      // Overbought/oversold reference lines
      rsiSeries.createPriceLine({
        price: 70,
        color: COLORS.rsiOverbought,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'OB',
      });
      rsiSeries.createPriceLine({
        price: 30,
        color: COLORS.rsiOversold,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'OS',
      });

      syncTimeScale(priceChart, rsiChart);
    }

    // ── MACD pane ────────────────────────────────────────────────────────────
    if (toggles.macd && macdContainerRef.current && indicators?.macd) {
      const macdChart = createChart(macdContainerRef.current, {
        ...baseOptions,
        width: macdContainerRef.current.clientWidth,
        height: 140,
        rightPriceScale: {
          borderColor: '#e5e7eb',
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });
      chartsRef.current.push(macdChart);

      const histSeries = macdChart.addSeries(HistogramSeries, {});
      const histData = candles
        .map((c, i) => {
          const v = indicators.macd!.histogram[i];
          if (v === null) return null;
          return {
            time: c.time,
            value: v,
            color: v >= 0 ? `${COLORS.upBar}90` : `${COLORS.downBar}90`,
          };
        })
        .filter((p): p is { time: string; value: number; color: string } => p !== null);
      histSeries.setData(histData);

      const macdLineSeries = macdChart.addSeries(LineSeries, {
        color: COLORS.macdLine,
        lineWidth: 2,
      });
      const macdLineData = candles
        .map((c, i) => ({ time: c.time, value: indicators.macd!.macd[i] ?? null }))
        .filter((p) => p.value !== null) as { time: string; value: number }[];
      macdLineSeries.setData(macdLineData);

      const signalSeries = macdChart.addSeries(LineSeries, {
        color: COLORS.signalLine,
        lineWidth: 1,
      });
      const signalData = candles
        .map((c, i) => ({ time: c.time, value: indicators.macd!.signal[i] ?? null }))
        .filter((p) => p.value !== null) as { time: string; value: number }[];
      signalSeries.setData(signalData);

      syncTimeScale(priceChart, macdChart);
    }

    // Resize handler
    const handleResize = () => {
      chartsRef.current.forEach((c, idx) => {
        const containers = [
          priceContainerRef.current,
          toggles.volume ? volumeContainerRef.current : null,
          toggles.rsi ? rsiContainerRef.current : null,
          toggles.macd ? macdContainerRef.current : null,
        ].filter(Boolean) as HTMLElement[];
        if (containers[idx]) {
          c.applyOptions({ width: containers[idx].clientWidth });
        }
      });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartsRef.current.forEach((c) => c.remove());
      chartsRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, indicators, toggles.ma5, toggles.ma20, toggles.ma60, toggles.volume, toggles.rsi, toggles.macd]);

  const togglesList: { key: keyof IndicatorToggles; label: string; color: string }[] = useMemo(() => [
    { key: 'ma5', label: 'MA5', color: COLORS.ma5 },
    { key: 'ma20', label: 'MA20', color: COLORS.ma20 },
    { key: 'ma60', label: 'MA60', color: COLORS.ma60 },
    { key: 'volume', label: '成交量', color: '#71717a' },
    { key: 'rsi', label: 'RSI', color: COLORS.rsi },
    { key: 'macd', label: 'MACD', color: COLORS.macdLine },
  ], []);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          K 線圖
          {data?.is_mock && (
            <span className="ml-2 text-xs font-normal text-amber-500">模擬資料</span>
          )}
        </h3>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.code}
              onClick={() => setRange(r.code)}
              disabled={loading}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                range === r.code
                  ? 'bg-blue-600 text-white'
                  : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Indicator toggles */}
      <div className="mb-3 flex flex-wrap gap-2 border-b border-zinc-100 pb-3 dark:border-zinc-800">
        {togglesList.map(({ key, label, color }) => (
          <label
            key={key}
            className="flex cursor-pointer items-center gap-1.5 rounded-full border border-zinc-200 px-2.5 py-1 text-xs hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600"
          >
            <input
              type="checkbox"
              checked={toggles[key]}
              onChange={(e) =>
                setToggles((t) => ({ ...t, [key]: e.target.checked }))
              }
              className="h-3 w-3 cursor-pointer"
            />
            <span className="h-2 w-3 rounded-sm" style={{ backgroundColor: color }} />
            <span className="text-zinc-600 dark:text-zinc-300">{label}</span>
          </label>
        ))}
      </div>

      {loading && (
        <div className="flex h-32 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        </div>
      )}

      {error && !loading && <p className="text-sm text-red-500">{error}</p>}

      {!loading && candles.length > 0 && (
        <div className="space-y-1">
          <div ref={priceContainerRef} className="w-full" />
          {toggles.volume && (
            <div>
              <div className="text-xs text-zinc-400 mt-2">成交量</div>
              <div ref={volumeContainerRef} className="w-full" />
            </div>
          )}
          {toggles.rsi && (
            <div>
              <div className="text-xs text-zinc-400 mt-2">RSI (14)</div>
              <div ref={rsiContainerRef} className="w-full" />
            </div>
          )}
          {toggles.macd && (
            <div>
              <div className="text-xs text-zinc-400 mt-2">MACD (12, 26, 9)</div>
              <div ref={macdContainerRef} className="w-full" />
            </div>
          )}
        </div>
      )}

      {!loading && !error && candles.length === 0 && (
        <p className="text-sm text-zinc-400">此期間無資料</p>
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function addMaLine(
  chart: IChartApi,
  candles: CandlePoint[],
  series: (number | null)[] | null | undefined,
  enabled: boolean,
  color: string,
) {
  if (!enabled || !series) return;
  const line = chart.addSeries(LineSeries, {
    color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
  });
  const data = candles
    .map((c, i) => ({ time: c.time, value: series[i] ?? null }))
    .filter((p) => p.value !== null) as { time: string; value: number }[];
  if (data.length > 0) line.setData(data);
}

function syncTimeScale(master: IChartApi, slave: IChartApi) {
  master.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (range) slave.timeScale().setVisibleLogicalRange(range);
  });
  slave.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (range) master.timeScale().setVisibleLogicalRange(range);
  });
}

