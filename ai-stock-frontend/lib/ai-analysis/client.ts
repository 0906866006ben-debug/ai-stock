import { analyzeTW } from '@/lib/api';
import type { TaiwanStockAnalysisResponse } from '@/lib/types';
import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { parabolicOverheatAnalysis, springEventAnalysis, tsmc2330Analysis, vcpConsolidationAnalysis } from './mock-data';
import { transformTaiwanAnalysisToAI } from './transformers';

const FIXTURES: Record<string, AIAnalysisResult> = {
  '2330': tsmc2330Analysis,
  overheat: parabolicOverheatAnalysis,
  vcp: vcpConsolidationAnalysis,
  spring: springEventAnalysis,
};

export function getMockAIAnalysis(symbol: string): AIAnalysisResult {
  return FIXTURES[symbol] ?? {
    ...tsmc2330Analysis,
    symbol,
    symbol_name: symbol === '2330' ? '台積電' : `${symbol} 示範分析`,
  };
}

export async function fetchAIAnalysis(symbol: string): Promise<AIAnalysisResult> {
  if (FIXTURES[symbol]) {
    return FIXTURES[symbol];
  }

  try {
    const twData = await analyzeTW(symbol);
    return transformTaiwanAnalysisToAI(twData);
  } catch {
    return getMockAIAnalysis(symbol);
  }
}

export function fromTaiwanAnalysis(data: TaiwanStockAnalysisResponse): AIAnalysisResult {
  return transformTaiwanAnalysisToAI(data);
}
