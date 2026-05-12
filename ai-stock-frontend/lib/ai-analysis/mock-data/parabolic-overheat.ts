import type { AIAnalysisResult } from '@/types/aiAnalysis';
import { tsmc2330Analysis } from './tsmc-2330';

export const parabolicOverheatAnalysis: AIAnalysisResult = {
  ...tsmc2330Analysis,
  symbol: '9991',
  symbol_name: '極端噴發範例',
  current_price: 188,
  price_change: 15,
  price_change_pct: 8.67,
  overall_direction: 'neutral_bearish',
  cross_horizon_state: 'distribution_warning',
  overall_scores: {
    signal: 88,
    confidence: 35,
    risk: 92,
    confidence_cap_reason: '極端乖離狀態下 v1 規則限制最高信心',
  },
  one_line_summary: '攻擊訊號很強，但追價風險極高；這不是加速進場點，而是檢查獲利了結條件的區域。',
  horizons: {
    ...tsmc2330Analysis.horizons,
    short_term: {
      ...tsmc2330Analysis.horizons.short_term,
      technical_state: 'parabolic_overheat',
      state_label_zh: '極端噴發態',
      direction: 'neutral_bearish',
      scores: { signal: 90, confidence: 34, risk: 94, confidence_cap_reason: '短線過熱造成信心上限' },
      invalidation_conditions: [
        {
          description: '跌破前一日低點且量增，噴發段落結束',
          trigger_expression: 'close < prior_low AND volume > vma20 * 1.3',
          monitored_fields: ['close', 'prior_low', 'volume', 'vma20'],
          severity: 'hard',
        },
      ],
    },
  },
  bullish_scenario: {
    ...tsmc2330Analysis.bullish_scenario,
    label: '續強但不追價劇本',
    action_if_triggered: '只適合已有部位用移動停利管理，不建議新倉追高。',
  },
  bearish_scenario: {
    ...tsmc2330Analysis.bearish_scenario,
    label: '過熱降風險劇本',
    action_if_triggered: '觸發後優先鎖定獲利，等待乖離修正。',
  },
  evidence_ledger: [
    {
      id: 'overheat-distance',
      source: 'technical',
      direction: 'bearish',
      factor_category: 'VOLATILITY',
      title: '短線乖離過大',
      detail: '收盤距 MA20 超過 18%，追價風險進入高檔區。',
      weight: -9,
    },
    ...tsmc2330Analysis.evidence_ledger.slice(0, 6),
  ],
  structure_panel: {
    ...tsmc2330Analysis.structure_panel,
    wyckoff_phase: 'distribution_a',
    ma_compression_ratio: 0.112,
    is_compressed: false,
    utad_detected: { date: '2026-05-11', confidence: 0.62 },
  },
  data_quality: 'mock',
  data_quality_score: 52,
  disposition_status: 'attention',
};
