import type {
  DowTrendStructure,
  Horizon,
  TechnicalState,
  WyckoffPhase,
} from '@/types/aiAnalysis';

export const HORIZON_LABELS: Record<Horizon, string> = {
  short_term: '短線',
  swing: '波段',
  long_term: '長線',
};

export const HORIZON_TIME_RANGE_LABEL: Record<Horizon, string> = {
  short_term: '1-10 日',
  swing: '2 週-3 月',
  long_term: '3 月以上',
};

export const TECHNICAL_STATE_LABELS: Record<TechnicalState, string> = {
  parabolic_overheat: '極端噴發態',
  strong_uptrend: '強勢多頭態',
  steady_uptrend: '穩健增長態',
  high_level_distribution: '高位派發態',
  early_weakening: '初步轉弱態',
  tight_consolidation: '窄幅整理態',
  early_strengthening: '早期轉強態',
  weak_rebound: '弱勢反彈態',
  downtrend_continuation: '空頭延續態',
  selling_climax: '恐慌衰竭態',
  mixed_signals: '多空混雜',
  data_insufficient: '資料不足',
  disposition_suspended: '處置暫停分析',
};

export const TECHNICAL_STATE_LABEL_ZH: Record<TechnicalState, {
  label: string;
  short_description: string;
  severity: 'high_risk' | 'bullish' | 'bearish' | 'neutral' | 'alert';
}> = {
  parabolic_overheat: { label: '極端噴發態', short_description: 'BIAS 95 分位 + RSI > 80', severity: 'high_risk' },
  strong_uptrend: { label: '強勢多頭態', short_description: 'MA20/60 多頭排列 + HH/HL', severity: 'bullish' },
  steady_uptrend: { label: '穩健增長態', short_description: 'MA20 緩升，籌碼支撐', severity: 'bullish' },
  high_level_distribution: { label: '高位派發態', short_description: '創高無量 + 頂背離', severity: 'alert' },
  early_weakening: { label: '初步轉弱態', short_description: '跌破 MA20 + MA5/10 死叉', severity: 'bearish' },
  tight_consolidation: { label: '窄幅整理態', short_description: 'MA 糾結 + ATR 萎縮', severity: 'neutral' },
  early_strengthening: { label: '早期轉強態', short_description: '首次帶量站回 MA20', severity: 'bullish' },
  weak_rebound: { label: '弱勢反彈態', short_description: '反彈受阻於下彎均線', severity: 'bearish' },
  downtrend_continuation: { label: '空頭延續態', short_description: 'MA 空頭排列 + LH/LL', severity: 'bearish' },
  selling_climax: { label: '恐慌衰竭態', short_description: '急殺爆量 + RSI < 20', severity: 'alert' },
  mixed_signals: { label: '因子分歧', short_description: '未達 3 個類別共識', severity: 'neutral' },
  data_insufficient: { label: '資料不足', short_description: 'K 棒數不滿足需求', severity: 'neutral' },
  disposition_suspended: { label: '處置股暫停', short_description: '處置期間指標失真', severity: 'high_risk' },
};

export const DOW_STRUCTURE_LABELS: Record<DowTrendStructure, string> = {
  bullish_intact: '多頭結構完整',
  bullish_at_risk: '多頭結構承壓',
  bos_down: '跌破結構',
  bearish_intact: '空頭結構完整',
  bearish_at_risk: '空頭結構轉弱',
  bos_up: '突破結構',
  undefined: '結構未定義',
};

export const WYCKOFF_PHASE_LABELS: Record<WyckoffPhase, string> = {
  accumulation_a: '吸籌 A',
  accumulation_b: '吸籌 B',
  accumulation_c: '吸籌 C',
  accumulation_d: '吸籌 D',
  accumulation_e: '吸籌 E',
  markup: '主升段',
  distribution_a: '派發 A',
  distribution_b: '派發 B',
  distribution_c: '派發 C',
  distribution_d: '派發 D',
  distribution_e: '派發 E',
  markdown: '主跌段',
  unclear: '相位不明',
};

export const WYCKOFF_PHASE_DESCRIPTIONS: Record<WyckoffPhase, string> = {
  accumulation_a: '下跌尾聲，供給開始被吸收',
  accumulation_b: '大型資金測試區間供需',
  accumulation_c: '可能出現 Spring 或最後測試',
  accumulation_d: '需求轉強，價格開始脫離底部',
  accumulation_e: '吸籌完成，準備進入上升趨勢',
  markup: '主升段，趨勢推進效率較高',
  distribution_a: '上漲尾聲，需求開始遲疑',
  distribution_b: '高檔震盪，供給逐步增加',
  distribution_c: '可能出現 UTAD 或假突破',
  distribution_d: '供給壓力明顯，回檔加深',
  distribution_e: '派發完成，準備進入下跌趨勢',
  markdown: '主跌段，風險控管優先',
  unclear: '目前資料不足以判定相位',
};
