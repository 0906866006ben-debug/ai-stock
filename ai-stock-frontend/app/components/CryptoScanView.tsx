'use client';

import { useEffect, useRef, useState } from 'react';

interface Row {
  sym: string; price: number; rsi: number; fr: number; fr_pct: number;
  dist_e12: number; ext_z: number; vol_z: number; oi_chg: number;
  diverg: boolean; chg24: number; tag: string; quality: number;
  triggered: boolean; trig_body: number; trig_vol: number;
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
      const r = await fetch('/api/crypto-scan?tf=15m&minVol=15', { cache: 'no-store' });
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
          設定 15m(超買/超賣×資費擁擠)· 觸發 1m 放量實體破 EMA20 + 下一根守住(回踩確認,非收針)· ★=已觸發 · Binance 永續
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
            <b className="text-zinc-200">設定類</b>(RSI／資費分位／OI／延伸z)= 判斷「站錯邊、擠爆沒」→ <b className="text-fuchsia-400">越極端越好</b>；
            <b className="text-zinc-200"> 觸發類</b>(1m實體／1m量)= 那根 K 夠不夠力 → <b className="text-cyan-400">≥1.5 才算數</b>。
          </p>
          <RefTable
            title="RSI · 超買超賣"
            rows={[['≥80', '嚴重超買 → 做空最佳'], ['70–80', '超買 → 做空及格'], ['30–70', '中性,無訊號'], ['20–30', '超賣 → 做多及格'], ['≤20', '嚴重超賣 → 做多最佳']]}
          />
          <RefTable
            title="資費分位 · 人群擠不擠(0–100%)"
            rows={[['≥90%', '多單擠爆前10% → 做空✅✅'], ['70–90%', '偏擠 → 做空及格'], ['30–70%', '普通,無鑑別力'], ['10–30%', '空單偏擠 → 做多及格'], ['≤10%', '空單擠爆前10% → 做多✅✅']]}
          />
          <RefTable
            title="OI變化 · 槓桿堆積(近3根未平倉量%)"
            rows={[['≥+8%', '槓桿大量湧入,軋壓燃料足✅'], ['+3~+8%', '有在堆積'], ['−3~+3%', '平淡'], ['大幅負', '部位在撤,擠壓消退⚠️']]}
          />
          <RefTable
            title="延伸z · 過度延伸(離均線幾個波動)"
            rows={[['≥+2', '往上拉太開 → 做空有回吐空間✅'], ['+1~+2', '有點延伸'], ['−1~+1', '貼均線,沒延伸❌'], ['≤−2', '往下砸太深 → 做多有反彈✅']]}
          />
          <RefTable
            title="1m實體 · 一大根?(幾倍均實體)"
            rows={[['≥2.0', '超大實體 → 真突破✅✅'], ['1.5–2.0', '合格的一大根✅'], ['1.0–1.5', '普通,不夠力❌'], ['<1.0', '小K擦邊,假訊號嫌疑❌']]}
          />
          <RefTable
            title="1m量 · 放量?(幾倍均量)"
            rows={[['≥2.0', '爆量,真有人砸/搶✅✅'], ['1.5–2.0', '合格放量✅'], ['1.0–1.5', '量普通,沒放量❌'], ['<1.0', '縮量,假訊號嫌疑❌']]}
          />
          <p className="rounded-lg bg-cyan-950/40 px-3 py-2 text-cyan-200">
            🎯 <b>可以做單(★)</b> = 設定類極端(RSI超買/賣 + 資費分位≥90或≤10 + 延伸z≥2)<b>且</b> 觸發成立:
            1m一大根(實體≥1.5)+ 放量(≥1.5)+ 實體收破EMA20 + <b className="text-cyan-300">下一根守住沒收回(回踩確認)</b>。
            只有設定→盯著等;破線但下一根收回→假訊號已濾掉;四關全過→★。
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
                r.tag.includes('★') ? 'border-cyan-500 ring-1 ring-cyan-500/40' : 'border-zinc-800'
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
                <Metric k="RSI" v={r.rsi.toFixed(0)} cls={r.rsi >= 70 ? 'text-red-400' : r.rsi <= 30 ? 'text-emerald-400' : ''} />
                <Metric k="資費分位" v={r.fr_pct + '%'} cls={r.fr_pct >= 90 || r.fr_pct <= 10 ? 'text-fuchsia-400' : ''} />
                <Metric k="OI變化" v={sgn(r.oi_chg, 1) + '%'} cls={r.oi_chg >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                <Metric k="延伸z" v={sgn(r.ext_z, 1)} cls={Math.abs(r.ext_z) >= 2 ? 'text-fuchsia-400' : ''} />
                <Metric k="1m實體x" v={r.trig_body ? r.trig_body.toFixed(1) : '—'} cls={r.trig_body >= 1.5 ? 'text-cyan-400' : ''} />
                <Metric k="1m量x" v={r.trig_vol ? r.trig_vol.toFixed(1) : '—'} cls={r.trig_vol >= 1.5 ? 'text-cyan-400' : ''} />
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
