// 加密永續異常掃描 — Vercel Edge Route(亞洲區,避開 Binance 對美國 IP 的封鎖)。
// 訊號品質版:極端資費(市場百分位)+ OI 擁擠 + 價格過度延伸 + 量能高潮 + RSI 背離,
// 正規化綜合品質分 + 最低門檻 → 少而精。純市場資料、無金鑰、無回測背書。
export const runtime = 'edge';
export const preferredRegion = ['hnd1', 'sin1'];
export const dynamic = 'force-dynamic';

const BASE = 'https://fapi.binance.com';

interface Row {
  sym: string; price: number; rsi: number; fr: number; fr_pct: number;
  dist_e12: number; ext_z: number; vol_z: number; oi_chg: number;
  diverg: boolean; chg24: number; tag: string; quality: number;
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
function mean(a: number[]) { return a.reduce((s, x) => s + x, 0) / (a.length || 1); }
function std(a: number[]) { const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))) || 1e-9; }

async function jget(path: string): Promise<any> {
  const r = await fetch(BASE + path, { headers: { 'User-Agent': 'Mozilla/5.0' }, cache: 'no-store' });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export async function GET(request: Request): Promise<Response> {
  const u = new URL(request.url);
  const tf = u.searchParams.get('tf') || '15m';
  const minVol = parseFloat(u.searchParams.get('minVol') || '15');
  const top = parseInt(u.searchParams.get('top') || '35', 10);
  const minQ = parseFloat(u.searchParams.get('minQ') || '55'); // 最低品質分(0-100),寧缺勿濫

  try {
    const [tickers, prem] = await Promise.all([jget('/fapi/v1/ticker/24hr'), jget('/fapi/v1/premiumIndex')]);
    const funding: Record<string, number> = {};
    for (const p of prem) funding[p.symbol] = parseFloat(p.lastFundingRate || '0') || 0;

    // 候選池 + 資費的「市場橫截面百分位」(極端擁擠才有意義,而非僅>0)
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
    const frPct = (v: number) => {
      let lo = 0, hi = frVals.length;
      while (lo < hi) { const m = (lo + hi) >> 1; if (frVals[m] < v) lo = m + 1; else hi = m; }
      return frVals.length ? lo / frVals.length : 0.5; // 0..1
    };
    const shortlist = pool
      .sort((a, b) => Math.abs(chgMap[b]) - Math.abs(chgMap[a]))
      .slice(0, Math.max(top, 20));

    const rows: Row[] = [];
    await Promise.all(shortlist.map(async (sym) => {
      let k: any, oiHist: any = null;
      try { k = await jget(`/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=120`); } catch { return; }
      try { oiHist = await jget(`/futures/data/openInterestHist?symbol=${sym}&period=${tf}&limit=12`); } catch { /* OI 可缺 */ }
      if (!Array.isArray(k) || k.length < 40) return;
      const closes = k.map((c: any) => parseFloat(c[4]));
      const highs = k.map((c: any) => parseFloat(c[2]));
      const vols = k.map((c: any) => parseFloat(c[5]));
      const price = closes[closes.length - 1];
      const rs = rsiSeries(closes);
      const r = rs[rs.length - 1];
      const e12 = emaLast(closes, 12);
      const e20 = emaLast(closes, 20);
      const fr = funding[sym] ?? 0;
      const fr_pct = frPct(fr);

      // 價格過度延伸(離 EMA20 幾個近期波動 std)——跨幣可比的「超買/超賣」度
      const recent = closes.slice(-30);
      const ext_z = (price - e20) / (std(recent.map((c, i) => (i ? c - recent[i - 1] : 0)).slice(1)) * Math.sqrt(20) || 1e-9);
      // 量能高潮
      const vpast = vols.slice(-21, -1);
      const vol_z = (vols[vols.length - 1] - mean(vpast)) / (std(vpast));
      // OI 變化%(近 ~3 根)——槓桿擁擠代理
      let oi_chg = 0;
      if (Array.isArray(oiHist) && oiHist.length >= 4) {
        const a = parseFloat(oiHist[oiHist.length - 4].sumOpenInterest);
        const b = parseFloat(oiHist[oiHist.length - 1].sumOpenInterest);
        if (a > 0) oi_chg = (b / a - 1) * 100;
      }
      const dist_e12 = (price / e12 - 1) * 100;
      const prevBelow = closes[closes.length - 2] < emaLast(closes.slice(0, -1), 12);
      const prevAbove = closes[closes.length - 2] > emaLast(closes.slice(0, -1), 12);

      // RSI 背離:近 20 根價創高但 RSI 未創高(空方背離)/ 反之(多方背離)
      const w = 20;
      const pSeg = closes.slice(-w), rSeg = rs.slice(-w);
      const pMaxI = pSeg.indexOf(Math.max(...pSeg)), rAtPMax = rSeg[pMaxI];
      const bearDiv = pMaxI >= w - 3 && Math.max(...rSeg.slice(0, w - 2)) > rAtPMax + 3; // 價新高、RSI背離
      const pMinI = pSeg.indexOf(Math.min(...pSeg)), rAtPMin = rSeg[pMinI];
      const bullDiv = pMinI >= w - 3 && Math.min(...rSeg.slice(0, w - 2)) < rAtPMin - 3;

      // 綜合品質分(0-100),各維度正規化後加權;做空/做多對稱
      let tag = '', quality = 0, diverg = false;
      const clamp = (x: number) => Math.max(0, Math.min(1, x));
      if (r >= 68 && fr > 0) {
        const qFund = clamp((fr_pct - 0.7) / 0.3);        // 資費前30%才開始給分,前10%滿分
        const qExt = clamp((ext_z - 1.5) / 2.5);          // 過度延伸
        const qOI = clamp(oi_chg / 8);                    // OI 近3根 +8% 滿分(槓桿追多)
        const qVol = clamp((vol_z - 1) / 3);              // 量能高潮
        const qRoll = price < e12 ? 1 : 0.3;              // 已翻頭
        diverg = bearDiv;
        quality = (qFund * 26 + qExt * 22 + qOI * 22 + qVol * 12 + qRoll * 10 + (diverg ? 8 : 0));
        tag = '🔻做空觀察(超買+擁擠多單)';
        if (price < e12 && prevBelow) tag += ' ★剛跌破EMA12';
        if (diverg) tag += ' ⚠空方背離';
      } else if (r <= 32 && fr < 0) {
        const qFund = clamp((0.3 - fr_pct) / 0.3);
        const qExt = clamp((-ext_z - 1.5) / 2.5);
        const qOI = clamp(-oi_chg / 8);
        const qVol = clamp((vol_z - 1) / 3);
        const qRoll = price > e12 ? 1 : 0.3;
        diverg = bullDiv;
        quality = (qFund * 26 + qExt * 22 + qOI * 22 + qVol * 12 + qRoll * 10 + (diverg ? 8 : 0));
        tag = '🔺做多觀察(超賣+擁擠空單)';
        if (price > e12 && prevAbove) tag += ' ★剛站上EMA12';
        if (diverg) tag += ' ⚠多方背離';
      }
      if (!tag || quality < minQ) return;
      rows.push({
        sym, price, rsi: r, fr: fr * 100, fr_pct: Math.round(fr_pct * 100),
        dist_e12, ext_z, vol_z, oi_chg, diverg, chg24: chgMap[sym], tag,
        quality: Math.round(quality),
      });
    }));

    rows.sort((a, b) => b.quality - a.quality);
    return new Response(JSON.stringify({
      status: 'ok', generated_at: new Date().toISOString(), tf, min_quality: minQ, rows,
    }), { headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
  } catch (e: unknown) {
    return new Response(JSON.stringify({ status: 'error', detail: e instanceof Error ? e.message : 'scan failed' }),
      { status: 200, headers: { 'content-type': 'application/json' } });
  }
}
