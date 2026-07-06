// 加密永續異常掃描 — Vercel Edge Route(部署於亞洲區避開 Binance 對美國 IP 的封鎖)。
// 前端每 N 秒打這支 → 即時掃 Binance → 回最新訊號。純市場資料、無金鑰、無回測背書。
export const runtime = 'edge';
export const preferredRegion = ['hnd1', 'sin1']; // 東京 / 新加坡
export const dynamic = 'force-dynamic';

const BASE = 'https://fapi.binance.com';

interface Row {
  sym: string; price: number; rsi: number; fr: number; dist_e12: number;
  ret_z: number; chg24: number; tag: string; strength: number;
}

function rsi(closes: number[], n = 14): number {
  if (closes.length < n + 1) return NaN;
  let up = 0, dn = 0;
  for (let i = closes.length - n; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) up += d; else dn -= d;
  }
  up /= n; dn /= n;
  if (dn === 0) return 100;
  return 100 - 100 / (1 + up / dn);
}

function emaLast(closes: number[], span: number): number {
  const a = 2 / (span + 1);
  let e = closes[0];
  for (let i = 1; i < closes.length; i++) e = a * closes[i] + (1 - a) * e;
  return e;
}

async function jget(path: string): Promise<any> {
  const r = await fetch(BASE + path, { headers: { 'User-Agent': 'Mozilla/5.0' }, cache: 'no-store' });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export async function GET(request: Request): Promise<Response> {
  const u = new URL(request.url);
  const tf = u.searchParams.get('tf') || '15m';
  const minVol = parseFloat(u.searchParams.get('minVol') || '15');   // 百萬美元
  const top = parseInt(u.searchParams.get('top') || '35', 10);
  const rsiHi = parseFloat(u.searchParams.get('rsiHi') || '70');
  const rsiLo = parseFloat(u.searchParams.get('rsiLo') || '30');

  try {
    const [tickers, prem] = await Promise.all([
      jget('/fapi/v1/ticker/24hr'),
      jget('/fapi/v1/premiumIndex'),
    ]);
    const funding: Record<string, number> = {};
    for (const p of prem) funding[p.symbol] = parseFloat(p.lastFundingRate || '0') || 0;
    const chgMap: Record<string, number> = {};

    const pool: { sym: string; chg: number }[] = [];
    for (const t of tickers) {
      const sym: string = t.symbol;
      if (!sym.endsWith('USDT')) continue;
      const qv = parseFloat(t.quoteVolume || '0') / 1e6;
      if (qv < minVol) continue;
      const chg = parseFloat(t.priceChangePercent || '0');
      chgMap[sym] = chg;
      pool.push({ sym, chg: Math.abs(chg) });
    }
    pool.sort((a, b) => b.chg - a.chg);
    const shortlist = pool.slice(0, Math.max(top, 20)).map((x) => x.sym);

    const rows: Row[] = [];
    await Promise.all(shortlist.map(async (sym) => {
      let k: any;
      try {
        k = await jget(`/fapi/v1/klines?symbol=${sym}&interval=${tf}&limit=100`);
      } catch { return; }
      if (!Array.isArray(k) || k.length < 30) return;
      const closes = k.map((c: any) => parseFloat(c[4]));
      const r = rsi(closes);
      const e12 = emaLast(closes, 12);
      const price = closes[closes.length - 1];
      const rets: number[] = [];
      for (let i = 1; i < closes.length; i++) rets.push(closes[i] / closes[i - 1] - 1);
      const past = rets.slice(0, -1);
      const mean = past.reduce((s, x) => s + x, 0) / past.length;
      const sd = Math.sqrt(past.reduce((s, x) => s + (x - mean) ** 2, 0) / past.length) || 1e-9;
      const ret_z = (rets[rets.length - 1] - mean) / sd;
      const fr = funding[sym] || 0;
      const dist_e12 = price / e12 - 1;
      const prevBelow = closes[closes.length - 2] < emaLast(closes.slice(0, -1), 12);
      const prevAbove = closes[closes.length - 2] > emaLast(closes.slice(0, -1), 12);

      let tag = '', strength = 0;
      if (r >= rsiHi && fr > 0) {
        tag = '🔻做空觀察(超買+資費正)';
        strength = (r - 50) + fr * 5000 + Math.max(ret_z, 0) * 5 + (price < e12 ? 8 : 0);
        if (price < e12 && prevBelow) tag += ' ★剛跌破EMA12';
      } else if (r <= rsiLo && fr < 0) {
        tag = '🔺做多觀察(超賣+資費負)';
        strength = (50 - r) + (-fr) * 5000 + Math.max(-ret_z, 0) * 5 + (price > e12 ? 8 : 0);
        if (price > e12 && prevAbove) tag += ' ★剛站上EMA12';
      } else if (Math.abs(ret_z) >= 3) {
        tag = '⚡純價格異常(觀察)';
        strength = Math.abs(ret_z);
      }
      if (!tag) return;
      rows.push({
        sym, price, rsi: r, fr: fr * 100, dist_e12: dist_e12 * 100,
        ret_z, chg24: chgMap[sym], tag, strength,
      });
    }));

    rows.sort((a, b) => b.strength - a.strength);
    const now = new Date().toISOString();
    return new Response(JSON.stringify({ status: 'ok', generated_at: now, tf, rsi_hi: rsiHi, rsi_lo: rsiLo, rows }), {
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : 'scan failed';
    // 451/403 多半是交易所地區封鎖 → 回誠實錯誤,前端提示
    return new Response(JSON.stringify({ status: 'error', detail: msg }), {
      status: 200, headers: { 'content-type': 'application/json' },
    });
  }
}
