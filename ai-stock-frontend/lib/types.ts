import type { NewsItem } from './api';

export interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Taiwan analysis detail sub-models ─────────────────────────────────────────

export interface RevenueSummary {
  latest_revenue?: string | null;
  yoy_pct?: number | null;
  mom_pct?: number | null;
  available_months: number;
  status: string;
}

export interface ValuationSummary {
  per?: number | null;
  pbr?: number | null;
  dividend_yield?: number | null;
  status: string;
}

export interface InstitutionalSummary {
  foreign_net_5d?: number | null;
  foreign_net_10d?: number | null;
  trust_net_5d?: number | null;
  trust_net_10d?: number | null;
  dealer_net_5d?: number | null;
  direction: string;
  status: string;
}

export interface ChipRiskSummary {
  margin_balance?: number | null;
  short_balance?: number | null;
  lending_balance?: number | null;
  chip_direction: string;
  risk_level: string;
  status: string;
}

export interface CashFlowSummary {
  period?: string | null;
  operating_cash_flow?: number | null;
  investing_cash_flow?: number | null;
  financing_cash_flow?: number | null;
  free_cash_flow?: number | null;
  operating_cf_positive?: boolean | null;
  operating_cf_trend: string;
  status: string;
}

export interface MacroEnvironmentSummary {
  usd_twd?: number | null;
  fed_rate?: number | null;
  us_10y_yield?: number | null;
  gold_price?: number | null;
  oil_wti?: number | null;
  sp500?: number | null;
  nasdaq?: number | null;
  fut_foreign_net_oi?: number | null;
  fut_foreign_net_oi_change?: number | null;
  fut_foreign_direction?: string | null;
  fut_foreign_trend?: string | null;
  status: string;
}

export interface ETFSummary {
  nav?: number | null;
  premium_discount_pct?: number | null;
  dividend_yield?: number | null;
  dividend_frequency?: string | null;
  tracking_index?: string | null;
  status: string;
}

// ── Taiwan stock response ─────────────────────────────────────────────────────

// ── 4-Pillar Analysis Models ──────────────────────────────────────────────────

export interface FundamentalMetrics {
  latest_revenue?: string | null;
  revenue_yoy?: number | null;
  revenue_mom?: number | null;
  eps_latest?: number | null;
  eps_yoy?: number | null;
  pe_ratio?: number | null;
  pb_ratio?: number | null;
  roe?: number | null;
  roa?: number | null;
  gross_margin?: number | null;
  operating_margin?: number | null;
  net_margin?: number | null;
  dividend_yield?: number | null;
  payout_ratio?: number | null;
  debt_ratio?: number | null;
  current_ratio?: number | null;
  quick_ratio?: number | null;
  operating_cf?: string | null;
  free_cf?: string | null;
  cf_trend?: string;
}

type AnalysisScalar = string | number | boolean | null | undefined;
type AnalysisDetail = Record<string, AnalysisScalar>;

export interface ProfitabilityDetail extends AnalysisDetail {
  trend?: string;
  quality?: string;
}

export interface ValuationDetail extends AnalysisDetail {
  level?: string;
}

export interface TechnicalMomentumDetail extends AnalysisDetail {
  rsi?: string | number;
  rsi_signal?: string;
}

export interface TechnicalKeyLevelsDetail extends AnalysisDetail {
  support?: string | number;
  resistance?: string | number;
}

export interface InstitutionalFlowDetail extends AnalysisDetail {
  trend?: string;
}

export interface ChipInstitutionalSentiment {
  foreign?: InstitutionalFlowDetail | null;
  domestic_fund?: InstitutionalFlowDetail | null;
  [key: string]: InstitutionalFlowDetail | AnalysisScalar | null;
}

export interface ChipPositionDetail extends AnalysisDetail {
  overall_trend?: string;
}

export interface NewsHeadlineDetail extends AnalysisDetail {
  title?: string;
  source?: string;
  date?: string;
  published_at?: string;
  url?: string;
}

export interface SentimentAggregateDetail extends AnalysisDetail {
  bullish_count?: number;
  neutral_count?: number;
  bearish_count?: number;
  overall_score?: number;
  trend?: string;
}

export interface NewsCatalystDetail extends AnalysisDetail {
  event?: string;
  date?: string;
}

export interface FundamentalAnalysis {
  summary: string;
  revenue_trend: string;
  profitability?: ProfitabilityDetail | null;
  valuation?: ValuationDetail | null;
  financial_health?: AnalysisDetail | null;
  risks: string[];
  catalysts: string[];
  metrics?: FundamentalMetrics | null;
  confidence: number;
  is_mock: boolean;
}

export interface TechnicalAnalysis {
  summary: string;
  trend: string;
  momentum?: TechnicalMomentumDetail | null;
  volatility?: AnalysisDetail | null;
  key_levels?: TechnicalKeyLevelsDetail | null;
  risks: string[];
  opportunities: string[];
  confidence: number;
  is_mock: boolean;
}

export interface ChipAnalysis {
  summary: string;
  institutional_sentiment?: ChipInstitutionalSentiment | null;
  chip_position?: ChipPositionDetail | null;
  risk_indicators?: AnalysisDetail | null;
  liquidity?: AnalysisDetail | null;
  risks: string[];
  signals: string[];
  confidence: number;
  is_mock: boolean;
}

export interface NewsAnalysis {
  summary: string;
  recent_headlines: NewsHeadlineDetail[];
  sentiment_aggregate?: SentimentAggregateDetail | null;
  key_catalysts: NewsCatalystDetail[];
  macro_impact?: AnalysisDetail | null;
  risks: string[];
  opportunities: string[];
  confidence: number;
  is_mock: boolean;
}

export interface ComprehensiveAnalysis {
  summary: string;
  overall_direction: string;
  confirmation_pillars?: Record<string, string> | null;
  confirmation_score: number;
  conflicts: string[];
  composite_confidence: number;
  target_price: number;
  stop_loss: number;
  timeframe: string;
  conviction_level: string;
  recommendation: string;
  key_risks: string[];
  catalyst_timeline: string[];
  conflict_resolution: string;
  is_mock: boolean;
}

// ── Elite Equity Research Framework ──────────────────────────────────────────

export interface ScenarioPrice {
  target_price: number;
  rationale: string;
  key_risk: string;
  upside_pct?: number | null;
  timeframe: string;
}

export interface SentimentScore {
  score: number;
  stage: string;
  avg_likes_per_post?: number | null;
  avg_comments_per_post?: number | null;
  source: string;
}

export interface AnalystEntry {
  firm: string;
  rating: string;
  target_price?: number | null;
}

export interface AnalystConsensus {
  buy_count: number;
  hold_count: number;
  sell_count: number;
  target_low?: number | null;
  target_median?: number | null;
  target_high?: number | null;
  entries: AnalystEntry[];
}

export interface CatalystRow {
  time_horizon: string;
  event: string;
  data_point: string;
  impact: string;
}

export interface RiskRow {
  risk: string;
  probability_pct: number;
  mitigation: string;
}

export interface CategoryRating {
  category: string;
  label_zh: string;
  stars: number;
}

export interface SourceCitation {
  title: string;
  url?: string | null;
  source: string;
}

export interface EquityResearch {
  // [1] Market Narrative
  social_sentiment: string;
  sentiment_stage: string;
  catalysts: string[];
  institutional_view: string;
  narrative_conclusion: string;
  sentiment_data?: SentimentScore | null;
  analyst_consensus_data?: AnalystConsensus | null;
  catalyst_table?: CatalystRow[] | null;
  risk_table?: RiskRow[] | null;
  category_ratings?: CategoryRating[] | null;
  source_citations?: SourceCitation[] | null;
  // [2] Fundamental Snapshot
  valuation_verdict: string;
  valuation_assumptions: string;
  financial_risks: string[];
  // [3] Technical Snapshot
  technical_verdict: string;
  institutional_positioning: string;
  setup_suitability: string;
  // [4] Scenario Framework
  scenario_bear: ScenarioPrice;
  scenario_base: ScenarioPrice;
  scenario_bull: ScenarioPrice;
  scenario_stretched: ScenarioPrice;
  // [5] Actionable Framework
  entry_zone: string;
  add_zone: string;
  profit_taking: string;
  thesis_break: string;
  key_catalyst: string;
  hidden_risk: string;
  // Meta
  investment_rating: string;
  summary: string;
  confidence: number;
  is_mock: boolean;
}

export interface TaiwanStockAnalysisResponse {
  symbol: string;
  company_name: string;
  market_type: string;
  currency: string;
  current_price: number;
  price_change_percent: number;
  volume: number;
  trend: string;
  confidence: number;
  summary: string;
  risks: string[];
  catalysts: string[];
  recommendation: string;
  recent_news: NewsItem[];
  chart_data: CandlePoint[];
  data_source: string;
  analysis_source: string;
  disclaimer: string;
  analyzed_at: string;
  // Detailed fields
  is_etf: boolean;
  revenue_summary?: RevenueSummary | null;
  valuation_summary?: ValuationSummary | null;
  institutional_summary?: InstitutionalSummary | null;
  chip_risk_summary?: ChipRiskSummary | null;
  cashflow_summary?: CashFlowSummary | null;
  macro_summary?: MacroEnvironmentSummary | null;
  etf_summary?: ETFSummary | null;
  // Phase 2 enrichments
  next_dividend?: DividendEvent | null;
  etf_holdings?: ETFHoldingsResponse | null;
  // Phase 3: 4-pillar comprehensive analysis
  fundamental?: FundamentalAnalysis | null;
  technical?: TechnicalAnalysis | null;
  chip?: ChipAnalysis | null;
  news?: NewsAnalysis | null;
  comprehensive_analysis?: ComprehensiveAnalysis | null;
  // Phase 4: elite equity research framework
  equity_research?: EquityResearch | null;
}

// ── FMP Fundamentals ─────────────────────────────────────────────────────────

export interface AnalystTarget {
  consensus?: string | null;
  high?: string | null;
  low?: string | null;
  median?: string | null;
}

export interface LastEarnings {
  date?: string | null;
  eps_actual?: number | null;
  eps_estimated?: number | null;
}

export interface ESGData {
  environmental?: number | null;
  social?: number | null;
  governance?: number | null;
  total?: number | null;
}

export interface FundamentalsData {
  financial_metrics: Record<string, string>;
  analyst: AnalystTarget;
  next_earnings_date?: string | null;
  last_earnings: LastEarnings;
  esg: ESGData;
}

// ── Competitor / peers ────────────────────────────────────────────────────────

export interface PeerStock {
  symbol: string;
  company_name?: string | null;
  price?: number | null;
  market_cap?: string | null;
  market_cap_fmt?: string | null;
  pe_ratio?: string | null;
  gross_margin?: string | null;
  net_margin?: string | null;
  roe?: string | null;
  ev_ebitda?: string | null;
}

export interface CompetitorResponse {
  symbol: string;
  peers: PeerStock[];
}

// ── Market Overview ───────────────────────────────────────────────────────────

export interface EconomicIndicator {
  name: string;
  label: string;
  value?: number | null;
  date?: string | null;
}

export interface TopStock {
  symbol?: string | null;
  company_name?: string | null;
  price?: number | null;
  market_cap?: number | null;
  sector?: string | null;
  volume?: number | null;
  beta?: number | null;
}

export interface MarketOverviewResponse {
  economic_indicators: EconomicIndicator[];
  top_stocks: TopStock[];
  data_source: string;
}

// ── Search ────────────────────────────────────────────────────────────────────

export interface SearchResult {
  symbol: string;
  name: string;
  exchange: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

// ── TW Stock directory ────────────────────────────────────────────────────────

export interface StockInfo {
  stock_code: string;
  company_name: string;
  market_type: string;
  industry?: string | null;
}

export interface StockListResponse {
  stocks: StockInfo[];
  total: number;
  returned: number;
  data_source: string;
}

// ── TW Price history + indicators ─────────────────────────────────────────────

export interface MACDBundle {
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
}

export interface KDBundle {
  "%K": (number | null)[];
  "%D": (number | null)[];
}

export interface BollingerBandsBundle {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

export interface SupportResistanceBundle {
  support: number[];
  resistance: number[];
}

export interface IndicatorsBundle {
  ma5?: (number | null)[] | null;
  ma20?: (number | null)[] | null;
  ma60?: (number | null)[] | null;
  ma120?: (number | null)[] | null;
  ma240?: (number | null)[] | null;
  rsi?: (number | null)[] | null;
  macd?: MACDBundle | null;
  kd?: KDBundle | null;
  bollinger_bands?: BollingerBandsBundle | null;
  atr?: (number | null)[] | null;
  support_resistance?: SupportResistanceBundle | null;
  volume?: number[] | null;
}

export interface PriceHistoryResponse {
  stock_code: string;
  range: string;
  candles: CandlePoint[];
  is_mock: boolean;
  indicators?: IndicatorsBundle | null;
}

// ── TW Calendar ───────────────────────────────────────────────────────────────

export interface DividendEvent {
  stock_code: string;
  company_name?: string | null;
  ex_date?: string | null;
  payment_date?: string | null;
  announcement_date?: string | null;
  cash_per_share?: number | null;
  stock_per_share?: number | null;
  type: 'cash' | 'stock' | 'mixed' | string;
}

export interface DividendCalendarResponse {
  events: DividendEvent[];
  data_source: string;
}

export interface EarningsEvent {
  stock_code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  deadline: string;
  actual_filing_date?: string | null;
  eps?: number | null;
  is_upcoming: boolean;
}

export interface EarningsCalendarResponse {
  events: EarningsEvent[];
  data_source: string;
}

// ── ETF Holdings ──────────────────────────────────────────────────────────────

export interface ETFHolding {
  stock_code?: string | null;
  company_name: string;
  weight_pct?: number | null;
  shares?: number | null;
}

export interface ETFSectorWeight {
  sector: string;
  weight_pct: number;
}

export interface ETFHoldingsResponse {
  symbol: string;
  fund_name?: string | null;
  total_constituents?: number | null;
  last_updated?: string | null;
  holdings: ETFHolding[];
  sector_weights: ETFSectorWeight[];
  status: 'live' | 'mock' | 'unsupported' | string;
}

// ── External news ─────────────────────────────────────────────────────────────

export interface ExternalNewsItem {
  title: string;
  url?: string | null;
  source?: string | null;
  published_at?: string | null;
  category: string;
}

export interface ExternalNewsResponse {
  categories: Record<string, ExternalNewsItem[]>;
  total: number;
  status: string;
}

// ── CANSLIM full grading (/tw/screen/full → CanslimFullResult) ────────────────

export type CanslimFactor = 'C' | 'A' | 'N' | 'S' | 'L' | 'I' | 'M';
export type PillarStatus =
  | 'Pass'
  | 'Weak'
  | 'Fail'
  | 'AI_Review_Required'
  | 'Neutral'
  | 'Insufficient_Data';
export type CanslimGrade = 'S' | 'A' | 'B' | 'C' | 'D';
export type CanslimPassStatus = 'PASS' | 'WATCHLIST' | 'FAIL' | 'INSUFFICIENT_DATA';
export type CanslimLevel = 'HIGH' | 'MEDIUM' | 'LOW';
export type StructureStatus = 'intact' | 'weakening' | 'invalidated' | 'profit_watch';

export interface CanslimFactorScore {
  factor: CanslimFactor;
  status: PillarStatus;
  score: number | null;
  reason: string;
  data_used: string[];
  missing_data: string[];
}

export interface CanslimFullResult {
  stock_id: string;
  as_of_date: string;
  overall_score: number;
  grade: CanslimGrade;
  pass_status: CanslimPassStatus;
  confidence: CanslimLevel;
  risk_level: CanslimLevel;
  per_factor_scores: CanslimFactorScore[];
  positive_reasons: string[];
  negative_reasons: string[];
  missing_data: string[];
  invalidation_signals: string[];
  observation_conditions: string[];
  suggested_strategy: string;
  data_quality: CanslimLevel;
  is_mock_or_fallback_data: boolean;
  // Embedded ScreeningResult carries the swing structure/exit fields.
  screening_result?: {
    market_regime?: 'risk_on' | 'risk_off' | 'severe' | 'unknown';
    structure_status?: StructureStatus;
    exit_signals?: string[];
    data_warnings?: string[];
  } | null;
}

// ── Entry context (/tw/entry-context → Task 1A timing/价位 conditions) ─────────

export type Expensiveness = '偏便宜' | '合理' | '偏貴' | 'unknown';
export type EntryStructureStatus = 'intact' | 'weakening' | 'invalidated' | 'unknown';

export interface EntrySupportLevel {
  kind: string;            // dynamic_ma60 | dynamic_ma200 | structural_box_low | structural_neckline
  price: number;
  pct_below: number;       // (price/current - 1), negative = below current
}

export interface EntryContext {
  symbol: string;
  current_price: number | null;
  extension: {
    pct_from_ma20?: number;
    pct_from_ma60?: number;
    pct_from_52w_high?: number;
    label?: string;
  };
  valuation: {
    pe?: number;
    pe_percentile?: number;
    pb?: number;
    pb_percentile?: number;
    label?: string;
  };
  expensiveness: Expensiveness;
  supports: EntrySupportLevel[];
  confluence_zones: { low: number; high: number; pct_below: number; kinds: string[] }[];
  structure_status: EntryStructureStatus;
  add_on_context: {
    structure_ok?: boolean;
    at_support?: boolean;
    volume_confirmed?: boolean | null;
    note?: string;
  };
  data_quality: { adjusted_available?: boolean; dividend_events?: number };
  missing: string[];
}

// ── Portfolio (client-side) ───────────────────────────────────────────────────

export interface Position {
  id: string;
  stock_code: string;
  company_name: string;
  lots: number;
  cost_per_share: number;
  purchase_date: string;
  current_price?: number;
  current_price_updated_at?: string;
}
