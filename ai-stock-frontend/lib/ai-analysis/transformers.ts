import type { TaiwanStockAnalysisResponse } from '@/lib/types';
import type {
  AIAnalysisResult,
  Direction,
  EvidenceDirection,
  EvidenceItem,
  FactorCategory,
  Horizon,
  HorizonView,
  KouDiAnalysis,
  ReasonTrace,
  TechnicalState,
} from '@/types/aiAnalysis';
import { TECHNICAL_STATE_LABELS } from './i18n';

function clamp(value: number, min = 0, max = 100): number {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function normalizedConfidence(confidence: number): number {
  return clamp(confidence <= 1 ? confidence * 100 : confidence);
}

function directionFromTrend(trend: string, pct: number): Direction {
  if (trend.includes('漲') || pct >= 2) return 'bullish';
  if (trend.includes('跌') || pct <= -2) return 'bearish';
  if (pct > 0.3) return 'neutral_bullish';
  if (pct < -0.3) return 'neutral_bearish';
  return 'neutral';
}

function evidenceDirectionFromWeight(weight: number): EvidenceDirection {
  if (weight > 1) return 'bullish';
  if (weight < -1) return 'bearish';
  return 'neutral';
}

function technicalStateFromDirection(direction: Direction, risk: number): TechnicalState {
  if (risk >= 85 && (direction === 'bullish' || direction === 'neutral_bullish')) return 'parabolic_overheat';
  if (direction === 'bullish') return 'strong_uptrend';
  if (direction === 'neutral_bullish') return 'steady_uptrend';
  if (direction === 'neutral_bearish') return 'early_weakening';
  if (direction === 'bearish') return 'downtrend_continuation';
  return 'mixed_signals';
}

function reason(
  reason_text: string,
  source_field: string,
  calculation: string,
  calculation_value: string,
  timestamp: string
): ReasonTrace {
  return { reason_text, source_field, calculation, calculation_value, timestamp };
}

function buildKouDi(window: number, currentPrice: number, bias = 0): KouDiAnalysis {
  const ma = currentPrice * (1 - (window === 20 ? 0.025 : window === 60 ? 0.065 : 0.11) + bias);
  const expected = ma < currentPrice ? 'up' : ma > currentPrice * 1.01 ? 'down' : 'flat';
  return {
    ma_window: window,
    current_ma_value: Number(ma.toFixed(2)),
    current_close: currentPrice,
    expected_direction_next_5d: expected,
    expected_slope_change_pct: Number((((currentPrice - ma) / Math.max(ma, 1)) * 1.8).toFixed(2)),
    upward_pressure_periods: [
      { start_day_offset: 1, end_day_offset: 5, direction: 'upward', intensity: 0.62 },
      { start_day_offset: 12, end_day_offset: 20, direction: 'upward', intensity: 0.44 },
    ],
    downward_pressure_periods: [
      { start_day_offset: 6, end_day_offset: 11, direction: 'downward', intensity: 0.38 },
    ],
    critical_kou_di_points: [
      {
        day_offset: 6,
        distance_pct: Number((((ma - currentPrice) / Math.max(currentPrice, 1)) * 100).toFixed(1)),
        note: '扣抵區段切換，觀察均線斜率是否變鈍',
      },
    ],
  };
}

function buildHorizon(
  horizon: Horizon,
  data: TaiwanStockAnalysisResponse,
  direction: Direction,
  signalOffset: number,
  riskOffset: number
): HorizonView {
  const confidence = normalizedConfidence(data.confidence);
  const absPct = Math.abs(data.price_change_percent);
  const signal = clamp(55 + absPct * 5 + signalOffset + (direction.includes('bullish') ? 8 : 0));
  const risk = clamp(38 + absPct * 7 + riskOffset);
  const technicalState = technicalStateFromDirection(direction, risk);
  const isBearish = direction === 'bearish' || direction === 'neutral_bearish';
  const directionLabel = isBearish ? '偏空' : direction === 'neutral' ? '中性' : '偏多';

  return {
    horizon,
    technical_state: technicalState,
    state_label_zh: TECHNICAL_STATE_LABELS[technicalState],
    state_detail: `${directionLabel}結構，漲跌幅 ${data.price_change_percent.toFixed(2)}%，AI 信心 ${Math.round(confidence)} 分。`,
    direction,
    factor_votes: [
      {
        category: 'PRICE_VS_MA',
        direction: isBearish ? 'bearish' : 'bullish',
        strength: clamp(signal / 100, 0, 1),
        evidence_text: isBearish ? '價格相對短均線偏弱' : '價格相對短均線偏強',
      },
      {
        category: 'MA_GEOMETRY',
        direction: isBearish ? 'neutral' : 'bullish',
        strength: 0.66,
        evidence_text: data.technical?.summary ?? '均線結構由目前趨勢推估',
      },
      {
        category: 'VOLUME_QUALITY',
        direction: 'neutral',
        strength: 0.48,
        evidence_text: `成交量 ${data.volume.toLocaleString()}，需搭配量均線確認`,
      },
      {
        category: 'CHIP_FLOW',
        direction: data.institutional_summary?.direction?.includes('賣') ? 'bearish' : 'neutral',
        strength: 0.5,
        evidence_text: data.institutional_summary?.direction ?? '法人方向資料有限',
      },
    ],
    categories_in_agreement: isBearish
      ? ['PRICE_VS_MA', 'VOLUME_QUALITY']
      : ['PRICE_VS_MA', 'MA_GEOMETRY', 'STRUCTURE'],
    dow_structure: isBearish ? 'bullish_at_risk' : 'bullish_intact',
    wyckoff_phase: isBearish ? 'distribution_a' : 'markup',
    scores: {
      signal,
      confidence: clamp(confidence - Math.max(0, riskOffset / 2)),
      risk,
      confidence_cap_reason: confidence < 60 ? '資料完整度不足，信心分數自動保守' : undefined,
    },
    invalidation_conditions: [
      {
        description: isBearish
          ? '重新站回 MA20 且量能溫和放大，偏空假設失效'
          : '收盤跌破 MA20，且成交量放大到 VMA20 的 1.5 倍以上',
        trigger_expression: isBearish
          ? 'close > ma20 AND volume > vma20'
          : 'close < ma20 AND volume > vma20 * 1.5',
        monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
        severity: 'hard',
      },
      {
        description: '連續兩個交易日與主方向相反，降低該時序信心',
        trigger_expression: 'direction_mismatch_for_2_sessions',
        monitored_fields: ['close', 'trend_state'],
        severity: 'soft',
      },
    ],
    reasons: [
      reason('AI 綜合趨勢判讀', 'trend', 'trend + price_change_percent', `${data.trend} / ${data.price_change_percent.toFixed(2)}%`, data.analyzed_at),
      reason('後端四面向摘要', 'comprehensive_analysis.summary', 'summary exists', data.comprehensive_analysis?.summary ?? data.summary, data.analyzed_at),
    ],
  };
}

function buildEvidence(data: TaiwanStockAnalysisResponse): EvidenceItem[] {
  const items: EvidenceItem[] = [];

  const add = (
    source: EvidenceItem['source'],
    title: string,
    detail: string,
    weight: number,
    factor_category?: FactorCategory
  ) => {
    items.push({
      id: `${source}-${items.length + 1}`,
      source,
      direction: evidenceDirectionFromWeight(weight),
      factor_category,
      title,
      detail,
      weight,
    });
  };

  if (data.technical?.summary) add('technical', '技術摘要', data.technical.summary, 6, 'STRUCTURE');
  if (data.chip?.summary) add('chip', '籌碼摘要', data.chip.summary, 4, 'CHIP_FLOW');
  if (data.fundamental?.summary) add('fundamental', '基本面摘要', data.fundamental.summary, 5);
  if (data.news?.summary) add('news', '消息摘要', data.news.summary, 3, 'NEWS_CATALYST');

  data.catalysts.slice(0, 4).forEach((catalyst) => add('news', '催化因子', catalyst, 4, 'NEWS_CATALYST'));
  data.risks.slice(0, 4).forEach((risk) => add('news', '風險因子', risk, -5, 'NEWS_CATALYST'));

  if (items.length === 0) {
    add('technical', 'AI 摘要', data.summary || '目前資料不足，僅能給出保守判讀。', 0, 'STRUCTURE');
  }

  return items.slice(0, 12);
}

function buildPivots(data: TaiwanStockAnalysisResponse) {
  const candles = data.chart_data.slice(-8);
  if (candles.length >= 4) {
    return candles.map((candle, index) => ({
      date: candle.time,
      type: index % 2 === 0 ? 'low' as const : 'high' as const,
      price: index % 2 === 0 ? candle.low : candle.high,
      is_confirmed: index < candles.length - 1,
    }));
  }

  const base = data.current_price || 100;
  return [
    { date: 'T-5', type: 'low' as const, price: base * 0.94, is_confirmed: true },
    { date: 'T-4', type: 'high' as const, price: base * 1.02, is_confirmed: true },
    { date: 'T-3', type: 'low' as const, price: base * 0.97, is_confirmed: true },
    { date: 'T-2', type: 'high' as const, price: base * 1.04, is_confirmed: true },
    { date: 'T-1', type: 'low' as const, price: base * 0.99, is_confirmed: false },
  ];
}

export function transformTaiwanAnalysisToAI(data: TaiwanStockAnalysisResponse): AIAnalysisResult {
  const overallDirection = directionFromTrend(data.trend, data.price_change_percent);
  const confidence = normalizedConfidence(data.confidence);
  const risk = clamp(38 + Math.abs(data.price_change_percent) * 7);
  const signal = clamp(55 + Math.abs(data.price_change_percent) * 5 + (overallDirection.includes('bullish') ? 10 : 0));
  const dataQuality = data.data_source === 'live'
    ? 'live'
    : data.data_source === 'mock'
      ? 'mock'
      : 'fallback';
  const qualityScore = dataQuality === 'live'
    ? clamp(confidence + 10)
    : dataQuality === 'mock'
      ? 55
      : 62;
  const priceChange = data.current_price * (data.price_change_percent / 100);
  const nextUpdateAt = new Date(new Date(data.analyzed_at).getTime() + 30 * 60 * 1000).toISOString();
  const isBearish = overallDirection === 'bearish' || overallDirection === 'neutral_bearish';

  return {
    symbol: data.symbol,
    symbol_name: data.company_name,
    sector_tag: data.is_etf ? 'ETF' : data.market_type,
    market_cap_bucket: 'large',
    current_price: data.current_price,
    price_change: Number(priceChange.toFixed(2)),
    price_change_pct: data.price_change_percent,
    overall_direction: overallDirection,
    cross_horizon_state: isBearish ? 'distribution_warning' : 'bull_pullback_in_uptrend',
    overall_scores: {
      signal,
      confidence,
      risk,
      confidence_cap_reason: confidence < 60 ? 'AI 信心低於 60，建議僅作為觀察清單' : undefined,
    },
    one_line_summary: data.summary || data.recommendation || '目前資料不足，建議以風險控管優先。',
    horizons: {
      short_term: buildHorizon('short_term', data, overallDirection, -8, 8),
      swing: buildHorizon('swing', data, isBearish ? 'neutral_bearish' : 'neutral_bullish', 2, 0),
      long_term: buildHorizon('long_term', data, isBearish ? 'neutral' : 'bullish', 8, -8),
    },
    bullish_scenario: {
      direction: 'bullish',
      label: '多方成立條件',
      conditions: [
        {
          condition_text: '收盤重新站回 MA20，且量能不低於近期均量',
          monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
          trigger_expression: 'close > ma20 AND volume >= vma20',
        },
        {
          condition_text: '三個時序至少兩個轉為中性偏多以上',
          monitored_fields: ['short_term.direction', 'swing.direction', 'long_term.direction'],
          trigger_expression: 'bullish_horizons >= 2',
        },
      ],
      action_if_triggered: '列入積極觀察，採分批而非一次追價。',
      scope_horizons: ['short_term', 'swing'],
    },
    bearish_scenario: {
      direction: 'bearish',
      label: '失效與風險條件',
      conditions: [
        {
          condition_text: '跌破 MA20 且成交量放大到 VMA20 的 1.5 倍',
          monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
          trigger_expression: 'close < ma20 AND volume > vma20 * 1.5',
        },
        {
          condition_text: '最近確認 swing low 失守，波段結構轉弱',
          monitored_fields: ['close', 'last_confirmed_swing_low'],
          trigger_expression: 'close < last_confirmed_swing_low',
        },
      ],
      action_if_triggered: '降低部位、停止加碼，等待結構重新轉強。',
      scope_horizons: ['short_term', 'swing'],
    },
    evidence_ledger: buildEvidence(data),
    structure_panel: {
      dow_structure: isBearish ? 'bullish_at_risk' : 'bullish_intact',
      wyckoff_phase: isBearish ? 'distribution_a' : 'markup',
      recent_pivots: buildPivots(data),
      kou_di_ma20: buildKouDi(20, data.current_price),
      kou_di_ma60: buildKouDi(60, data.current_price),
      kou_di_ma120: buildKouDi(120, data.current_price),
      ma_compression_ratio: Math.abs(data.price_change_percent) < 1 ? 0.028 : 0.052,
      is_compressed: Math.abs(data.price_change_percent) < 1,
    },
    report_sections: [
      {
        key: 'narrative',
        title: '市場敘事',
        icon: 'target',
        preview: data.summary || '目前市場敘事資料有限。',
        body_markdown: data.equity_research?.narrative_conclusion ?? data.summary ?? '尚無足夠市場敘事資料。',
      },
      {
        key: 'fundamentals',
        title: '基本面延伸',
        icon: 'chart',
        preview: data.fundamental?.summary ?? data.equity_research?.valuation_verdict ?? '基本面資料有限。',
        body_markdown: data.fundamental?.summary ?? data.equity_research?.valuation_assumptions ?? '尚無足夠基本面延伸資料。',
      },
      {
        key: 'technical_chips',
        title: '技術與籌碼延伸',
        icon: 'activity',
        preview: data.technical?.summary ?? data.chip?.summary ?? '技術與籌碼資料有限。',
        body_markdown: [data.technical?.summary, data.chip?.summary].filter(Boolean).join('\n\n') || '尚無足夠技術與籌碼延伸資料。',
      },
      {
        key: 'scenarios',
        title: '情境分析',
        icon: 'route',
        preview: data.recommendation || '情境資料有限。',
        body_markdown: data.equity_research?.summary ?? data.recommendation ?? '尚無足夠情境資料。',
      },
      {
        key: 'rating',
        title: '評級摘要',
        icon: 'rating',
        preview: data.equity_research?.investment_rating ?? data.recommendation ?? '評級資料有限。',
        body_markdown: data.equity_research?.summary ?? data.recommendation ?? '尚無足夠評級資料。',
      },
    ],
    data_sources: [data.data_source, data.analysis_source, data.market_type].filter(Boolean),
    models_used: [data.analysis_source === 'ai' ? 'Gemini' : 'mock/rules', 'technical-rule-v1'],
    data_quality: dataQuality,
    data_quality_score: qualityScore,
    disposition_status: 'normal',
    analyzed_at: data.analyzed_at,
    next_update_at: nextUpdateAt,
    rule_set_version: 'v1.0.0',
    is_v1_hypothesis: true,
  };
}
