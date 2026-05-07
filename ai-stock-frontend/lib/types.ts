import type { NewsItem } from './api';

export interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
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
}
