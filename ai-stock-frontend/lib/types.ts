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

export interface MacroEnvironmentSummary {
  usd_twd?: number | null;
  fed_rate?: number | null;
  us_10y_yield?: number | null;
  gold_price?: number | null;
  oil_wti?: number | null;
  sp500?: number | null;
  nasdaq?: number | null;
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
  macro_summary?: MacroEnvironmentSummary | null;
  etf_summary?: ETFSummary | null;
  // Phase 2 enrichments
  next_dividend?: DividendEvent | null;
  etf_holdings?: ETFHoldingsResponse | null;
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

export interface IndicatorsBundle {
  ma5?: (number | null)[] | null;
  ma20?: (number | null)[] | null;
  ma60?: (number | null)[] | null;
  rsi?: (number | null)[] | null;
  macd?: MACDBundle | null;
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

// ── Portfolio (client-side) ───────────────────────────────────────────────────

export interface Position {
  id: string;
  stock_code: string;
  company_name: string;
  lots: number;
  cost_per_share: number;
  purchase_date: string;
  current_price?: number;
}
