'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { TaiwanStockAnalysisResponse } from '@/lib/types';
import type { AIAnalysisResult } from '@/types/aiAnalysis';
import {
  fetchAIAnalysis,
  fetchAIAnalysisV2Overlay,
  fetchMultiAgentOverlay,
  fromTaiwanAnalysis,
  getMockAIAnalysis,
} from '@/lib/ai-analysis/client';

interface UseAIAnalysisOptions {
  sourceData?: TaiwanStockAnalysisResponse | null;
}

export function useAIAnalysis(symbol: string, options: UseAIAnalysisOptions = {}) {
  const { sourceData } = options;
  const [data, setData] = useState<AIAnalysisResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const transformedSourceData = useMemo(() => {
    if (!sourceData) return null;
    return fromTaiwanAnalysis(sourceData);
  }, [sourceData]);

  const load = useCallback(async () => {
    if (transformedSourceData) {
      setData(transformedSourceData);
      setError(null);
      const withV2 = await fetchAIAnalysisV2Overlay(symbol, transformedSourceData);
      setData(withV2);
      const withAgents = await fetchMultiAgentOverlay(symbol, withV2);
      setData(withAgents);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const next = await fetchAIAnalysis(symbol);
      setData(next);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('AI 分析讀取失敗'));
      setData(getMockAIAnalysis(symbol));
    } finally {
      setIsLoading(false);
    }
  }, [symbol, transformedSourceData]);

  useEffect(() => {
    queueMicrotask(() => {
      load();
    });
  }, [load]);

  return {
    data: data ?? transformedSourceData,
    isLoading,
    error,
    refetch: load,
  };
}
