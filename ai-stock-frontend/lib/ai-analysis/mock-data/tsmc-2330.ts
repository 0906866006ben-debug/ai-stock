import type {
  AIAnalysisResult,
  Direction,
  EvidenceDirection,
  FactorCategory,
  Horizon,
  HorizonView,
  KouDiAnalysis,
  ReasonTrace,
  TechnicalState,
} from '@/types/aiAnalysis';
import { TECHNICAL_STATE_LABELS } from '../i18n';

const analyzedAt = new Date().toISOString();

function trace(
  reason_text: string,
  source_field: string,
  calculation: string,
  calculation_value: string
): ReasonTrace {
  return {
    reason_text,
    source_field,
    timestamp: analyzedAt,
    calculation,
    calculation_value,
  };
}

function vote(
  category: FactorCategory,
  direction: EvidenceDirection,
  strength: number,
  evidence_text: string
) {
  return { category, direction, strength, evidence_text };
}

function kouDi(ma_window: number, ma: number, close: number): KouDiAnalysis {
  return {
    ma_window,
    current_ma_value: ma,
    current_close: close,
    expected_direction_next_5d: ma < close ? 'up' : 'flat',
    expected_slope_change_pct: Number((((close - ma) / ma) * 2.1).toFixed(2)),
    upward_pressure_periods: [
      { start_day_offset: 1, end_day_offset: 6, direction: 'upward', intensity: 0.72 },
      { start_day_offset: 13, end_day_offset: 20, direction: 'upward', intensity: 0.48 },
    ],
    downward_pressure_periods: [
      { start_day_offset: 7, end_day_offset: 12, direction: 'downward', intensity: 0.42 },
    ],
    critical_kou_di_points: [
      { day_offset: 7, distance_pct: -5.8, note: '扣抵低價區即將結束，MA 斜率可能趨緩' },
      { day_offset: 14, distance_pct: 6.1, note: '進入較高扣抵區，若量縮容易形成壓力' },
    ],
  };
}

function horizon(
  horizonName: Horizon,
  direction: Direction,
  technical_state: TechnicalState,
  signal: number,
  confidence: number,
  risk: number
): HorizonView {
  const bullish = direction === 'bullish' || direction === 'neutral_bullish';
  return {
    horizon: horizonName,
    technical_state,
    state_label_zh: TECHNICAL_STATE_LABELS[technical_state],
    state_detail: bullish
      ? '收盤仍站在主要均線之上，均線斜率維持正向，回檔暫未破壞結構。'
      : '短線動能降溫，需觀察是否跌破主要均線與前低結構。',
    direction,
    factor_votes: [
      vote('PRICE_VS_MA', bullish ? 'bullish' : 'neutral', 0.78, '收盤價相對 MA20 仍維持正乖離'),
      vote('MA_GEOMETRY', bullish ? 'bullish' : 'neutral', 0.72, 'MA20 > MA60，斜率仍偏上'),
      vote('VOLUME_QUALITY', 'neutral', 0.46, '量能未同步放大，追價效率一般'),
      vote('STRUCTURE', bullish ? 'bullish' : 'neutral', 0.69, '近期低點未跌破前一個 swing low'),
      vote('MOMENTUM', bullish ? 'bullish' : 'neutral', 0.62, '動能放緩但仍在中性上緣'),
    ],
    categories_in_agreement: bullish
      ? ['PRICE_VS_MA', 'MA_GEOMETRY', 'STRUCTURE']
      : ['PRICE_VS_MA', 'VOLUME_QUALITY'],
    dow_structure: bullish ? 'bullish_intact' : 'bullish_at_risk',
    wyckoff_phase: bullish ? 'markup' : 'distribution_a',
    scores: { signal, confidence, risk },
    invalidation_conditions: [
      {
        description: '收盤跌破 MA20，且成交量放大到 VMA20 的 1.5 倍以上',
        trigger_expression: 'close < ma20 AND volume > vma20 * 1.5',
        monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
        severity: 'hard',
      },
      {
        description: '連續兩日未能收復 MA20，短線信心下修',
        trigger_expression: 'close < ma20 FOR 2 sessions',
        monitored_fields: ['close', 'ma20'],
        severity: 'soft',
      },
    ],
    reasons: [
      trace('價格仍在主要均線上方', 'technical.ma20', 'close > ma20', '收盤 950.00 / MA20 925.40'),
      trace('中期結構維持多頭排列', 'technical.ma_geometry', 'ma20 > ma60', 'MA20 925.40 / MA60 886.20'),
    ],
  };
}

export const tsmc2330Analysis: AIAnalysisResult = {
  symbol: '2330',
  symbol_name: '台積電',
  sector_tag: '半導體',
  market_cap_bucket: 'large',
  current_price: 950,
  price_change: 8,
  price_change_pct: 0.85,
  overall_direction: 'neutral_bullish',
  cross_horizon_state: 'bull_pullback_in_uptrend',
  overall_scores: {
    signal: 73,
    confidence: 78,
    risk: 48,
  },
  one_line_summary: '長線趨勢仍偏多，短線進入健康回檔；等待量縮止跌比追價更有勝率。',
  horizons: {
    short_term: horizon('short_term', 'neutral_bullish', 'early_weakening', 62, 70, 55),
    swing: horizon('swing', 'bullish', 'strong_uptrend', 78, 80, 46),
    long_term: horizon('long_term', 'bullish', 'steady_uptrend', 82, 84, 38),
  },
  bullish_scenario: {
    direction: 'bullish',
    label: '多方延續劇本',
    conditions: [
      {
        condition_text: '量縮守住 MA20，並重新站回短期均線上方',
        monitored_fields: ['close', 'ma20', 'volume'],
        trigger_expression: 'close > ma20 AND volume <= vma20',
      },
      {
        condition_text: '波段高點突破時，成交量高於 VMA20 的 1.2 倍',
        monitored_fields: ['close', 'swing_high', 'volume', 'vma20'],
        trigger_expression: 'close > swing_high AND volume > vma20 * 1.2',
      },
    ],
    action_if_triggered: '以分批加碼取代一次追價，停損條件掛在 MA20 失守與量增轉弱。',
    scope_horizons: ['short_term', 'swing'],
  },
  bearish_scenario: {
    direction: 'bearish',
    label: '失效與降風險劇本',
    conditions: [
      {
        condition_text: '跌破 MA20 且量增，短線多方假設失效',
        monitored_fields: ['close', 'ma20', 'volume', 'vma20'],
        trigger_expression: 'close < ma20 AND volume > vma20 * 1.5',
      },
      {
        condition_text: '跌破最近確認 swing low，波段結構轉為承壓',
        monitored_fields: ['close', 'last_confirmed_swing_low'],
        trigger_expression: 'close < last_confirmed_swing_low',
      },
    ],
    action_if_triggered: '降低部位或停止加碼，等待波段結構重新轉強。',
    scope_horizons: ['short_term', 'swing'],
  },
  evidence_ledger: [
    {
      id: 'ev-ma-geometry',
      source: 'technical',
      direction: 'bullish',
      factor_category: 'MA_GEOMETRY',
      title: '均線仍維持多頭排列',
      detail: 'MA20 高於 MA60，且 MA20 斜率仍為正，波段趨勢尚未破壞。',
      weight: 8,
      trace: trace('均線多頭排列', 'technical.ma_geometry', 'ma20 > ma60 AND slope(ma20) > 0', 'MA20 925.40 / MA60 886.20'),
    },
    {
      id: 'ev-price-ma',
      source: 'technical',
      direction: 'bullish',
      factor_category: 'PRICE_VS_MA',
      title: '收盤仍站上 MA20',
      detail: '收盤價高於 MA20 約 2.7%，短線回檔仍屬趨勢內整理。',
      weight: 7,
      trace: trace('價格站上 MA20', 'technical.price_vs_ma', 'close > ma20', '+2.7%'),
    },
    {
      id: 'ev-volume',
      source: 'technical',
      direction: 'neutral',
      factor_category: 'VOLUME_QUALITY',
      title: '量能未明顯配合',
      detail: '近期成交量約為 VMA20 的 0.9 倍，攻擊訊號沒有放大。',
      weight: 1,
    },
    {
      id: 'ev-chip',
      source: 'chip',
      direction: 'bullish',
      factor_category: 'CHIP_FLOW',
      title: '法人籌碼偏向穩定',
      detail: '近 5 日外資與投信合計仍偏買超，籌碼面未見連續撤退。',
      weight: 5,
    },
    {
      id: 'ev-fundamental',
      source: 'fundamental',
      direction: 'bullish',
      title: '基本面敘事支撐估值',
      detail: '營收與毛利率敘事仍由先進製程與 AI 需求支撐。',
      weight: 6,
    },
    {
      id: 'ev-risk',
      source: 'news',
      direction: 'bearish',
      factor_category: 'NEWS_CATALYST',
      title: '短線評價對利率敏感',
      detail: '若美債殖利率上行，成長股估值可能承壓。',
      weight: -4,
    },
    {
      id: 'ev-structure',
      source: 'technical',
      direction: 'bullish',
      factor_category: 'STRUCTURE',
      title: 'Swing low 尚未跌破',
      detail: '近期回檔未破前低，多頭結構仍可視為完整。',
      weight: 7,
    },
  ],
  structure_panel: {
    dow_structure: 'bullish_intact',
    wyckoff_phase: 'markup',
    recent_pivots: [
      { date: '2026-04-10', type: 'low', price: 860, is_confirmed: true },
      { date: '2026-04-16', type: 'high', price: 910, is_confirmed: true },
      { date: '2026-04-22', type: 'low', price: 884, is_confirmed: true },
      { date: '2026-04-29', type: 'high', price: 960, is_confirmed: true },
      { date: '2026-05-05', type: 'low', price: 922, is_confirmed: true },
      { date: '2026-05-11', type: 'high', price: 972, is_confirmed: false },
    ],
    kou_di_ma20: kouDi(20, 925.4, 950),
    kou_di_ma60: kouDi(60, 886.2, 950),
    kou_di_ma120: kouDi(120, 834.8, 950),
    ma_compression_ratio: 0.047,
    is_compressed: false,
  },
  report_sections: [
    {
      key: 'narrative',
      title: '市場敘事',
      icon: 'target',
      preview: 'AI 需求與先進製程仍是主要敘事，短線受估值與匯率影響。',
      body_markdown: '市場敘事仍由 AI 伺服器、先進製程需求與高階封裝帶動。短線若利率或匯率造成評價壓力，仍需看回檔是否守住波段均線。',
    },
    {
      key: 'fundamentals',
      title: '基本面延伸',
      icon: 'chart',
      preview: '營收動能與毛利率仍是中長線評價支撐。',
      body_markdown: '基本面重點在營收年增率、毛利率穩定性與資本支出效率。若營收連續轉弱，長線信心需下修。',
    },
    {
      key: 'technical_chips',
      title: '技術與籌碼延伸',
      icon: 'activity',
      preview: '技術結構偏多，籌碼未見明顯撤退。',
      body_markdown: 'MA20 與 MA60 多頭排列仍完整，外資與投信未出現同步連續賣超。短線需要觀察量縮回檔是否成立。',
    },
    {
      key: 'scenarios',
      title: '情境分析',
      icon: 'route',
      preview: '多方看守住 MA20，空方看量增跌破與 swing low 失守。',
      body_markdown: '多方情境需要量縮守均線並重新突破短線壓力；空方情境則以量增跌破 MA20 與 swing low 為優先警訊。',
    },
    {
      key: 'rating',
      title: '評級摘要',
      icon: 'rating',
      preview: '中性偏多，適合等待回檔確認後分批。',
      body_markdown: '綜合三軸分數，目前屬中性偏多。追價風險中等，較適合等待回檔確認後再提高部位。',
    },
  ],
  data_sources: ['FinMind', 'Yahoo Finance', '內部 v1 技術規則'],
  models_used: ['Gemini fallback', 'rule-set-v1'],
  data_quality: 'mock',
  data_quality_score: 78,
  disposition_status: 'normal',
  analyzed_at: analyzedAt,
  next_update_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
  rule_set_version: 'v1.0.0',
  is_v1_hypothesis: true,
};
