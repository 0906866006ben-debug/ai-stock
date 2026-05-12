import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { tsmc2330Analysis } from './tsmc-2330';

export const springEventAnalysis: AIAnalysisResult = {
  ...tsmc2330Analysis,
  symbol: '9993',
  symbol_name: 'Spring 訊號範例',
  current_price: 41.8,
  price_change: 1.1,
  price_change_pct: 2.7,
  overall_direction: 'neutral_bullish',
  cross_horizon_state: 'reversal_forming',
  overall_scores: {
    signal: 66,
    confidence: 68,
    risk: 44,
  },
  one_line_summary: '疑似 Spring 後收回區間，屬於早期轉強訊號；仍要等波段結構確認。',
  horizons: {
    short_term: {
      ...tsmc2330Analysis.horizons.short_term,
      technical_state: 'early_strengthening',
      state_label_zh: '早期轉強態',
      direction: 'neutral_bullish',
      scores: { signal: 68, confidence: 65, risk: 48 },
    },
    swing: {
      ...tsmc2330Analysis.horizons.swing,
      technical_state: 'early_strengthening',
      state_label_zh: '早期轉強態',
      direction: 'neutral_bullish',
      scores: { signal: 64, confidence: 69, risk: 42 },
    },
    long_term: {
      ...tsmc2330Analysis.horizons.long_term,
      technical_state: 'weak_rebound',
      state_label_zh: '弱勢反彈態',
      direction: 'neutral',
      scores: { signal: 52, confidence: 63, risk: 50 },
    },
  },
  evidence_ledger: [
    {
      id: 'spring-reclaim',
      source: 'technical',
      direction: 'bullish',
      factor_category: 'STRUCTURE',
      title: 'Spring 後收回區間',
      detail: '價格一度跌破區間低點後快速收回，疑似測試供給成功。',
      weight: 7,
    },
    ...tsmc2330Analysis.evidence_ledger.slice(0, 6),
  ],
  structure_panel: {
    ...tsmc2330Analysis.structure_panel,
    dow_structure: 'bearish_at_risk',
    wyckoff_phase: 'accumulation_c',
    spring_detected: { date: '2026-05-08', level: 'standard' },
    ma_compression_ratio: 0.036,
    is_compressed: false,
  },
  data_quality: 'mock',
  data_quality_score: 68,
};
