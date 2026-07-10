// 加密永續異常掃描 — Vercel Edge Route(亞洲區,避開 Binance 對美國 IP 的封鎖)。
// 多框架:設定只看 1h RSI 超買/超賣,觸發在 1m 抓
// 「一大根實體收破 EMA12 + 守住」;15m EMA12 只作目標參考,不是篩選條件。
import { getCache } from '@vercel/functions';

export const runtime = 'edge';
export const preferredRegion = ['hnd1', 'sin1'];
export const dynamic = 'force-dynamic';

const BASE = 'https://fapi.binance.com';
const FETCH_TIMEOUT_MS = 8000;
const FETCH_ATTEMPTS = 2;
const SCAN_CONCURRENCY = 24;
const MIN_SETUP_COVERAGE = 0.7;
const FRESH_CACHE_TTL_SEC = 25;
const STALE_CACHE_TTL_SEC = 300;
const JSON_HEADERS = {
  'content-type': 'application/json',
  'cache-control': 'no-store',
  'vercel-cdn-cache-control': 'public, s-maxage=10, stale-while-revalidate=20',
};
const SETUP_INTERVALS = new Set(['5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']);
const TRIGGER_INTERVALS = new Set(['1m', '3m', '5m', '15m']);

type BinanceTicker = {
  symbol: string;
  quoteVolume?: string;
  priceChangePercent?: string;
};

type BinancePremium = {
  symbol: string;
  lastFundingRate?: string;
};

type BinanceKline = [
  number | string,
  string,
  string,
  string,
  string,
  string,
  ...unknown[],
];

type OpenInterestPoint = {
  sumOpenInterest?: string;
};

interface Row {
  sym: string; price: number; rsi: number; fr: number; fr_pct: number;
  dist_e12: number; ext_z: number; vol_z: number; oi_chg: number;
  oi_state: string; ext_extreme: boolean;
  diverg: boolean; chg24: number; tag: string; quality: number;
  triggered: boolean; tier: string; trig_body: number; trig_vol: number;
  trigger_checked: boolean;
  trigger_ms: number; confirm_ms: number;
}

interface ScanDiagnostics {
  shortlisted: number;
  setup_attempted: number;
  setup_succeeded: number;
  setup_failed: number;
  setup_candidates: number;
  target_attempted: number;
  target_succeeded: number;
  target_failed: number;
  oi_failed: number;
  trigger_attempted: number;
  trigger_succeeded: number;
  trigger_failed: number;
  setup_coverage: number;
}

interface ScanPayload {
  status: 'ok';
  scan_mode: string;
  generated_at: string;
  tf: string;
  trig_tf: string;
  min_quality: number;
  degraded: boolean;
  diagnostics: ScanDiagnostics;
  rows: Row[];
}

function rsiSeries(closes: number[], n = 14): number[] {
  const out = new Array(closes.length).fill(NaN);
  let g = 0, l = 0;
  for (let i = 1; i <= n; i++) { const d = closes[i] - closes[i - 1]; if (d > 0) g += d; else l -= d; }
  g /= n; l /= n;
  out[n] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  for (let i = n + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    g = (g * (n - 1) + (d > 0 ? d : 0)) / n;
    l = (l * (n - 1) + (d < 0 ? -d : 0)) / n;
    out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
}
function emaLast(c: number[], span: number): number {
  const a = 2 / (span + 1); let e = c[0];
  for (let i = 1; i < c.length; i++) e = a * c[i] + (1 - a) * e;
  return e;
}
const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / (a.length || 1);
const std = (a: number[]) => { const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))) || 1e-9; };

function boundedNumber(raw: string | null, fallback: number, min: number, max: number): number {
  const value = raw === null ? fallback : Number.parseFloat(raw);
  if (!Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, value));
}

function boundedInteger(raw: string | null, fallback: number, min: number, max: number): number {
  return Math.round(boundedNumber(raw, fallback, min, max));
}

function intervalParam(raw: string | null, fallback: string, allowed: Set<string>): string {
  return raw !== null && allowed.has(raw) ? raw : fallback;
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function mapLimit<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let nextIndex = 0;
  const runners = Array.from({ length: Math.min(Math.max(limit, 1), items.length) }, async () => {
    while (nextIndex < items.length) {
      const item = items[nextIndex];
      nextIndex += 1;
      await worker(item);
    }
  });
  await Promise.all(runners);
}

function errorName(error: unknown): string {
  if (!error || typeof error !== 'object' || !('name' in error)) return '';
  return String((error as { name?: unknown }).name || '');
}

async function jget<T>(path: string): Promise<T> {
  let lastError: unknown = new Error(`${path} upstream failed`);
  for (let attempt = 0; attempt < FETCH_ATTEMPTS; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const r = await fetch(BASE + path, {
        headers: { 'User-Agent': 'Mozilla/5.0' },
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!r.ok) {
        const failure = new Error(`${path} ${r.status}`);
        if (r.status === 418 || r.status === 429) throw Object.assign(failure, { noRetry: true });
        throw failure;
      }
      return await r.json() as T;
    } catch (error) {
      lastError = errorName(error) === 'AbortError'
        ? new Error(`${path} upstream timeout`)
        : error;
      if (error && typeof error === 'object' && 'noRetry' in error) break;
    } finally {
      clearTimeout(timeout);
    }
    if (attempt + 1 < FETCH_ATTEMPTS) await delay(150 * (attempt + 1));
  }
  throw lastError;
}

// 一大根 + 實體收破 EMA12 + 「下一根守住(沒收回均線)」確認。全用「已收 K」:
// 排除幣安最後一根未收 K(n-1);確認根 = 最後已收(n-2)、突破根 = n-3。dir=1 多、dir=-1 空。
function bigBreak(kl: BinanceKline[], dir: number, volMult: number, bodyMult: number):
  { hit: boolean; loud: boolean; body: number; vol: number; held: boolean; triggerMs: number; confirmMs: number } {
  if (!Array.isArray(kl) || kl.length < 26) return { hit: false, loud: false, body: 0, vol: 0, held: false, triggerMs: 0, confirmMs: 0 };
  const o = kl.map((c) => parseFloat(c[1])), h = kl.map((c) => parseFloat(c[2]));
  const lo = kl.map((c) => parseFloat(c[3])), cl = kl.map((c) => parseFloat(c[4]));
  const v = kl.map((c) => parseFloat(c[5]));
  const n = cl.length;
  // 幣安最後一根 cl[n-1] 是「當下未收完」的 K——排除,只用已收 K 判斷,否則會用半根 K 提前跳訊號。
  const ci = n - 2;                                  // 確認根(已收的最後一根)
  const bi = ci - 1;                                  // 突破那根(已收)
  if (bi < 21) return { hit: false, loud: false, body: 0, vol: 0, held: false, triggerMs: 0, confirmMs: 0 };
  const e12p = emaLast(cl.slice(0, bi), 12);          // 突破前一根的 EMA12
  const e12b = emaLast(cl.slice(0, bi + 1), 12);      // 突破當根的 EMA12
  const e12c = emaLast(cl.slice(0, ci + 1), 12);      // 確認根的 EMA12(不含未收根)
  const O = o[bi], H = h[bi], L = lo[bi], C = cl[bi], V = v[bi];
  const prevC = cl[bi - 1];
  const body = Math.abs(C - O), range = Math.max(H - L, 1e-12);
  const bodies = []; for (let i = bi - 20; i < bi; i++) bodies.push(Math.abs(cl[i] - o[i]));
  const avgBody = mean(bodies) || 1e-12;
  const avgVol = mean(v.slice(bi - 20, bi)) || 1e-12;
  const bodyMul = body / avgBody, volMul = V / avgVol;
  const big = bodyMul >= bodyMult;                   // 一大根
  const loud = volMul >= volMult;                    // 放量
  const closePos = (C - L) / range;                  // 收盤在 K 棒位置
  let broke = false, held = false;
  if (dir < 0) {
    broke = big && prevC >= e12p && C < e12b && C < O && closePos <= 0.4;
    held = cl[ci] < e12c;                                 // 確認根(已收)仍收在 EMA12 下
  } else {
    broke = big && prevC <= e12p && C > e12b && C > O && closePos >= 0.6;
    held = cl[ci] > e12c;                                 // 確認根(已收)仍收在 EMA12 上
  }
  // hit = 扳機成立(整根實體收破+守住,無需放量);loud = 有放量(升級為 ★ 用)
  return { hit: broke && held, loud, body: bodyMul, vol: volMul, held, triggerMs: Number(kl[bi][0]) || 0, confirmMs: Number(kl[ci][0]) || 0 };
}

export async function GET(request: Request): Promise<Response> {
  const u = new URL(request.url);
  const tf = intervalParam(u.searchParams.get('tf'), '1h', SETUP_INTERVALS);           // 設定框架(1h RSI)
  const trigTf = intervalParam(u.searchParams.get('trigTf'), '1m', TRIGGER_INTERVALS); // 觸發框架(你的 1 分鐘)
  const minVol = boundedNumber(u.searchParams.get('minVol'), 15, 1, 5000);
  const top = boundedInteger(u.searchParams.get('top'), 150, 1, 200);
  const minQ = boundedNumber(u.searchParams.get('minQ'), 0, 0, 100);
  const volMult = boundedNumber(u.searchParams.get('volMult'), 1.5, 0.1, 10);   // 放量倍數
  const bodyMult = boundedNumber(u.searchParams.get('bodyMult'), 1.5, 0.1, 10);  // 一大根倍數
  const cache = getCache({ namespace: 'crypto-scan' });
  const cacheKey = [tf, trigTf, minVol, top, minQ, volMult, bodyMult].join(':');
  const freshKey = `fresh:${cacheKey}`;
  const staleKey = `stale:${cacheKey}`;

  try {
    const cached = await cache.get(freshKey) as ScanPayload | undefined;
    if (cached) {
      return Response.json(
        { ...cached, cache_status: 'hit', served_at: new Date().toISOString() },
        { headers: JSON_HEADERS },
      );
    }
  } catch {
    // Runtime Cache is an optimization; scan directly if it is unavailable.
  }

  try {
    const [tickers, prem] = await Promise.all([
      jget<BinanceTicker[]>('/fapi/v1/ticker/24hr'),
      jget<BinancePremium[]>('/fapi/v1/premiumIndex'),
    ]);
    const funding: Record<string, number> = {};
    for (const p of prem) funding[p.symbol] = parseFloat(p.lastFundingRate || '0') || 0;

    const chgMap: Record<string, number> = {};
    const pool: string[] = [];
    for (const t of tickers) {
      const sym: string = t.symbol;
      if (!sym.endsWith('USDT')) continue;
      if (parseFloat(t.quoteVolume || '0') / 1e6 < minVol) continue;
      chgMap[sym] = parseFloat(t.priceChangePercent || '0');
      pool.push(sym);
    }
    const frVals = pool.map((s) => funding[s] ?? 0).sort((a, b) => a - b);
    const frPct = (val: number) => {
      let lo = 0, hi = frVals.length;
      while (lo < hi) { const m = (lo + hi) >> 1; if (frVals[m] < val) lo = m + 1; else hi = m; }
      return frVals.length ? lo / frVals.length : 0.5;
    };
    const shortlist = pool.sort((a, b) => Math.abs(chgMap[b]) - Math.abs(chgMap[a])).slice(0, Math.max(top, 20));
    const diagnostics: ScanDiagnostics = {
      shortlisted: shortlist.length,
      setup_attempted: shortlist.length,
      setup_succeeded: 0,
      setup_failed: 0,
      setup_candidates: 0,
      target_attempted: 0,
      target_succeeded: 0,
      target_failed: 0,
      oi_failed: 0,
      trigger_attempted: 0,
      trigger_succeeded: 0,
      trigger_failed: 0,
      setup_coverage: 0,
    };

    // ── 第一階段:只用 1h RSI 超買/超賣產生觀察名單;15m EMA12 只作目標參考 ──
    const rows: Row[] = [];
    const dirOf: Record<string, number> = {};
    await mapLimit(shortlist, SCAN_CONCURRENCY, async (sym) => {
      let k: BinanceKline[] | null = null, k15: BinanceKline[] | null = null, oiHist: OpenInterestPoint[] | null = null;
      try { k = await jget<BinanceKline[]>(`/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=120`); } catch { diagnostics.setup_failed += 1; return; }        // 1h → RSI 超買超賣
      if (!Array.isArray(k) || k.length < 40) { diagnostics.setup_failed += 1; return; }
      diagnostics.setup_succeeded += 1;
      const closes = k.map((c) => parseFloat(c[4]));         // 1h 收盤 → RSI
      const rs = rsiSeries(closes);
      const r = rs[rs.length - 1];                           // 1h RSI-14(超買超賣鐵門檻)

      const RSI_HI = 75, RSI_LO = 25;
      let tag = '', dir = 0;
      if (r >= RSI_HI) { dir = -1; tag = '🔻做空觀察(1h超買≥75·待1m EMA12跌破)'; }
      else if (r <= RSI_LO) { dir = 1; tag = '🔺做多觀察(1h超賣≤25·待1m EMA12突破)'; }
      if (!tag) return;

      diagnostics.setup_candidates += 1;
      diagnostics.target_attempted += 1;
      try { k15 = await jget<BinanceKline[]>(`/fapi/v1/klines?symbol=${sym}&interval=15m&limit=120`); } catch { diagnostics.target_failed += 1; return; }        // 15m → EMA12 目標
      if (!Array.isArray(k15) || k15.length < 20) { diagnostics.target_failed += 1; return; }
      diagnostics.target_succeeded += 1;
      try { oiHist = await jget<OpenInterestPoint[]>(`/futures/data/openInterestHist?symbol=${sym}&period=${tf}&limit=12`); } catch { diagnostics.oi_failed += 1; }
      const closes15 = k15.map((c) => parseFloat(c[4]));      // 15m 收盤 → 目標/偏離
      const vols = k15.map((c) => parseFloat(c[5]));          // 15m 量(context)
      const price = closes15[closes15.length - 1];
      const fr = funding[sym] ?? 0;
      const fr_pct = frPct(fr);
      const e12 = emaLast(closes15, 12);                     // 15m EMA12 = 拉回目標
      const dist_e12 = (price / e12 - 1) * 100;              // 距 15m EMA12 %(=拉回空間/獲利目標)
      const recent = closes15.slice(-30);
      // 15m EMA12 是出場/目標參考;ext_z 只用於排序提示,不擋名單。
      const ext_z = (price - e12) / (std(recent.map((c, i) => (i ? c - recent[i - 1] : 0)).slice(1)) * Math.sqrt(20) || 1e-9);
      const vpast = vols.slice(-21, -1);
      const vol_z = (vols[vols.length - 1] - mean(vpast)) / std(vpast);
      let oi_chg = 0;
      if (Array.isArray(oiHist) && oiHist.length >= 4) {
        const a = parseFloat(oiHist[oiHist.length - 4].sumOpenInterest || '0');
        const b = parseFloat(oiHist[oiHist.length - 1].sumOpenInterest || '0');
        if (a > 0) oi_chg = (b / a - 1) * 100;
      }
      const clamp = (x: number) => Math.max(0, Math.min(1, x));

      const oi_state = oi_chg >= 3 ? '堆積' : oi_chg <= -3 ? '消退' : '中性';
      const ext_extreme = Math.abs(ext_z) >= 3;
      const rsiQuality = dir < 0
        ? clamp((r - RSI_HI) / (100 - RSI_HI)) * 45
        : clamp((RSI_LO - r) / RSI_LO) * 45;
      const fundingAligned = (dir < 0 && fr > 0) || (dir > 0 && fr < 0);
      let quality = rsiQuality
        + clamp(Math.abs(ext_z) / 3) * 20
        + (fundingAligned ? 15 : 0)
        + (oi_chg >= 3 ? 10 : oi_chg <= -3 ? -5 : 0)
        + (ext_extreme ? 8 : 0);
      quality = Math.max(0, Math.min(100, quality));
      tag += fundingAligned ? ' 資費順風' : ' 資費逆風';
      if (oi_state === '堆積') tag += ' 🔥OI堆積';
      else if (oi_state === '消退') tag += ' ⚠️OI消退';
      if (ext_extreme) tag += ' 極端偏離';
      if (quality < minQ) return;
      dirOf[sym] = dir;
      rows.push({
        sym, price, rsi: r, fr: fr * 100, fr_pct: Math.round(fr_pct * 100),
        dist_e12, ext_z, vol_z, oi_chg, oi_state, ext_extreme, diverg: false,
        chg24: chgMap[sym], tag, quality: Math.round(quality),
        triggered: false, tier: '', trig_body: 0, trig_vol: 0, trigger_checked: false,
        trigger_ms: 0, confirm_ms: 0,
      });
    });

    diagnostics.setup_coverage = diagnostics.setup_attempted
      ? Math.round((diagnostics.setup_succeeded / diagnostics.setup_attempted) * 1000) / 1000
      : 1;
    if (diagnostics.setup_attempted > 0 && diagnostics.setup_coverage < MIN_SETUP_COVERAGE) {
      throw new Error(`Binance 1h data coverage too low (${diagnostics.setup_succeeded}/${diagnostics.setup_attempted})`);
    }
    if (diagnostics.target_attempted > 0 && diagnostics.target_succeeded === 0) {
      throw new Error('Binance 15m target data unavailable');
    }

    // ── 第二階段:只對「設定成立」者抓 1m,驗「一大根實體破 EMA12」──
    diagnostics.trigger_attempted = rows.length;
    await mapLimit(rows, SCAN_CONCURRENCY, async (row) => {
      let k1: BinanceKline[];
      try { k1 = await jget<BinanceKline[]>(`/fapi/v1/klines?symbol=${row.sym}&interval=${trigTf}&limit=60`); } catch { diagnostics.trigger_failed += 1; return; }
      if (!Array.isArray(k1) || k1.length < 26) { diagnostics.trigger_failed += 1; return; }
      diagnostics.trigger_succeeded += 1;
      row.trigger_checked = true;
      const b = bigBreak(k1, dirOf[row.sym], volMult, bodyMult);
      row.trig_body = Math.round(b.body * 10) / 10;
      row.trig_vol = Math.round(b.vol * 10) / 10;
      if (b.hit) {
        row.triggered = true;
        row.tier = b.loud ? '★' : '◆';   // ★=整根收破+放量(最高把握)、◆=整根收破無量
        row.trigger_ms = b.triggerMs;
        row.confirm_ms = b.confirmMs;
        const dirTxt = dirOf[row.sym] < 0 ? '🔻做空' : '🔺做多';
        const brk = dirOf[row.sym] < 0 ? '整根實體跌破' : '整根實體突破';
        row.tag = `${dirTxt} ${row.tier}${trigTf}${brk}EMA12+守住${b.loud ? '+放量' : '(無量)'}`;
      }
    });

    // 已觸發排前面,再依品質分
    rows.sort((a, b) => (Number(b.triggered) - Number(a.triggered)) || (b.quality - a.quality));
    const degraded = diagnostics.setup_failed > 0
      || diagnostics.target_failed > 0
      || diagnostics.oi_failed > 0
      || diagnostics.trigger_failed > 0;
    const payload: ScanPayload = {
      status: 'ok', scan_mode: 'rsi_setup_v2', generated_at: new Date().toISOString(), tf, trig_tf: trigTf,
      min_quality: minQ, degraded, diagnostics, rows,
    };
    try {
      await Promise.all([
        cache.set(freshKey, payload, { ttl: FRESH_CACHE_TTL_SEC, tags: ['crypto-scan'], name: 'crypto-scan-fresh' }),
        cache.set(staleKey, payload, { ttl: STALE_CACHE_TTL_SEC, tags: ['crypto-scan'], name: 'crypto-scan-stale' }),
      ]);
    } catch {
      // A cache write failure must not turn a successful live scan into an error.
    }
    return Response.json(
      { ...payload, cache_status: 'miss', served_at: new Date().toISOString() },
      { headers: JSON_HEADERS },
    );
  } catch (e: unknown) {
    try {
      const stale = await cache.get(staleKey) as ScanPayload | undefined;
      if (stale) {
        const rows = stale.rows.map((row) => ({
          ...row,
          tag: row.tag.includes('做空') ? '🔻做空觀察(資料更新中)' : '🔺做多觀察(資料更新中)',
          triggered: false,
          tier: '',
          trigger_checked: false,
          trig_body: 0,
          trig_vol: 0,
          trigger_ms: 0,
          confirm_ms: 0,
        }));
        return Response.json({
          ...stale,
          rows,
          degraded: true,
          stale: true,
          cache_status: 'stale',
          served_at: new Date().toISOString(),
          detail: 'Live Binance scan is temporarily unavailable; stale triggers are disabled.',
        }, { headers: JSON_HEADERS });
      }
    } catch {
      // Fall through to the explicit upstream error response.
    }
    return Response.json(
      { status: 'error', detail: e instanceof Error ? e.message : 'scan failed' },
      { status: 502, headers: JSON_HEADERS },
    );
  }
}
