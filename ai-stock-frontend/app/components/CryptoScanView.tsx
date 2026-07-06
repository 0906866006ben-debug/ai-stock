'use client';

import { useEffect, useRef, useState } from 'react';

interface Row {
  sym: string; price: number; rsi: number; fr: number; fr_pct: number;
  dist_e12: number; ext_z: number; vol_z: number; oi_chg: number;
  diverg: boolean; chg24: number; tag: string; quality: number;
}
interface ScanResp {
  status: string; generated_at?: string; tf?: string; rows?: Row[]; detail?: string;
}

const REFRESH_SEC = 30;
const kind = (t: string) => (t.includes('做空') ? 'down' : t.includes('做多') ? 'up' : 'anom');
const fmtPx = (p: number) => (p >= 1 ? p.toFixed(3) : p.toPrecision(4));
const sgn = (v: number, d = 2) => (v > 0 ? '+' : '') + v.toFixed(d);

export default function CryptoScanView() {
  const [data, setData] = useState<ScanResp | null>(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'down' | 'up' | 'anom'>('all');
  const [countdown, setCountdown] = useState(REFRESH_SEC);
  const [updatedAt, setUpdatedAt] = useState<string>('');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load() {
    try {
      const r = await fetch('/api/crypto-scan?tf=15m&minVol=15', { cache: 'no-store' });
      const d: ScanResp = await r.json();
      if (d.status !== 'ok') { setErr(d.detail || '掃描暫時失敗(可能為交易所地區限制)'); }
      else { setData(d); setErr(''); setUpdatedAt(new Date().toLocaleTimeString('zh-TW')); }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '載入失敗');
    } finally {
      setLoading(false);
      setCountdown(REFRESH_SEC);
    }
  }

  useEffect(() => {
    load();
    timer.current = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) { load(); return REFRESH_SEC; }
        return c - 1;
      });
    }, 1000);
    return () => { if (timer.current) clearInterval(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = (data?.rows ?? []).slice().sort((a, b) => b.quality - a.quality);
  const counts = { down: 0, up: 0, anom: 0 };
  rows.forEach((r) => { counts[kind(r.tag) as 'down' | 'up' | 'anom']++; });
  const shown = rows.filter((r) => filter === 'all' || kind(r.tag) === filter);

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-cyan-800/50 bg-gradient-to-r from-zinc-900 to-cyan-950/30 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-bold text-cyan-300">📡 加密異常掃描（即時）</h2>
          <span className="rounded-full bg-cyan-600/80 px-2 py-0.5 text-[10px] font-semibold text-white">
            每 {REFRESH_SEC}s 自動更新 · 下次 {countdown}s
          </span>
          <button
            onClick={load}
            className="ml-auto rounded-full border border-cyan-700 px-3 py-1 text-xs font-medium text-cyan-300 hover:bg-cyan-950/50"
          >
            ↻ 立即刷新
          </button>
        </div>
        <p className="mt-1 text-xs text-zinc-400">
          三因子品質分:資費擁擠 × OI槓桿堆積 × 過度延伸(刻意精簡防過擬合)· Binance 永續
          {updatedAt ? ` · 更新 ${updatedAt}` : ''}
          {rows.length ? ` · 🔻${counts.down} 🔺${counts.up} ⚡${counts.anom}` : ''}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {([['all', '全部'], ['down', '🔻做空觀察'], ['up', '🔺做多觀察'], ['anom', '⚡純異常']] as const).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${
              filter === k
                ? 'border-cyan-600 bg-cyan-950/50 text-cyan-300'
                : 'border-zinc-700 bg-zinc-900 text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-zinc-500">掃描中…（首次約需數秒）</p>}
      {err && (
        <p className="rounded-xl border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {err}
        </p>
      )}

      {!loading && !err && shown.length === 0 && (
        <p className="rounded-xl border border-dashed border-zinc-700 px-4 py-6 text-center text-sm text-zinc-500">
          此分類目前無訊號——掃描不硬湊，空的是正常的。
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((r) => {
          const k = kind(r.tag);
          const bar = k === 'down' ? 'bg-red-500' : k === 'up' ? 'bg-emerald-500' : 'bg-amber-500';
          const tagColor = k === 'down' ? 'text-red-400' : k === 'up' ? 'text-emerald-400' : 'text-amber-400';
          return (
            <div key={r.sym} className="relative overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900 p-3">
              <span className={`absolute left-0 top-0 h-full w-[3px] ${bar}`} />
              <div className="flex items-baseline gap-2">
                <span className="text-base font-bold tracking-wide text-zinc-100">{r.sym.replace('USDT', '')}</span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                    r.quality >= 75 ? 'bg-fuchsia-600 text-white' : r.quality >= 65 ? 'bg-amber-500 text-black' : 'bg-zinc-700 text-zinc-200'
                  }`}
                  title="綜合品質分(資費極端度+OI擁擠+過度延伸+量能+翻頭+背離)"
                >
                  品質 {r.quality}
                </span>
                <span className="ml-auto font-mono text-sm tabular-nums text-zinc-400">{fmtPx(r.price)}</span>
              </div>
              <p className={`mt-1 text-xs font-semibold ${tagColor}`}>{r.tag}</p>
              <div className="mt-2 grid grid-cols-3 gap-1.5 font-mono text-xs tabular-nums">
                <Metric k="RSI" v={r.rsi.toFixed(0)} cls={r.rsi >= 70 ? 'text-red-400' : r.rsi <= 30 ? 'text-emerald-400' : ''} />
                <Metric k="資費分位" v={r.fr_pct + '%'} cls={r.fr_pct >= 90 || r.fr_pct <= 10 ? 'text-fuchsia-400' : ''} />
                <Metric k="OI變化" v={sgn(r.oi_chg, 1) + '%'} cls={r.oi_chg >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                <Metric k="延伸z" v={sgn(r.ext_z, 1)} cls={Math.abs(r.ext_z) >= 2 ? 'text-fuchsia-400' : ''} />
                <Metric k="量能z" v={sgn(r.vol_z, 1)} cls={r.vol_z >= 2 ? 'text-fuchsia-400' : ''} />
                <Metric k="24h%" v={sgn(r.chg24, 1) + '%'} cls={r.chg24 >= 0 ? 'text-emerald-400' : 'text-red-400'} />
              </div>
            </div>
          );
        })}
      </div>

      <p className="pt-2 text-center text-[11px] leading-6 text-zinc-500">
        觀察輔助工具，非投資建議、無回測背書。做空噴出幣有軋空尾部風險；控槓桿與停損自負。<br />
        綠＝做多方向（超賣反轉）· 紅＝做空方向（超買反轉）· 國際慣例綠漲紅跌。
      </p>
    </div>
  );
}

function Metric({ k, v, cls = '' }: { k: string; v: string; cls?: string }) {
  return (
    <div className="rounded-md bg-zinc-800/60 px-2 py-1">
      <div className="text-[9px] text-zinc-500">{k}</div>
      <div className={`text-[13px] font-bold ${cls || 'text-zinc-200'}`}>{v}</div>
    </div>
  );
}
