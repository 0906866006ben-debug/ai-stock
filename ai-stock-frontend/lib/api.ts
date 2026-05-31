import axios from 'axios';
import type { AgentAnalysisResponse, AIAnalysisResult } from '@/types/aiAnalysis';
import type {
  TaiwanStockAnalysisResponse,
  FundamentalsData,
  CompetitorResponse,
  MarketOverviewResponse,
  SearchResponse,
  StockListResponse,
  PriceHistoryResponse,
  ExternalNewsResponse,
  DividendCalendarResponse,
  EarningsCalendarResponse,
  ETFHoldingsResponse,
  CandlePoint,
  CanslimFullResult,
  EntryContext,
} from './types';

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim().replace(/\/+$/, '');

export interface ChartPoint {
  time: string;
  value: number;
}

export interface NewsItem {
  title: string;
  published_at: string;
  source: string;
  url?: string | null;
}

export interface StockAnalysisResponse {
  symbol: string;
  company_name: string;
  current_price: number;
  price_change_percent: number;
  trend: string;
  confidence: number;
  summary: string;
  risks: string[];
  catalysts: string[];
  recommendation: string;
  recent_news: NewsItem[];
  financial_summary: Record<string, string>;
  chart_data: CandlePoint[];
  data_source: string;
  fundamentals?: FundamentalsData | null;
}

export async function analyzeStock(symbol: string): Promise<StockAnalysisResponse> {
  const { data } = await axios.get<StockAnalysisResponse>(`${API_BASE}/analyze`, {
    params: { symbol: symbol.toUpperCase().trim() },
  });
  return data;
}

export async function analyzeTW(symbol: string): Promise<TaiwanStockAnalysisResponse> {
  const { data } = await axios.get<TaiwanStockAnalysisResponse>(`${API_BASE}/analyze/tw`, {
    params: { symbol: symbol.trim() },
  });
  return data;
}

export async function getTwScreenFull(
  symbol: string,
  asOfDate?: string
): Promise<CanslimFullResult> {
  const params: Record<string, string> = { symbol: symbol.trim() };
  if (asOfDate) params.as_of_date = asOfDate;
  const { data } = await axios.get<CanslimFullResult>(`${API_BASE}/tw/screen/full`, { params });
  return data;
}

export async function getTwEntryContext(symbol: string): Promise<EntryContext> {
  const { data } = await axios.get<EntryContext>(`${API_BASE}/tw/entry-context`, {
    params: { symbol: symbol.trim() },
  });
  return data;
}

export async function getTwAIAnalysisContract(symbol: string): Promise<Partial<AIAnalysisResult>> {
  const { data } = await axios.get<Partial<AIAnalysisResult>>(`${API_BASE}/ai-analysis/tw`, {
    params: { symbol: symbol.trim() },
  });
  return data;
}

export async function getTwAgentAnalysis(symbol: string): Promise<AgentAnalysisResponse> {
  const { data } = await axios.get<AgentAnalysisResponse>(`${API_BASE}/tw/agent-analysis`, {
    params: { symbol: symbol.trim() },
  });
  return data;
}

export async function checkHealth(): Promise<{ status: string; version: string }> {
  const { data } = await axios.get(`${API_BASE}/health`);
  return data;
}

export async function getMarketOverview(): Promise<MarketOverviewResponse> {
  const { data } = await axios.get<MarketOverviewResponse>(`${API_BASE}/market`);
  return data;
}

export async function getCompetitors(symbol: string): Promise<CompetitorResponse> {
  const { data } = await axios.get<CompetitorResponse>(`${API_BASE}/compare`, {
    params: { symbol: symbol.toUpperCase().trim() },
  });
  return data;
}

export async function searchSymbols(query: string): Promise<SearchResponse> {
  const { data } = await axios.get<SearchResponse>(`${API_BASE}/search`, {
    params: { query: query.trim() },
  });
  return data;
}

// ── Taiwan-specific APIs ──────────────────────────────────────────────────────

export async function getTwStocks(params: {
  q?: string;
  stock_type?: string;
  industry?: string;
  limit?: number;
}): Promise<StockListResponse> {
  const { data } = await axios.get<StockListResponse>(`${API_BASE}/tw/stocks`, { params });
  return data;
}

export async function getTwPriceHistory(
  stock_code: string,
  range: 'D' | 'W' | 'M' | 'Y' = 'D',
  include_indicators?: string
): Promise<PriceHistoryResponse> {
  const params: Record<string, string> = { stock_code: stock_code.trim(), range };
  if (include_indicators) params.include_indicators = include_indicators;
  const { data } = await axios.get<PriceHistoryResponse>(`${API_BASE}/tw/price-history`, { params });
  return data;
}

export async function getUsPriceHistory(
  symbol: string,
  range: string = 'D',
  include_indicators?: string
): Promise<PriceHistoryResponse> {
  const params: Record<string, string> = { symbol: symbol.trim().toUpperCase(), range };
  if (include_indicators) params.include_indicators = include_indicators;
  const { data } = await axios.get<PriceHistoryResponse>(`${API_BASE}/price-history`, { params });
  return data;
}

// ── Phase 2: calendar + ETF holdings ──────────────────────────────────────────

export async function getDividendCalendar(params: {
  symbol?: string;
  start?: string;
  end?: string;
}): Promise<DividendCalendarResponse> {
  const { data } = await axios.get<DividendCalendarResponse>(
    `${API_BASE}/tw/calendar/dividends`,
    { params }
  );
  return data;
}

export async function getEarningsCalendar(symbol?: string): Promise<EarningsCalendarResponse> {
  const { data } = await axios.get<EarningsCalendarResponse>(
    `${API_BASE}/tw/calendar/earnings`,
    { params: symbol ? { symbol } : {} }
  );
  return data;
}

export async function getETFHoldings(symbol: string): Promise<ETFHoldingsResponse> {
  const { data } = await axios.get<ETFHoldingsResponse>(
    `${API_BASE}/tw/etf/holdings`,
    { params: { symbol: symbol.trim() } }
  );
  return data;
}

export async function getExternalNews(category?: string): Promise<ExternalNewsResponse> {
  const { data } = await axios.get<ExternalNewsResponse>(`${API_BASE}/tw/external-news`, {
    params: category ? { category } : {},
  });
  return data;
}

export async function syncTelegramWatchlist(
  action: 'add' | 'remove',
  stock_code: string,
  stock_name?: string
): Promise<{ status: string; message: string }> {
  const { data } = await axios.post(`${API_BASE}/tw/telegram/watchlist/sync`, {
    action,
    stock_code: stock_code.trim(),
    stock_name: stock_name ?? null,
  });
  return data;
}

export type {
  TaiwanStockAnalysisResponse,
  FundamentalsData,
  CompetitorResponse,
  MarketOverviewResponse,
  SearchResponse,
  StockListResponse,
  PriceHistoryResponse,
  ExternalNewsResponse,
  DividendCalendarResponse,
  EarningsCalendarResponse,
  ETFHoldingsResponse,
  CanslimFullResult,
};
