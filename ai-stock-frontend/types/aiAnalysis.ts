// Direction and state contracts for the AI analysis decision interface.
export type Direction =
  | 'bullish'
  | 'neutral_bullish'
  | 'neutral'
  | 'neutral_bearish'
  | 'bearish';

export type Horizon = 'short_term' | 'swing' | 'long_term';

export type CrossHorizonState =
  | 'aligned_bullish'
  | 'aligned_bearish'
  | 'bull_pullback_in_uptrend'
  | 'dead_cat_bounce'
  | 'reversal_forming'
  | 'distribution_warning'
  | 'triple_resonance_confluence'
  | 'mixed_uncertain';

export type TechnicalState =
  | 'parabolic_overheat'
  | 'strong_uptrend'
  | 'steady_uptrend'
  | 'high_level_distribution'
  | 'early_weakening'
  | 'tight_consolidation'
  | 'early_strengthening'
  | 'weak_rebound'
  | 'downtrend_continuation'
  | 'selling_climax'
  | 'mixed_signals'
  | 'data_insufficient'
  | 'disposition_suspended';

export type DowTrendStructure =
  | 'bullish_intact'
  | 'bullish_at_risk'
  | 'bos_down'
  | 'bearish_intact'
  | 'bearish_at_risk'
  | 'bos_up'
  | 'undefined';

export type WyckoffPhase =
  | 'accumulation_a'
  | 'accumulation_b'
  | 'accumulation_c'
  | 'accumulation_d'
  | 'accumulation_e'
  | 'markup'
  | 'distribution_a'
  | 'distribution_b'
  | 'distribution_c'
  | 'distribution_d'
  | 'distribution_e'
  | 'markdown'
  | 'unclear';

export type FactorCategory =
  | 'PRICE_VS_MA'
  | 'MA_GEOMETRY'
  | 'VOLUME_QUALITY'
  | 'STRUCTURE'
  | 'MOMENTUM'
  | 'VOLATILITY'
  | 'CHIP_FLOW'
  | 'BREAKOUT_QUALITY'
  | 'NEWS_CATALYST';

export type EvidenceSource = 'technical' | 'chip' | 'fundamental' | 'news';
export type EvidenceDirection = 'bullish' | 'bearish' | 'neutral';
export type DataQuality = 'live' | 'delayed' | 'estimated' | 'mock' | 'fallback';
export type DispositionStatus = 'normal' | 'attention' | 'stage_1' | 'stage_2';

export interface ThreeAxisScore {
  signal: number;
  confidence: number;
  risk: number;
  confidence_cap_reason?: string;
}

export interface FactorVote {
  category: FactorCategory;
  direction: EvidenceDirection;
  strength: number;
  evidence_text: string;
}

export interface ReasonTrace {
  reason_text: string;
  source_field: string;
  timestamp: string;
  calculation: string;
  calculation_value: string;
}

export interface InvalidationCondition {
  description: string;
  trigger_expression: string;
  monitored_fields: string[];
  severity: 'soft' | 'hard';
}

export interface HorizonView {
  horizon: Horizon;
  technical_state: TechnicalState;
  state_label_zh: string;
  state_detail: string;
  direction: Direction;
  factor_votes: FactorVote[];
  categories_in_agreement: FactorCategory[];
  dow_structure: DowTrendStructure;
  wyckoff_phase: WyckoffPhase;
  scores: ThreeAxisScore;
  invalidation_conditions: InvalidationCondition[];
  reasons: ReasonTrace[];
}

export interface ScenarioCondition {
  condition_text: string;
  monitored_fields: string[];
  trigger_expression: string;
}

export interface Scenario {
  direction: 'bullish' | 'bearish';
  label: string;
  conditions: ScenarioCondition[];
  action_if_triggered: string;
  scope_horizons: Horizon[];
}

export interface EvidenceItem {
  id: string;
  source: EvidenceSource;
  direction: EvidenceDirection;
  factor_category?: FactorCategory;
  title: string;
  detail: string;
  weight: number;
  trace?: ReasonTrace;
  backtest_hit_rate?: number;
  backtest_sample_size?: number;
}

export interface KouDiPeriod {
  start_day_offset: number;
  end_day_offset: number;
  direction: 'upward' | 'downward';
  intensity: number;
}

export interface KouDiAnalysis {
  ma_window: number;
  current_ma_value: number;
  current_close: number;
  expected_direction_next_5d: 'up' | 'flat' | 'down';
  expected_slope_change_pct: number;
  upward_pressure_periods: KouDiPeriod[];
  downward_pressure_periods: KouDiPeriod[];
  critical_kou_di_points: Array<{
    day_offset: number;
    distance_pct: number;
    note: string;
  }>;
}

export interface SwingPivot {
  date: string;
  type: 'high' | 'low';
  price: number;
  is_confirmed: boolean;
}

export interface StructurePanelData {
  dow_structure: DowTrendStructure;
  wyckoff_phase: WyckoffPhase;
  recent_pivots: SwingPivot[];
  spring_detected?: {
    date: string;
    level: 'light' | 'standard' | 'strong';
  };
  utad_detected?: {
    date: string;
    confidence: number;
  };
  kou_di_ma20: KouDiAnalysis;
  kou_di_ma60: KouDiAnalysis;
  kou_di_ma120?: KouDiAnalysis;
  ma_compression_ratio: number;
  is_compressed: boolean;
}

export interface ReportSection {
  key: 'narrative' | 'fundamentals' | 'technical_chips' | 'scenarios' | 'rating';
  title: string;
  icon: string;
  preview: string;
  body_markdown: string;
}

export interface AIAnalysisResult {
  symbol: string;
  symbol_name: string;
  sector_tag: string;
  market_cap_bucket: 'large' | 'mid' | 'small' | 'micro';
  current_price: number;
  price_change: number;
  price_change_pct: number;
  overall_direction: Direction;
  cross_horizon_state: CrossHorizonState;
  overall_scores: ThreeAxisScore;
  one_line_summary: string;
  horizons: {
    short_term: HorizonView;
    swing: HorizonView;
    long_term: HorizonView;
  };
  bullish_scenario: Scenario;
  bearish_scenario: Scenario;
  evidence_ledger: EvidenceItem[];
  structure_panel: StructurePanelData;
  report_sections: ReportSection[];
  data_sources: string[];
  models_used: string[];
  data_quality: DataQuality;
  data_quality_score: number;
  disposition_status: DispositionStatus;
  analyzed_at: string;
  next_update_at: string;
  rule_set_version: string;
  is_v1_hypothesis: boolean;
}
