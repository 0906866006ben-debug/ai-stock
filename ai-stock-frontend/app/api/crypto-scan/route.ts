// 加密永續異常掃描 — Vercel Edge Route(亞洲區,避開 Binance 對美國 IP 的封鎖)。
// 多框架:設定在 15m 找(超買/超賣 + 資費擁擠 + 過度延伸),觸發在 1m 抓
// 「一大根放量 + 實體收破 EMA20」(非收針)。純市場資料、無金鑰、無回測背書。
export const runtime = 'edge';
export const preferredRegion = ['hnd1', 'sin1'];
export const dynamic = 'force-dynamic';

const BASE = 'https://fapi.binance.com';

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

async function jget(path: string): Promise<any> {
  const r = await fetch(BASE + path, { headers: { 'User-Agent': 'Mozilla/5.0' }, cache: 'no-store' });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

// 一大根放量 + 實體收破 EMA20 + 「下一根守住(沒收回均線)」回踩確認。
// 突破根 = 倒數第二根(n-2),確認根 = 最後一根(n-1)。dir=1 突破(多)、dir=-1 跌破(空)。
function bigBreak(kl: any[], dir: number, volMult: number, bodyMult: number):
  { hit: boolean; loud: boolean; body: number; vol: number; held: boolean } {
  if (!Array.isArray(kl) || kl.length < 26) return { hit: false, loud: false, body: 0, vol: 0, held: false };
  const o = kl.map((c) => parseFloat(c[1])), h = kl.map((c) => parseFloat(c[2]));
  const lo = kl.map((c) => parseFloat(c[3])), cl = kl.map((c) => parseFloat(c[4]));
  const v = kl.map((c) => parseFloat(c[5]));
  const n = cl.length;
  const bi = n - 2;                                  // 突破那根
  const e20b = emaLast(cl.slice(0, bi + 1), 20);     // 突破當根的 EMA20
  const e20c = emaLast(cl, 20);                       // 確認根(n-1)的 EMA20
  const O = o[bi], H = h[bi], L = lo[bi], C = cl[bi], V = v[bi];
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
    broke = big && C < e20b && C < O && closePos <= 0.4;  // 一大根陰線實體收破(均值回歸扳機,不含放量)
    held = cl[n - 1] < e20c;                              // 確認根仍收在 EMA20 下(沒收回)
  } else {
    broke = big && C > e20b && C > O && closePos >= 0.6;  // 一大根陽線實體收破
    held = cl[n - 1] > e20c;
  }
  // hit = 扳機成立(整根實體收破+守住,無需放量);loud = 有放量(升級為 ★ 用)
  return { hit: broke && held, loud: volMul >= volMult, body: bodyMul, vol: volMul, held };
}

export async function GET(request: Request): Promise<Response> {
  const u = new URL(request.url);
  const tf = u.searchParams.get('tf') || '1h';           // 設定框架(1h 過度偏離 + EMA12 目標)
  const trigTf = u.searchParams.get('trigTf') || '1m';   // 觸發框架(你的 1 分鐘)
  const minVol = parseFloat(u.searchParams.get('minVol') || '15');
  const top = parseInt(u.searchParams.get('top') || '35', 10);
  const minQ = parseFloat(u.searchParams.get('minQ') || '30');
  const volMult = parseFloat(u.searchParams.get('volMult') || '1.5');   // 放量倍數
  const bodyMult = parseFloat(u.searchParams.get('bodyMult') || '1.5');  // 一大根倍數

  try {
    const [tickers, prem] = await Promise.all([jget('/fapi/v1/ticker/24hr'), jget('/fapi/v1/premiumIndex')]);
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

    // ── 第一階段:15m 設定偵測 ──
    const rows: Row[] = [];
    const dirOf: Record<string, number> = {};
    await Promise.all(shortlist.map(async (sym) => {
      let k: any, oiHist: any = null;
      try { k = await jget(`/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=120`); } catch { return; }
      try { oiHist = await jget(`/futures/data/openInterestHist?symbol=${sym}&period=${tf}&limit=12`); } catch { /* OI 可缺 */ }
      if (!Array.isArray(k) || k.length < 40) return;
      const closes = k.map((c: any) => parseFloat(c[4]));
      const vols = k.map((c: any) => parseFloat(c[5]));
      const price = closes[closes.length - 1];
      const rs = rsiSeries(closes);
      const r = rs[rs.length - 1];
      const e20 = emaLast(closes, 20);
      const fr = funding[sym] ?? 0;
      const fr_pct = frPct(fr);
      const e12 = emaLast(closes, 12);                       // 拉回目標
      const dist_e12 = (price / e12 - 1) * 100;              // 距 EMA12 %(=拉回空間/獲利目標)
      const recent = closes.slice(-30);
      // 過度偏離(離 EMA12 幾個波動)——均值回歸的「前提」,必要條件
      const ext_z = (price - e12) / (std(recent.map((c, i) => (i ? c - recent[i - 1] : 0)).slice(1)) * Math.sqrt(20) || 1e-9);
      const vpast = vols.slice(-21, -1);
      const vol_z = (vols[vols.length - 1] - mean(vpast)) / std(vpast);
      let oi_chg = 0;
      if (Array.isArray(oiHist) && oiHist.length >= 4) {
        const a = parseFloat(oiHist[oiHist.length - 4].sumOpenInterest);
        const b = parseFloat(oiHist[oiHist.length - 1].sumOpenInterest);
        if (a > 0) oi_chg = (b / a - 1) * 100;
      }
      const clamp = (x: number) => Math.max(0, Math.min(1, x));

      // ── 均值回歸:硬門檻=1h RSI-14 超買/超賣(75/25),沒到免談;方向由它決定 ──
      const RSI_HI = 75, RSI_LO = 25, EXT_MIN = 1.0;
      let tag = '', dir = 0;
      if (r >= RSI_HI && ext_z >= EXT_MIN) { dir = -1; tag = '🔻做空觀察(1h超買≥75·待1m整根收破)'; }
      else if (r <= RSI_LO && ext_z <= -EXT_MIN) { dir = 1; tag = '🔺做多觀察(1h超賣≤25·待1m整根收破)'; }
      if (!tag) return;   // 沒超買超賣(或偏離方向不符)= 直接不進名單

      // 品質分(0-100):偏離幅度為主 + 資費擠/OI堆積 加分(RSI 已是門檻不再計分)
      const oi_state = oi_chg >= 3 ? '堆積' : oi_chg <= -3 ? '消退' : '中性';
      const ext_extreme = Math.abs(ext_z) >= 3;
      let quality = clamp((Math.abs(ext_z) - EXT_MIN) / 2.5) * 50   // 偏離越大越好(核心)
        + (dir < 0 ? clamp((fr_pct - 0.6) / 0.4) : clamp((0.4 - fr_pct) / 0.4)) * 25  // 資費擠(加分)
        + (oi_chg >= 3 ? 10 : oi_chg <= -3 ? -8 : 0)                                   // OI 堆積/消退
        + (ext_extreme ? 8 : 0);
      quality = Math.max(0, Math.min(100, quality));
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

    // ── 第二階段:只對「設定成立」者抓 1m,驗「一大根放量實體破 EMA20」──
    await Promise.all(rows.map(async (row) => {
      let k1: any;
      try { k1 = await jget(`/fapi/v1/klines?symbol=${row.sym}&interval=${trigTf}&limit=40`); } catch { return; }
      const b = bigBreak(k1, dirOf[row.sym], volMult, bodyMult);
      row.trig_body = Math.round(b.body * 10) / 10;
      row.trig_vol = Math.round(b.vol * 10) / 10;
      if (b.hit) {
        row.triggered = true;
        row.tier = b.loud ? '★' : '◆';   // ★=整根收破+放量(最高把握)、◆=整根收破無量
        const dirTxt = dirOf[row.sym] < 0 ? '🔻做空' : '🔺做多';
        const brk = dirOf[row.sym] < 0 ? '整根實體跌破' : '整根實體突破';
        row.tag = `${dirTxt} ${row.tier}${trigTf}${brk}EMA20+守住${b.loud ? '+放量' : '(無量)'}`;
      }
    }));

    // 已觸發排前面,再依品質分
    rows.sort((a, b) => (Number(b.triggered) - Number(a.triggered)) || (b.quality - a.quality));
    return new Response(JSON.stringify({
      status: 'ok', generated_at: new Date().toISOString(), tf, trig_tf: trigTf, min_quality: minQ, rows,
    }), { headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
  } catch (e: unknown) {
    return new Response(JSON.stringify({ status: 'error', detail: e instanceof Error ? e.message : 'scan failed' }),
      { status: 200, headers: { 'content-type': 'application/json' } });
  }
}
