import axios from 'axios';

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
}

export async function analyzeStock(symbol: string): Promise<StockAnalysisResponse> {
  const { data } = await axios.get<StockAnalysisResponse>(`${API_BASE}/analyze`, {
    params: { symbol: symbol.toUpperCase().trim() },
  });
  return data;
}

export async function checkHealth(): Promise<{ status: string; version: string }> {
  const { data } = await axios.get(`${API_BASE}/health`);
  return data;
}
