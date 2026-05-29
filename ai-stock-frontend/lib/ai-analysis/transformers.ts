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
  CrossHorizonState,
  DowTrendStructure,
  MultiAgentAnalysis,
  WyckoffPhase,
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
  const normalized = trend.toLowerCase();
  const bullishTerms = ['bullish', 'uptrend', 'strong_uptrend', '看多', '多頭', '強勢', '上漲', '上升'];
  const bearishTerms = ['bearish', 'downtrend', 'downtrend_continuation', '看空', '空頭', '弱勢', '下跌', '下降'];
  const neutralBullishTerms = ['neutral_bullish', '偏多', '轉強', '穩健'];
  const neutralBearishTerms = ['neutral_bearish', '偏空', '轉弱', '承壓'];

  if (bullishTerms.some((term) => normalized.includes(term)) || pct >= 2) return 'bullish';
  if (bearishTerms.some((term) => normalized.includes(term)) || pct <= -2) return 'bearish';
  if (neutralBullishTerms.some((term) => normalized.includes(term))) return 'neutral_bullish';
  if (neutralBearishTerms.some((term) => normalized.includes(term))) return 'neutral_bearish';
  if (pct > 0.3) return 'neutral_bullish';
  if (pct < -0.3) return 'neutral_bearish';
  return 'neutral';
}

function evidenceDirectionFromWeight(weight: number): EvidenceDirection {
  if (weight > 1) return 'bullish';
  if (weight < -1) return 'bearish';
  return 'neutral';
}

function technicalStateFromDirection(direction: Direction, risk: number, absPct: number): TechnicalState {
  if (risk >= 85 && (direction === 'bullish' || direction === 'neutral_bullish')) return 'parabolic_overheat';
  if (direction === 'bullish') return 'strong_uptrend';
  if (direction === 'neutral_bullish') return absPct <= 1 ? 'early_strengthening' : 'steady_uptrend';
  if (direction === 'neutral_bearish') return 'early_weakening';
  if (direction === 'bearish') return 'downtrend_continuation';
  if (absPct <= 1 && risk <= 45) return 'tight_consolidation';
  return 'mixed_signals';
}

function directionalEvidence(direction: Direction): EvidenceDirection {
  if (direction === 'bullish' || direction === 'neutral_bullish') return 'bullish';
  if (direction === 'bearish' || direction === 'neutral_bearish') return 'bearish';
  return 'neutral';
}

function horizonStructure(direction: Direction): {
  dow: DowTrendStructure;
  wyckoff: WyckoffPhase;
  label: string;
  agreement: FactorCategory[];
} {
  if (direction === 'bullish') {
    return {
      dow: 'bullish_intact',
      wyckoff: 'markup',
      label: '偏多',
      agreement: ['PRICE_VS_MA', 'MA_GEOMETRY', 'STRUCTURE'],
    };
  }
  if (direction === 'neutral_bullish') {
    return {
      dow: 'bullish_intact',
      wyckoff: 'accumulation_d',
      label: '中性偏多',
      agreement: ['PRICE_VS_MA', 'STRUCTURE'],
    };
  }
  if (direction === 'neutral_bearish') {
    return {
      dow: 'bullish_at_risk',
      wyckoff: 'distribution_a',
      label: '中性偏空',
      agreement: ['PRICE_VS_MA', 'VOLUME_QUALITY'],
    };
  }
  if (direction === 'bearish') {
    return {
      dow: 'bearish_intact',
      wyckoff: 'markdown',
      label: '偏空',
      agreement: ['PRICE_VS_MA', 'MA_GEOMETRY', 'STRUCTURE'],
    };
  }
  return {
    dow: 'undefined',
    wyckoff: 'unclear',
    label: '中性',
    agreement: [],
  };
}

function crossHorizonStateFromDirection(direction: Direction, risk: number): CrossHorizonState {
  if (risk >= 85 && (direction === 'bullish' || direction === 'neutral_bullish')) return 'distribution_warning';
  if (direction === 'bullish') return 'aligned_bullish';
  if (direction === 'neutral_bullish') return 'bull_pullback_in_uptrend';
  if (direction === 'neutral_bearish') return 'distribution_warning';
  if (direction === 'bearish') return 'aligned_bearish';
  return 'mixed_uncertain';
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
  const technicalState = technicalStateFromDirection(direction, risk, absPct);
  const structure = horizonStructure(direction);
  const directionalVote = directionalEvidence(direction);
  const maVote = direction === 'bullish' || direction === 'bearish'
    ? directionalVote
    : direction === 'neutral' ? 'neutral' : directionalVote;
  const invalidationConditions = direction === 'neutral'
    ? [
        {
          description: '放量站回 MA20，整理區轉為偏多觀察',
          trigger_expression: 'close > ma20 AND volume >= vma20',
          monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
          severity: 'soft' as const,
        },
        {
          description: '跌破 MA20 且量能放大，整理區轉為偏空風險',
          trigger_expression: 'close < ma20 AND volume > vma20 * 1.3',
          monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
          severity: 'hard' as const,
        },
      ]
    : [
        {
          description: directionalVote === 'bearish'
            ? '重新站回 MA20 且量能溫和放大，偏空假設失效'
            : '收盤跌破 MA20，且成交量放大到 VMA20 的 1.5 倍以上',
          trigger_expression: directionalVote === 'bearish'
            ? 'close > ma20 AND volume > vma20'
            : 'close < ma20 AND volume > vma20 * 1.5',
          monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
          severity: 'hard' as const,
        },
        {
          description: '連續兩個交易日與主方向相反，降低該時序信心',
          trigger_expression: 'direction_mismatch_for_2_sessions',
          monitored_fields: ['close', 'trend_state'],
          severity: 'soft' as const,
        },
      ];

  return {
    horizon,
    technical_state: technicalState,
    state_label_zh: TECHNICAL_STATE_LABELS[technicalState],
    state_detail: `${structure.label}結構，漲跌幅 ${data.price_change_percent.toFixed(2)}%，AI 信心 ${Math.round(confidence)} 分。`,
    direction,
    factor_votes: [
      {
        category: 'PRICE_VS_MA',
        direction: directionalVote,
        strength: clamp(signal / 100, 0, 1),
        evidence_text: directionalVote === 'bearish'
          ? '價格相對短均線偏弱'
          : directionalVote === 'bullish'
            ? '價格相對短均線偏強'
            : '價格與短均線方向未明顯偏離',
      },
      {
        category: 'MA_GEOMETRY',
        direction: maVote,
        strength: maVote === 'neutral' ? 0.4 : 0.66,
        evidence_text: data.technical?.summary ?? (maVote === 'neutral' ? '均線結構尚未形成明確方向' : '均線結構由目前趨勢推估'),
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
    categories_in_agreement: structure.agreement,
    dow_structure: structure.dow,
    wyckoff_phase: structure.wyckoff,
    scores: {
      signal,
      confidence: clamp(confidence - Math.max(0, riskOffset / 2)),
      risk,
      confidence_cap_reason: confidence < 60 ? '資料完整度不足，信心分數自動保守' : undefined,
    },
    invalidation_conditions: invalidationConditions,
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

function formatMaybeNumber(value: number | null | undefined, suffix = ''): string {
  if (value == null || !Number.isFinite(value)) return '缺資料';
  return `${Number(value).toLocaleString('zh-TW', { maximumFractionDigits: 2 })}${suffix}`;
}

function latestCandleDate(data: TaiwanStockAnalysisResponse): string | null {
  return data.chart_data.at(-1)?.time ?? null;
}

function buildMultiAgentAnalysis(data: TaiwanStockAnalysisResponse): MultiAgentAnalysis {
  const priceDate = latestCandleDate(data);
  const revenue = data.revenue_summary;
  const valuation = data.valuation_summary;
  const institutional = data.institutional_summary;
  const chipRisk = data.chip_risk_summary;
  const macro = data.macro_summary;
  const hasNews = data.recent_news.length > 0 || Boolean(data.news?.summary);
  const evidencePacks: MultiAgentAnalysis['evidence_packs'] = [
    {
      id: 'price',
      label: '價格與量能',
      source: 'FinMind',
      status: data.chart_data.length > 0 ? 'available' : 'missing',
      latest_date: priceDate,
      summary: `收盤 ${formatMaybeNumber(data.current_price)}，漲跌幅 ${formatMaybeNumber(data.price_change_percent, '%')}，成交量 ${formatMaybeNumber(data.volume)}。`,
      key_values: [
        { label: '現價', value: formatMaybeNumber(data.current_price) },
        { label: '漲跌幅', value: formatMaybeNumber(data.price_change_percent, '%') },
        { label: '成交量', value: formatMaybeNumber(data.volume) },
      ],
      warnings: data.chart_data.length > 0 ? [] : ['價格序列缺資料'],
    },
    {
      id: 'revenue',
      label: '月營收',
      source: 'FinMind',
      status: revenue ? revenue.status === 'mock' ? 'partial' : 'available' : 'missing',
      latest_date: revenue?.latest_revenue ?? null,
      summary: revenue
        ? `YoY ${formatMaybeNumber(revenue.yoy_pct, '%')}，MoM ${formatMaybeNumber(revenue.mom_pct, '%')}，可用月份 ${revenue.available_months}。`
        : '月營收資料未提供。',
      key_values: [
        { label: 'YoY', value: formatMaybeNumber(revenue?.yoy_pct, '%') },
        { label: 'MoM', value: formatMaybeNumber(revenue?.mom_pct, '%') },
        { label: '月份數', value: revenue ? String(revenue.available_months) : '缺資料' },
      ],
      warnings: revenue ? [] : ['月營收缺資料'],
    },
    {
      id: 'valuation',
      label: '估值',
      source: 'FinMind',
      status: valuation ? valuation.status === 'mock' ? 'partial' : 'available' : 'missing',
      latest_date: priceDate,
      summary: valuation
        ? `PER ${formatMaybeNumber(valuation.per)}，PBR ${formatMaybeNumber(valuation.pbr)}，殖利率 ${formatMaybeNumber(valuation.dividend_yield, '%')}。`
        : '估值資料未提供。',
      key_values: [
        { label: 'PER', value: formatMaybeNumber(valuation?.per) },
        { label: 'PBR', value: formatMaybeNumber(valuation?.pbr) },
        { label: '殖利率', value: formatMaybeNumber(valuation?.dividend_yield, '%') },
      ],
      warnings: valuation ? [] : ['PER/PBR 缺資料'],
    },
    {
      id: 'institutional',
      label: '法人籌碼',
      source: 'FinMind',
      status: institutional ? institutional.status === 'mock' ? 'partial' : 'available' : 'missing',
      latest_date: priceDate,
      summary: institutional
        ? `法人方向：${institutional.direction}；外資 5 日 ${formatMaybeNumber(institutional.foreign_net_5d)}，投信 5 日 ${formatMaybeNumber(institutional.trust_net_5d)}。`
        : '法人籌碼資料未提供。',
      key_values: [
        { label: '外資 5D', value: formatMaybeNumber(institutional?.foreign_net_5d) },
        { label: '投信 5D', value: formatMaybeNumber(institutional?.trust_net_5d) },
        { label: '自營 5D', value: formatMaybeNumber(institutional?.dealer_net_5d) },
      ],
      warnings: institutional ? [] : ['法人買賣超缺資料'],
    },
    {
      id: 'margin',
      label: '融資融券 / 籌碼風險',
      source: 'FinMind',
      status: chipRisk ? chipRisk.status === 'mock' ? 'partial' : 'available' : 'missing',
      latest_date: priceDate,
      summary: chipRisk
        ? `籌碼方向：${chipRisk.chip_direction}；風險等級：${chipRisk.risk_level}。`
        : '融資融券與籌碼風險資料未提供。',
      key_values: [
        { label: '融資餘額', value: formatMaybeNumber(chipRisk?.margin_balance) },
        { label: '融券餘額', value: formatMaybeNumber(chipRisk?.short_balance) },
        { label: '風險', value: chipRisk?.risk_level ?? '缺資料' },
      ],
      warnings: chipRisk ? [] : ['融資融券缺資料'],
    },
    {
      id: 'macro-news',
      label: '新聞與宏觀',
      source: hasNews ? 'Yahoo' : 'Backend',
      status: hasNews || macro ? 'partial' : 'missing',
      latest_date: data.recent_news[0]?.published_at ?? data.analyzed_at,
      summary: data.news?.summary ?? (hasNews ? `取得 ${data.recent_news.length} 則新聞。` : '新聞與宏觀資料有限。'),
      key_values: [
        { label: '新聞數', value: String(data.recent_news.length) },
        { label: '美元台幣', value: formatMaybeNumber(macro?.usd_twd) },
        { label: 'NASDAQ', value: formatMaybeNumber(macro?.nasdaq) },
      ],
      warnings: hasNews ? [] : ['新聞來源不足'],
    },
  ];

  const availableCount = evidencePacks.filter((pack) => pack.status === 'available').length;
  const missingData = evidencePacks.flatMap((pack) => pack.warnings);
  const conflicts: string[] = [];
  if (data.price_change_percent > 0 && institutional?.direction?.includes('賣')) {
    conflicts.push('價格偏強，但法人籌碼方向偏保守');
  }
  if (Math.abs(data.price_change_percent) > 1 && chipRisk?.risk_level && chipRisk.risk_level !== 'low') {
    conflicts.push('價格波動擴大，同時籌碼風險不低');
  }
  if (data.technical?.trend && data.chip?.summary && data.chip.summary.includes('賣')) {
    conflicts.push('技術趨勢與籌碼摘要存在分歧');
  }

  const keyPoints = [
    `價格與量能：${evidencePacks[0].summary}`,
    revenue ? `營收：${evidencePacks[1].summary}` : '營收：目前缺少可用 FinMind 月營收摘要。',
    institutional ? `籌碼：${evidencePacks[3].summary}` : '籌碼：法人買賣超資料不足。',
    valuation ? `估值：${evidencePacks[2].summary}` : '估值：PER/PBR 資料不足。',
    hasNews ? `消息：${evidencePacks[5].summary}` : '消息：新聞來源不足，事件判讀保守。',
  ];

  const confidence: MultiAgentAnalysis['claude_final']['confidence'] =
    availableCount >= 4 && missingData.length <= 2 ? 'High' : availableCount >= 2 ? 'Medium' : 'Low';
  const status: MultiAgentAnalysis['claude_final']['status'] =
    missingData.length >= 4 ? 'Insufficient_Data'
      : data.price_change_percent > 0.5 && conflicts.length <= 1 ? 'Strong'
        : data.price_change_percent < -1 ? 'Weak'
          : 'Neutral';

  const conclusion = status === 'Insufficient_Data'
    ? '目前資料覆蓋不足，結論應以資料補齊後再確認。'
    : status === 'Strong'
      ? '目前資料組合偏正向，但仍需檢查籌碼與量能是否同步。'
      : status === 'Weak'
        ? '目前價格或風險訊號偏弱，需優先觀察風險來源是否持續。'
        : '目前訊號偏混合，較適合視為條件觀察而非單一方向判斷。';

  return {
    pipeline_version: 'finmind-gemini-claude-ui-v1',
    agents: [
      { name: 'FinMind Agent', role: '蒐集價格、營收、估值、法人、融資融券與宏觀資料', status: data.data_source === 'mock' ? 'fallback' : 'completed' },
      { name: 'Gemini Agent', role: '將 FinMind 資料壓縮成主題重點、矛盾訊號與資料缺口', status: 'fallback' },
      { name: 'Claude Agent', role: '審核 Gemini 重點，產出固定格式最終判讀', status: 'fallback' },
    ],
    evidence_packs: evidencePacks,
    gemini_structured: {
      key_points: keyPoints,
      conflicts,
      missing_data: missingData,
      coverage_notes: evidencePacks.map((pack) => `${pack.label}: ${pack.status}`),
    },
    claude_final: {
      status,
      confidence,
      conclusion,
      supporting_evidence: keyPoints.filter((point) => !point.includes('不足') && !point.includes('缺少')).slice(0, 4),
      key_risks: [...data.risks.slice(0, 3), ...missingData.slice(0, 2)],
      conflicting_signals: conflicts,
      data_limitations: missingData,
      manual_review_required: missingData.length ? ['資料缺口需人工確認', '若要接正式 Agent，需由後端提供來源逐筆引用'] : [],
    },
  };
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
  const overallStructure = horizonStructure(overallDirection);

  return {
    symbol: data.symbol,
    symbol_name: data.company_name,
    sector_tag: data.is_etf ? 'ETF' : data.market_type,
    market_cap_bucket: 'large',
    current_price: data.current_price,
    price_change: Number(priceChange.toFixed(2)),
    price_change_pct: data.price_change_percent,
    overall_direction: overallDirection,
    cross_horizon_state: crossHorizonStateFromDirection(overallDirection, risk),
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
    multi_agent_analysis: buildMultiAgentAnalysis(data),
    structure_panel: {
      dow_structure: overallStructure.dow,
      wyckoff_phase: overallStructure.wyckoff,
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
