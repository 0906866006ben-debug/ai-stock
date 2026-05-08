import axios from 'axios';
import type {
  TaiwanStockAnalysisResponse,
  FundamentalsData,
  CompetitorResponse,
  MarketOverviewResponse,
  SearchResponse,
  StockListResponse,
  PriceHistoryResponse,
  ExternalNewsResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
  chart_data: ChartPoint[];
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
  range: '1D' | '5D' | '1W' | '1M' | '1Y' = '1M'
): Promise<PriceHistoryResponse> {
  const { data } = await axios.get<PriceHistoryResponse>(`${API_BASE}/tw/price-history`, {
    params: { stock_code: stock_code.trim(), range },
  });
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
};
