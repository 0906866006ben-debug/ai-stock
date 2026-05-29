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
  key: 'narrative' | 'fundamentals' | 'technical_chips' | 'scenarios' | 'rating' | 'quant_v2';
  title: string;
  icon: string;
  preview: string;
  body_markdown: string;
}

export type DecimalLike = number | string;

export interface V2FundamentalGate {
  status: 'pass' | 'fail' | 'unknown';
  passed: boolean;
  score: number;
  failed_rules: string[];
  missing_fields: string[];
  warnings: string[];
}

export interface V2TimeBoxProjection {
  ma_window: number;
  status: 'ready' | 'insufficient_data';
  p_crit?: DecimalLike | null;
  projection_date?: string | null;
  deduction_min?: DecimalLike | null;
  deduction_max?: DecimalLike | null;
  current_close: DecimalLike;
  distance_to_p_crit_pct?: DecimalLike | null;
  ma_acceleration_flag: boolean;
  warning?: string | null;
}

export interface V2VolumeProfile {
  status: 'ready' | 'insufficient_data';
  lookback_days: number;
  poc_price?: DecimalLike | null;
  vah_price?: DecimalLike | null;
  val_price?: DecimalLike | null;
  poc_distance_pct?: DecimalLike | null;
  poc_breakdown_flag: boolean;
  bins_used: number;
  value_area_pct: DecimalLike;
}

export interface V2TwoBReversal {
  status: 'confirmed' | 'watch' | 'none' | 'insufficient_data';
  confirmed: boolean;
  prior_low_l1?: DecimalLike | null;
  false_break_low_l2?: DecimalLike | null;
  reclaim_days?: number | null;
  bias_120_pct?: DecimalLike | null;
  reasons: string[];
}

export interface V2RiskExecution {
  take_profit_price?: DecimalLike | null;
  stop_loss_price?: DecimalLike | null;
  rr_ratio?: DecimalLike | null;
  rr_pass: boolean;
  kelly_fraction: DecimalLike;
  position_cap: DecimalLike;
  forced_exit: boolean;
  forced_exit_reason?: string | null;
  bottom_line_fields: string[];
}

export interface V2QuantAnalysisResult {
  version: string;
  fundamental_gate: V2FundamentalGate;
  time_boxes: Record<string, V2TimeBoxProjection>;
  volume_profile: V2VolumeProfile;
  two_b_reversal: V2TwoBReversal;
  risk_execution: V2RiskExecution;
  implemented_modules: string[];
  missing_data_fields: string[];
  hypothesis_ids: string[];
}

export type AgentDataStatus = 'available' | 'partial' | 'missing' | 'stale';
export type AgentConfidence = 'High' | 'Medium' | 'Low';
export type AgentFinalStatus = 'Strong' | 'Neutral' | 'Weak' | 'Insufficient_Data';

export interface AgentEvidencePack {
  id: string;
  label: string;
  source: 'FinMind' | 'Backend' | 'Yahoo' | 'Derived';
  status: AgentDataStatus;
  latest_date?: string | null;
  summary: string;
  key_values: Array<{
    label: string;
    value: string;
  }>;
  warnings: string[];
}

export interface GeminiStructuredInsight {
  key_points: string[];
  conflicts: string[];
  missing_data: string[];
  coverage_notes: string[];
}

export interface ClaudeFinalReview {
  status: AgentFinalStatus;
  confidence: AgentConfidence;
  conclusion: string;
  supporting_evidence: string[];
  key_risks: string[];
  conflicting_signals: string[];
  data_limitations: string[];
  manual_review_required: string[];
}

export interface MultiAgentAnalysis {
  pipeline_version: string;
  agents: Array<{
    name: 'FinMind Agent' | 'Gemini Agent' | 'Claude Agent';
    role: string;
    status: 'completed' | 'fallback' | 'pending' | 'error';
  }>;
  evidence_packs: AgentEvidencePack[];
  gemini_structured: GeminiStructuredInsight;
  claude_final: ClaudeFinalReview;
}

export interface AgentAnalysisResponse {
  symbol: string;
  analysis_date: string;
  is_mock: boolean;
  data_warnings: string[];
  analysis: MultiAgentAnalysis;
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
  v2_quant_analysis?: V2QuantAnalysisResult;
  multi_agent_analysis?: MultiAgentAnalysis;
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
