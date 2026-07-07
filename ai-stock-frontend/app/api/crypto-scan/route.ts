// 加密永續異常掃描 — Vercel Edge Route(亞洲區,避開 Binance 對美國 IP 的封鎖)。
// 多框架:設定只看 1h RSI 超買/超賣,觸發在 1m 抓
// 「一大根實體收破 EMA12 + 守住」;15m EMA12 只作目標參考,不是篩選條件。
export const runtime = 'edge';
export const preferredRegion = ['hnd1', 'sin1'];
export const dynamic = 'force-dynamic';

const BASE = 'https://fapi.binance.com';
const FETCH_TIMEOUT_MS = 8000;
const JSON_HEADERS = { 'content-type': 'application/json', 'cache-control': 'no-store' };
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

async function jget<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(BASE + path, {
      headers: { 'User-Agent': 'Mozilla/5.0' },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return await r.json() as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`${path} upstream timeout`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

// 一大根 + 實體收破 EMA12 + 「下一根守住(沒收回均線)」回踩確認。
// 突破根 = 倒數第二根(n-2),確認根 = 最後一根(n-1)。dir=1 突破(多)、dir=-1 跌破(空)。
function bigBreak(kl: BinanceKline[], dir: number, volMult: number, bodyMult: number):
  { hit: boolean; loud: boolean; body: number; vol: number; held: boolean } {
  if (!Array.isArray(kl) || kl.length < 26) return { hit: false, loud: false, body: 0, vol: 0, held: false };
  const o = kl.map((c) => parseFloat(c[1])), h = kl.map((c) => parseFloat(c[2]));
  const lo = kl.map((c) => parseFloat(c[3])), cl = kl.map((c) => parseFloat(c[4]));
  const v = kl.map((c) => parseFloat(c[5]));
  const n = cl.length;
  const bi = n - 2;                                  // 突破那根
  const e12p = emaLast(cl.slice(0, bi), 12);          // 突破前一根的 EMA12
  const e12b = emaLast(cl.slice(0, bi + 1), 12);      // 突破當根的 EMA12
  const e12c = emaLast(cl, 12);                       // 確認根(n-1)的 EMA12
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
    held = cl[n - 1] < e12c;                              // 確認根仍收在 EMA12 下(沒收回)
  } else {
    broke = big && prevC <= e12p && C > e12b && C > O && closePos >= 0.6;
    held = cl[n - 1] > e12c;
  }
  // hit = 扳機成立(整根實體收破+守住,無需放量);loud = 有放量(升級為 ★ 用)
  return { hit: broke && held, loud, body: bodyMul, vol: volMul, held };
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

    // ── 第一階段:只用 1h RSI 超買/超賣產生觀察名單;15m EMA12 只作目標參考 ──
    const rows: Row[] = [];
    const dirOf: Record<string, number> = {};
    await Promise.all(shortlist.map(async (sym) => {
      let k: BinanceKline[] | null = null, k15: BinanceKline[] | null = null, oiHist: OpenInterestPoint[] | null = null;
      try { k = await jget<BinanceKline[]>(`/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=120`); } catch { return; }        // 1h → RSI 超買超賣
      if (!Array.isArray(k) || k.length < 40) return;
      const closes = k.map((c) => parseFloat(c[4]));         // 1h 收盤 → RSI
      const rs = rsiSeries(closes);
      const r = rs[rs.length - 1];                           // 1h RSI-14(超買超賣鐵門檻)

      const RSI_HI = 75, RSI_LO = 25;
      let tag = '', dir = 0;
      if (r >= RSI_HI) { dir = -1; tag = '🔻做空觀察(1h超買≥75·待1m EMA12跌破)'; }
      else if (r <= RSI_LO) { dir = 1; tag = '🔺做多觀察(1h超賣≤25·待1m EMA12突破)'; }
      if (!tag) return;

      try { k15 = await jget<BinanceKline[]>(`/fapi/v1/klines?symbol=${sym}&interval=15m&limit=120`); } catch { return; }        // 15m → EMA12 目標
      try { oiHist = await jget<OpenInterestPoint[]>(`/futures/data/openInterestHist?symbol=${sym}&period=${tf}&limit=12`); } catch { /* OI 可缺 */ }
      if (!Array.isArray(k15) || k15.length < 20) return;
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
        triggered: false, tier: '', trig_body: 0, trig_vol: 0,
      });
    }));

    // ── 第二階段:只對「設定成立」者抓 1m,驗「一大根實體破 EMA12」──
    await Promise.all(rows.map(async (row) => {
      let k1: BinanceKline[];
      try { k1 = await jget<BinanceKline[]>(`/fapi/v1/klines?symbol=${row.sym}&interval=${trigTf}&limit=40`); } catch { return; }
      const b = bigBreak(k1, dirOf[row.sym], volMult, bodyMult);
      row.trig_body = Math.round(b.body * 10) / 10;
      row.trig_vol = Math.round(b.vol * 10) / 10;
      if (b.hit) {
        row.triggered = true;
        row.tier = b.loud ? '★' : '◆';   // ★=整根收破+放量(最高把握)、◆=整根收破無量
        const dirTxt = dirOf[row.sym] < 0 ? '🔻做空' : '🔺做多';
        const brk = dirOf[row.sym] < 0 ? '整根實體跌破' : '整根實體突破';
        row.tag = `${dirTxt} ${row.tier}${trigTf}${brk}EMA12+守住${b.loud ? '+放量' : '(無量)'}`;
      }
    }));

    // 已觸發排前面,再依品質分
    rows.sort((a, b) => (Number(b.triggered) - Number(a.triggered)) || (b.quality - a.quality));
    return Response.json({
      status: 'ok', scan_mode: 'rsi_setup_v2', generated_at: new Date().toISOString(), tf, trig_tf: trigTf, min_quality: minQ, rows,
    }, { headers: JSON_HEADERS });
  } catch (e: unknown) {
    return Response.json(
      { status: 'error', detail: e instanceof Error ? e.message : 'scan failed' },
      { status: 502, headers: JSON_HEADERS },
    );
  }
}
