import { analyzeTW, getTwAgentAnalysis, getTwAIAnalysisContract } from '@/lib/api';
import type { TaiwanStockAnalysisResponse } from '@/lib/types';
import type { AIAnalysisResult, ReportSection } from '@/types/aiAnalysis';
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
    return fetchMultiAgentOverlay(symbol, FIXTURES[symbol]);
  }

  try {
    const twData = await analyzeTW(symbol);
    const withV2 = await fetchAIAnalysisV2Overlay(symbol, transformTaiwanAnalysisToAI(twData));
    return fetchMultiAgentOverlay(symbol, withV2);
  } catch {
    return getMockAIAnalysis(symbol);
  }
}

export function fromTaiwanAnalysis(data: TaiwanStockAnalysisResponse): AIAnalysisResult {
  return transformTaiwanAnalysisToAI(data);
}

export async function fetchAIAnalysisV2Overlay(symbol: string, base: AIAnalysisResult): Promise<AIAnalysisResult> {
  try {
    const contract = await getTwAIAnalysisContract(symbol);
    return mergeV2Overlay(base, contract);
  } catch {
    return base;
  }
}

export async function fetchMultiAgentOverlay(symbol: string, base: AIAnalysisResult): Promise<AIAnalysisResult> {
  try {
    const response = await getTwAgentAnalysis(symbol);
    return {
      ...base,
      multi_agent_analysis: response.analysis,
      data_quality: response.is_mock ? 'mock' : base.data_quality,
      models_used: Array.from(new Set([
        ...base.models_used,
        ...response.analysis.agents
          .filter((agent) => agent.status === 'completed')
          .map((agent) => agent.name),
      ])),
    };
  } catch {
    return base;
  }
}

function mergeV2Overlay(base: AIAnalysisResult, contract: Partial<AIAnalysisResult>): AIAnalysisResult {
  if (!contract.v2_quant_analysis) return base;

  const quantSection = contract.report_sections?.find((section): section is ReportSection => section.key === 'quant_v2');
  const reportSections = quantSection && !base.report_sections.some((section) => section.key === 'quant_v2')
    ? [...base.report_sections, quantSection]
    : base.report_sections;

  return {
    ...base,
    v2_quant_analysis: contract.v2_quant_analysis,
    report_sections: reportSections,
    models_used: Array.from(new Set([...base.models_used, ...(contract.models_used ?? [])])),
  };
}
