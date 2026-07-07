'use client';

import { useEffect, useRef, useState } from 'react';

interface Row {
  sym: string; price: number; rsi: number; fr: number; fr_pct: number;
  dist_e12: number; ext_z: number; vol_z: number; oi_chg: number;
  oi_state: string; ext_extreme: boolean;
  diverg: boolean; chg24: number; tag: string; quality: number;
  triggered: boolean; tier: string; trig_body: number; trig_vol: number;
}
interface ScanResp {
  status: string; generated_at?: string; tf?: string; rows?: Row[]; detail?: string;
}

const REFRESH_SEC = 30;
const kind = (t: string) => (t.includes('做空') ? 'down' : (t.includes('做多') || t.includes('追多')) ? 'up' : 'anom');
const fmtPx = (p: number) => (p >= 1 ? p.toFixed(3) : p.toPrecision(4));
const sgn = (v: number, d = 2) => (v > 0 ? '+' : '') + v.toFixed(d);

export default function CryptoScanView() {
  const [data, setData] = useState<ScanResp | null>(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'down' | 'up' | 'anom'>('all');
  const [countdown, setCountdown] = useState(REFRESH_SEC);
  const [updatedAt, setUpdatedAt] = useState<string>('');
  const [alertOn, setAlertOn] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevTrig = useRef<Set<string>>(new Set());
  const alertOnRef = useRef(false);

  // 響一聲(WebAudio,不需檔案)
  function beep() {
    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AC();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = 880;
      o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
      o.start(); o.stop(ctx.currentTime + 0.5);
    } catch { /* 靜音失敗不致命 */ }
  }

  function fireAlert(newHits: Row[]) {
    beep();
    const names = newHits.map((r) => `${r.sym.replace('USDT', '')} ${r.tag.includes('做空') ? '做空' : '做多'}`).join('、');
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      new Notification('📡 加密觸發 ★', { body: names, tag: 'crypto-scan' });
    }
  }

  async function load() {
    try {
      const r = await fetch('/api/crypto-scan?minVol=15', { cache: 'no-store' });
      const d: ScanResp = await r.json();
      if (d.status !== 'ok') { setErr(d.detail || '掃描暫時失敗(可能為交易所地區限制)'); }
      else {
        setData(d); setErr(''); setUpdatedAt(new Date().toLocaleTimeString('zh-TW'));
        // 偵測「新出現」的 ★ 觸發 → 響鈴+通知(只有開啟通知後才響)
        const nowTrig = (d.rows || []).filter((x) => x.triggered);
        const fresh = nowTrig.filter((x) => !prevTrig.current.has(x.sym));
        if (alertOnRef.current && fresh.length > 0) fireAlert(fresh);
        prevTrig.current = new Set(nowTrig.map((x) => x.sym));
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '載入失敗');
    } finally {
      setLoading(false);
      setCountdown(REFRESH_SEC);
    }
  }

  async function enableAlerts() {
    if (typeof Notification !== 'undefined' && Notification.permission !== 'granted') {
      try { await Notification.requestPermission(); } catch { /* ignore */ }
    }
    beep(); // 順便解鎖手機的音訊播放權限
    alertOnRef.current = true;
    setAlertOn(true);
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
            onClick={enableAlerts}
            className={`ml-auto rounded-full px-3 py-1 text-xs font-medium ${
              alertOn ? 'bg-emerald-600 text-white' : 'border border-amber-600 text-amber-300 hover:bg-amber-950/40'
            }`}
          >
            {alertOn ? '🔔 觸發響鈴已開' : '🔕 開啟觸發響鈴'}
          </button>
          <button
            onClick={load}
            className="rounded-full border border-cyan-700 px-3 py-1 text-xs font-medium text-cyan-300 hover:bg-cyan-950/50"
          >
            ↻ 立即刷新
          </button>
        </div>
        <p className="mt-1 text-xs text-zinc-400">
          均值回歸:1h RSI-14 超買≥75/超賣≤25(硬門檻)+ 過度偏離 EMA12 → 1m 整根實體收破 EMA20+守住(扳機,無需放量)· ◆無量/★有量 · 目標拉回 EMA12
          {updatedAt ? ` · 更新 ${updatedAt}` : ''}
          {rows.length ? ` · 🔻${counts.down} 🔺${counts.up} ⚡${counts.anom}` : ''}
        </p>
      </div>

      <details className="rounded-xl border border-zinc-800 bg-zinc-900/60">
        <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-semibold text-cyan-300">
          📖 數值怎麼看(速查表)
        </summary>
        <div className="space-y-3 px-4 pb-4 text-xs text-zinc-300">
          <p className="text-zinc-400">
            <b className="text-zinc-200">均值回歸邏輯</b>:<b className="text-fuchsia-400">1h RSI 超買≥75 / 超賣≤25(鐵門檻,沒到不進名單)</b>+ 離 EMA12 夠遠 → 等 1m 整根實體收破 EMA20(<b className="text-cyan-400">扳機,無需放量</b>)→ 目標拉回 EMA12。
            資費、OI、放量 才是 <b className="text-amber-300">加分</b>。
          </p>
          <RefTable
            title="1h RSI-14 · 鐵門檻(沒到直接不出現)"
            rows={[['≥75', '超買 → 只找做空'], ['25~75', '不夠極端,不進名單❌'], ['≤25', '超賣 → 只找做多']]}
          />
          <RefTable
            title="偏離z · 離 EMA12 多遠(獲利空間)"
            rows={[['≥+3', '極端偏離,多半已竭盡 ✅✅ 做空'], ['+1~+3', '過度偏離 → 做空(拉回空間大)'], ['≤−3', '極端 ✅✅ 做多']]}
          />
          <RefTable
            title="距 EMA12 目標% = 拉回停利空間"
            rows={[['絕對值越大', '拉回 EMA12 的肉越多,這單越值得'], ['做空', '現價在 EMA12 上方,目標往下拉回'], ['做多', '現價在 EMA12 下方,目標往上拉回']]}
          />
          <RefTable
            title="扳機:1m 整根實體收破 EMA20(◆/★)"
            rows={[['◆ 無量', '整根實體決定性收破+守住 = 你的實際扳機(均值回歸不需量)'], ['★ 有量', '整根收破 再加放量 = 最高把握'], ['1m實體 ≥1.5', '一大根、決定性(非收針)'], ['守住', '下一根沒收回均線才算數(濾假破)']]}
          />
          <RefTable
            title="加分項(不是門檻,只提高把握)"
            rows={[['資費分位 ≥90 / ≤10', '人群擠爆,+把握'], ['OI🔥堆積', '槓桿燃料足,+把握;⚠️消退則−'], ['放量(★)', '有真實拋壓/搶單,+把握']]}
          />
          <p className="rounded-lg bg-cyan-950/40 px-3 py-2 text-cyan-200">
            🎯 <b>可以做單</b> = 1h RSI 超買≥75/超賣≤25(鐵門檻)<b>且</b> 離 EMA12 夠遠 <b>且</b> 1m 整根實體收破 EMA20 + 守住(◆)。
            再有放量 = ★(最高把握)。目標:拉回 EMA12 停利。
          </p>
        </div>
      </details>

      <div className="flex flex-wrap gap-2">
        {([['all', '全部'], ['down', '🔻做空(超買·跌破)'], ['up', '🔺做多(超賣·突破)'], ['anom', '⚡純異常']] as const).map(([k, label]) => (
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
            <div
              key={r.sym}
              className={`relative overflow-hidden rounded-xl border bg-zinc-900 p-3 ${
                r.tier === '★' ? 'border-cyan-500 ring-1 ring-cyan-500/50'
                  : r.tier === '◆' ? 'border-amber-500 ring-1 ring-amber-500/40' : 'border-zinc-800'
              }`}
            >
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
                <Metric k="距EMA12目標" v={sgn(r.dist_e12, 1) + '%'} cls="text-cyan-300" />
                <Metric k="偏離z" v={sgn(r.ext_z, 1)} cls={r.ext_extreme ? 'text-fuchsia-400' : Math.abs(r.ext_z) >= 2 ? 'text-fuchsia-300' : ''} />
                <Metric k="RSI(1h)" v={r.rsi.toFixed(0)} cls={r.rsi >= 70 ? 'text-red-400' : r.rsi <= 30 ? 'text-emerald-400' : ''} />
                <Metric k="資費分位" v={r.fr_pct + '%'} cls={r.fr_pct >= 90 || r.fr_pct <= 10 ? 'text-fuchsia-400' : ''} />
                <Metric k={`OI${r.oi_state === '堆積' ? '🔥' : r.oi_state === '消退' ? '⚠️' : ''}`} v={sgn(r.oi_chg, 1) + '%'} cls={r.oi_state === '堆積' ? 'text-emerald-400' : r.oi_state === '消退' ? 'text-red-400' : ''} />
                <Metric k="1m實體/量x" v={r.trig_body ? `${r.trig_body.toFixed(1)}/${r.trig_vol.toFixed(1)}` : '—'} cls={r.trig_body >= 1.5 ? 'text-cyan-400' : ''} />
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

function RefTable({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div>
      <p className="mb-1 font-semibold text-zinc-200">{title}</p>
      <div className="overflow-hidden rounded-lg border border-zinc-800">
        {rows.map(([v, meaning], i) => (
          <div key={i} className={`flex gap-3 px-2.5 py-1.5 ${i % 2 ? 'bg-zinc-900/40' : 'bg-zinc-900/70'}`}>
            <span className="w-16 shrink-0 font-mono tabular-nums text-cyan-300">{v}</span>
            <span className="text-zinc-300">{meaning}</span>
          </div>
        ))}
      </div>
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
