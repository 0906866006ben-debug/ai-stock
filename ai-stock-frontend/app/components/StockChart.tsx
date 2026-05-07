'use client';

import { useEffect, useRef } from 'react';
import { createChart, LineSeries, CandlestickSeries } from 'lightweight-charts';
import { ChartPoint } from '@/lib/api';
import { CandlePoint } from '@/lib/types';

interface StockChartProps {
  chartData: ChartPoint[] | CandlePoint[];
  symbol: string;
  mode?: 'line' | 'candle';
}

export default function StockChart({ chartData, symbol, mode = 'line' }: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 260,
      layout: {
        background: { color: 'transparent' },
        textColor: '#6b7280',
      },
      grid: {
        vertLines: { color: '#e5e7eb' },
        horzLines: { color: '#e5e7eb' },
      },
      timeScale: { borderColor: '#e5e7eb' },
      rightPriceScale: { borderColor: '#e5e7eb' },
    });

    if (mode === 'candle') {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderUpColor: '#22c55e',
        borderDownColor: '#ef4444',
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      });
      if (chartData.length > 0) {
        series.setData(chartData as CandlePoint[]);
        chart.timeScale().fitContent();
      }
    } else {
      const series = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2 });
      if (chartData.length > 0) {
        series.setData(chartData as ChartPoint[]);
        chart.timeScale().fitContent();
      }
    }

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [chartData, mode]);

  const label = mode === 'candle' ? `K線圖 — ${symbol}` : `Price Chart — ${symbol}`;
  const emptyMsg = mode === 'candle' ? '目前無圖表資料。' : 'No chart data available.';

  if (chartData.length === 0) {
    return (
      <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {label}
        </h3>
        <p className="mt-4 text-center text-sm text-zinc-400 dark:text-zinc-500">{emptyMsg}</p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {label}
      </h3>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
