import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { tsmc2330Analysis } from './tsmc-2330';

export const vcpConsolidationAnalysis: AIAnalysisResult = {
  ...tsmc2330Analysis,
  symbol: '9992',
  symbol_name: 'VCP 壓縮範例',
  current_price: 62.4,
  price_change: 0.2,
  price_change_pct: 0.32,
  overall_direction: 'neutral_bullish',
  cross_horizon_state: 'reversal_forming',
  overall_scores: {
    signal: 58,
    confidence: 71,
    risk: 36,
  },
  one_line_summary: '價格進入窄幅壓縮，方向尚未確認；重點不是預測方向，而是等待放量突破或跌破。',
  horizons: {
    short_term: {
      ...tsmc2330Analysis.horizons.short_term,
      technical_state: 'tight_consolidation',
      state_label_zh: '窄幅整理態',
      direction: 'neutral',
      scores: { signal: 52, confidence: 72, risk: 32 },
    },
    swing: {
      ...tsmc2330Analysis.horizons.swing,
      technical_state: 'tight_consolidation',
      state_label_zh: '窄幅整理態',
      direction: 'neutral_bullish',
      scores: { signal: 60, confidence: 73, risk: 35 },
    },
    long_term: {
      ...tsmc2330Analysis.horizons.long_term,
      technical_state: 'steady_uptrend',
      state_label_zh: '穩健增長態',
      direction: 'neutral_bullish',
      scores: { signal: 64, confidence: 70, risk: 40 },
    },
  },
  evidence_ledger: [
    {
      id: 'vcp-compression',
      source: 'technical',
      direction: 'neutral',
      factor_category: 'VOLATILITY',
      title: '均線壓縮接近臨界',
      detail: 'MA5-MA60 壓縮度約 2.1%，能量收斂但方向未決。',
      weight: 5,
    },
    ...tsmc2330Analysis.evidence_ledger.slice(1, 7),
  ],
  structure_panel: {
    ...tsmc2330Analysis.structure_panel,
    wyckoff_phase: 'accumulation_d',
    ma_compression_ratio: 0.021,
    is_compressed: true,
  },
  report_sections: tsmc2330Analysis.report_sections.map((section) => ({
    ...section,
    preview: section.key === 'technical_chips'
      ? '壓縮度低於 3%，等待量價確認突破方向。'
      : section.preview,
  })),
  data_quality: 'mock',
  data_quality_score: 76,
};
