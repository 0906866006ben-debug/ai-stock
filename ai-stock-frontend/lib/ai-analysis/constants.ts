import type {
  CrossHorizonState,
  DataQuality,
  Direction,
  DispositionStatus,
  EvidenceSource,
  FactorCategory,
} from '@/types/aiAnalysis';

export const DIRECTION_STYLES: Record<Direction, {
  bg: string;
  text: string;
  border: string;
  label: string;
  icon: string;
}> = {
  bullish: {
    bg: 'bg-emerald-50 dark:bg-emerald-950/50',
    text: 'text-emerald-800 dark:text-emerald-200',
    border: 'border-emerald-200 dark:border-emerald-800',
    label: '偏多',
    icon: '↗',
  },
  neutral_bullish: {
    bg: 'bg-lime-50 dark:bg-lime-950/50',
    text: 'text-lime-800 dark:text-lime-200',
    border: 'border-lime-200 dark:border-lime-800',
    label: '中性偏多',
    icon: '↗',
  },
  neutral: {
    bg: 'bg-zinc-100 dark:bg-zinc-800',
    text: 'text-zinc-700 dark:text-zinc-200',
    border: 'border-zinc-200 dark:border-zinc-700',
    label: '中性',
    icon: '→',
  },
  neutral_bearish: {
    bg: 'bg-amber-50 dark:bg-amber-950/50',
    text: 'text-amber-800 dark:text-amber-200',
    border: 'border-amber-200 dark:border-amber-800',
    label: '中性偏空',
    icon: '↘',
  },
  bearish: {
    bg: 'bg-red-50 dark:bg-red-950/50',
    text: 'text-red-800 dark:text-red-200',
    border: 'border-red-200 dark:border-red-800',
    label: '偏空',
    icon: '↘',
  },
};

export const SOURCE_STYLES: Record<EvidenceSource, {
  bg: string;
  text: string;
  label: string;
  description: string;
}> = {
  technical: { bg: 'bg-lime-100 dark:bg-lime-950', text: 'text-lime-900 dark:text-lime-200', label: '技', description: '技術面證據' },
  chip: { bg: 'bg-sky-100 dark:bg-sky-950', text: 'text-sky-900 dark:text-sky-200', label: '籌', description: '籌碼面證據' },
  fundamental: { bg: 'bg-violet-100 dark:bg-violet-950', text: 'text-violet-900 dark:text-violet-200', label: '基', description: '基本面證據' },
  news: { bg: 'bg-rose-100 dark:bg-rose-950', text: 'text-rose-900 dark:text-rose-200', label: '息', description: '消息面證據' },
};

export const FACTOR_LABELS: Record<FactorCategory, string> = {
  PRICE_VS_MA: '價位均線',
  MA_GEOMETRY: '均線結構',
  VOLUME_QUALITY: '量價品質',
  STRUCTURE: '結構',
  MOMENTUM: '動能',
  VOLATILITY: '波動',
  CHIP_FLOW: '籌碼',
  BREAKOUT_QUALITY: '突破品質',
  NEWS_CATALYST: '消息催化',
};

export const CROSS_HORIZON_META: Record<CrossHorizonState, {
  label: string;
  description: string;
  action_hint: string;
}> = {
  aligned_bullish: {
    label: '三時序共振多',
    description: '短線、波段、長線同步偏多',
    action_hint: '可進入積極研究與分批佈局觀察',
  },
  triple_resonance_confluence: {
    label: '三重共振進場',
    description: '短階轉強 + 中階回測支撐 + 高階起漲',
    action_hint: 'v1 假設：最高品質進場訊號',
  },
  bull_pullback_in_uptrend: {
    label: '健康回檔',
    description: '長線多 + 波段多 + 短線弱',
    action_hint: '等待短線止跌後分批進場',
  },
  dead_cat_bounce: {
    label: '弱勢反彈',
    description: '長線空 + 波段空 + 短線強',
    action_hint: '短線反彈不視為轉折，逢高減碼',
  },
  distribution_warning: {
    label: '派發警告',
    description: '長線多 + 波段中性 + 短線弱',
    action_hint: '進入波段減碼觀察期',
  },
  reversal_forming: {
    label: '潛在轉折',
    description: '長線空 + 波段中性 + 短線強',
    action_hint: '等待波段確認轉強再加碼',
  },
  aligned_bearish: {
    label: '三時序共振空',
    description: '三個時序全部偏空',
    action_hint: '避免進場，已有部位以風險控管優先',
  },
  mixed_uncertain: {
    label: '矛盾觀望',
    description: '三個時序訊號不一致',
    action_hint: '等待結構明朗後再提高部位',
  },
};

export const DATA_QUALITY_LABELS: Record<DataQuality, string> = {
  live: '即時資料',
  delayed: '延遲資料',
  estimated: '估算資料',
  mock: '示範資料',
  fallback: '備援資料',
};

export const DISPOSITION_MESSAGES: Record<Exclude<DispositionStatus, 'normal'>, {
  level: 'warning' | 'danger';
  text: string;
}> = {
  attention: {
    level: 'warning',
    text: '此股票為注意股，量價分析可信度降低',
  },
  stage_1: {
    level: 'danger',
    text: '此股票進入處置股第一階段，技術指標可能失真',
  },
  stage_2: {
    level: 'danger',
    text: '此股票進入處置股第二階段，技術分析暫停輸出',
  },
};

export const SCORE_LABELS = {
  signal: '技術訊號',
  confidence: '信心度',
  risk: '追價風險',
} as const;

export const SCORE_AXIS_CONFIG = {
  signal: {
    label: '技術訊號',
    color: '#3B6D11',
    bg_light: '#EAF3DE',
    text_dark: '#27500A',
    tooltip: '衡量當前技術型態的攻擊性。基於 10 種價格狀態、均線扣抵預測、Wyckoff 相位、量價配合的加權平均（v1 規則）。',
  },
  confidence: {
    label: '分析信心',
    color: '#185FA5',
    bg_light: '#E6F1FB',
    text_dark: '#0C447C',
    tooltip: '衡量底層資料的可靠性。資料完整度、流動性充裕度、跨週期一致性、籌碼支持時信心高。mock 資料時 cap 50，無 invalidation 時 cap 60。',
  },
  risk: {
    label: '追價風險',
    color: '#BA7517',
    bg_light: '#FAEEDA',
    text_dark: '#854F0B',
    tooltip: '衡量當前的追價回撤風險。基於乖離率（BIAS z-score）、過熱度（RSI/KD）、大盤環境綜合評估。',
  },
} as const;
