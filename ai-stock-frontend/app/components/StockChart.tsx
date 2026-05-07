'use client';

import { useEffect, useRef } from 'react';
import { createChart, LineSeries, CandlestickSeries } from 'lightweight-charts';
import { ChartPoint } from '@/lib/api';
import { CandlePoint } from '@/lib/types';

interface LineChartProps {
  chartType: 'line';
  chartData: ChartPoint[];
  symbol: string;
}

interface CandleChartProps {
  chartType: 'candlestick';
  chartData: CandlePoint[];
  symbol: string;
}

type StockChartProps = LineChartProps | CandleChartProps;

export default function StockChart({ chartType, chartData, symbol }: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || chartData.length === 0) return;

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

    if (chartType === 'candlestick') {
      const series = chart.addSeries(CandlestickSeries, {});
      series.setData(chartData as CandlePoint[]);
    } else {
      const series = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2 });
      series.setData(chartData as ChartPoint[]);
    }
    chart.timeScale().fitContent();

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
  }, [chartData, chartType]);

  const heading = chartType === 'candlestick' ? '價格走勢' : 'Price Chart';
  const empty = chartType === 'candlestick' ? '無圖表資料。' : 'No chart data available.';

  if (chartData.length === 0) {
    return (
      <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {heading} — {symbol}
        </h3>
        <p className="mt-4 text-center text-sm text-zinc-400 dark:text-zinc-500">{empty}</p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {heading} — {symbol}
      </h3>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
