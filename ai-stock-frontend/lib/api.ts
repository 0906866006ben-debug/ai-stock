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
  CanslimSummary,
  EntryContext,
  AllocationResult,
  AllocationRequest,
  QuarterlySnapshot,
  QualityWatchHistoryItem,
  DurabilityMetrics,
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

export async function analyzeTW(
  symbol: string,
  options: { includeCanslim?: boolean; includeScreening?: boolean } = {}
): Promise<TaiwanStockAnalysisResponse> {
  const params: Record<string, string | boolean> = {
    symbol: symbol.trim(),
  };
  if (options.includeCanslim) params.include_canslim = true;
  if (options.includeScreening) params.include_screening = true;
  const { data } = await axios.get<TaiwanStockAnalysisResponse>(`${API_BASE}/analyze/tw`, {
    params,
  });
  return data;
}

export async function getTwCanslimSummary(symbol: string): Promise<CanslimSummary> {
  const { data } = await axios.get<CanslimSummary>(`${API_BASE}/tw/canslim-summary`, {
    params: { symbol: symbol.trim() },
  });
  return data;
}

const SCREEN_FULL_CACHE_TTL_MS = 10 * 60 * 1000;
const screenFullCache = new Map<string, { data: CanslimFullResult; cachedAt: number }>();
const screenFullInflight = new Map<string, Promise<CanslimFullResult>>();

function screenFullCacheKey(symbol: string, asOfDate?: string): string {
  const effectiveDate = asOfDate ?? new Date().toISOString().slice(0, 10);
  return `${symbol.trim()}|${effectiveDate}`;
}

export async function getTwScreenFull(
  symbol: string,
  asOfDate?: string
): Promise<CanslimFullResult> {
  const key = screenFullCacheKey(symbol, asOfDate);
  const cached = screenFullCache.get(key);
  if (cached && Date.now() - cached.cachedAt < SCREEN_FULL_CACHE_TTL_MS) return cached.data;
  if (cached) screenFullCache.delete(key);
  const inflight = screenFullInflight.get(key);
  if (inflight) return inflight;

  const params: Record<string, string> = { symbol: symbol.trim() };
  if (asOfDate) params.as_of_date = asOfDate;
  const request = axios
    .get<CanslimFullResult>(`${API_BASE}/tw/screen/full`, { params })
    .then(({ data }) => {
      screenFullCache.set(key, { data, cachedAt: Date.now() });
      return data;
    })
    .finally(() => {
      screenFullInflight.delete(key);
    });
  screenFullInflight.set(key, request);
  return request;
}

export async function getTwScreenQualityBatch(
  symbols: string[],
  options: { concurrency?: number; asOfDate?: string } = {}
): Promise<Array<readonly [string, DurabilityMetrics | null]>> {
  const uniqueSymbols = Array.from(new Set(symbols.map((symbol) => symbol.trim()).filter(Boolean)));
  const concurrency = Math.max(1, Math.floor(options.concurrency ?? 2));
  const results: Array<readonly [string, DurabilityMetrics | null]> = [];
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < uniqueSymbols.length) {
      const symbol = uniqueSymbols[nextIndex++];
      try {
        const full = await getTwScreenFull(symbol, options.asOfDate);
        results.push([symbol, full.durability_metrics ?? null] as const);
      } catch {
        results.push([symbol, null] as const);
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, uniqueSymbols.length) }, () => worker()));
  return results;
}

export async function postTwAllocation(payload: AllocationRequest): Promise<AllocationResult> {
  const { data } = await axios.post<AllocationResult>(`${API_BASE}/tw/allocate`, payload);
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

export async function getQualitySnapshot(quarter?: string): Promise<QuarterlySnapshot> {
  const url = quarter ? `${API_BASE}/tw/quality-watch` : `${API_BASE}/tw/quality-watch/latest`;
  const { data } = await axios.get<QuarterlySnapshot>(url, {
    params: quarter ? { quarter } : undefined,
  });
  return data;
}

export async function listQualityWatchQuarters(): Promise<QualityWatchHistoryItem[]> {
  const { data } = await axios.get<QualityWatchHistoryItem[]>(`${API_BASE}/tw/quality-watch/history`);
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
  CanslimSummary,
  QuarterlySnapshot,
  QualityWatchHistoryItem,
};
