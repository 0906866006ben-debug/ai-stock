"""輸出「中線桶（CANSLIM 領導股）」當日快照 → backend/data/leader_snapshot.json。

雲端沒有正典資料庫，此桶走「本機計算 → 快照隨 repo 部署」架構（同回測儀表板 JSON）。
訊號定義 = experiments_ledger Iteration 4 註冊規則（貼高 + 月營收加速 + 帶量 + 大盤閘 +
可買性）。**該回測判定 FAIL（T+60 excu +1.4% 未達 +2% 門檻、逐事件輸 TAIEX）**——
快照與端點必須攜帶此誠實標註，本桶為「條件觀察名單」，非已驗證選股力。

Grades（描述性分級，未經分級別驗證）：
  S = 全部條件成立 且 收盤創 252 日新高 且 月營收 YoY >= 30%
  A = 全部條件成立（貼高 >= 95%、YoY >= 10% 且加速、量 >= 1.5x、大盤 > 100SMA）
  B = 位置/引擎/大盤閘成立但當日無量能確認（觀察）

Run:  .venv/Scripts/python.exe backend/scripts/export_leader_snapshot.py
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
H_DB = ROOT / "backend" / "historical_data.db"
P_DB = ROOT / "backend" / "pit_fundamentals.db"
OUT = ROOT / "backend" / "data" / "leader_snapshot.json"

FINANCIAL_CODES = frozenset({
    "2801", "2807", "2809", "2812", "2816", "2820", "2823", "2827", "2831", "2832", "2833",
    "2834", "2836", "2837", "2838", "2845", "2847", "2849", "2850", "2851", "2852", "2854",
    "2855", "2856", "2867", "2880", "2881", "2882", "2883", "2884", "2885", "2886", "2887",
    "2888", "2889", "2890", "2891", "2892", "2897", "5820", "5854", "5859", "5863", "5864",
    "5876", "5878", "5880", "6004", "6005", "6012", "6015", "6016", "6020", "6021", "6023",
    "6024", "6026", "6027", "6028", "6035", "6878", "9101", "9102", "9103", "9104", "9105",
    "9106", "9110", "9136", "9151", "9157", "9188",
})


def main() -> None:
    h = sqlite3.connect(H_DB, timeout=120)
    px = pd.read_sql(
        "SELECT stock_id, date, close, volume, turnover FROM ohlcv WHERE date>=?",
        h, params=((datetime.now().date().replace(year=datetime.now().year - 2)).isoformat(),),
    )
    bench = pd.read_sql(
        "SELECT date, close FROM ohlcv WHERE stock_id='TAIEX' ORDER BY date", h)
    h.close()
    p = sqlite3.connect(P_DB, timeout=120)
    rev = pd.read_sql("SELECT stock_id, date, revenue FROM month_revenue WHERE date>=?",
                      p, params=("2023-01-01",))
    p.close()

    px = px[px.stock_id.str.len().eq(4) & px.stock_id.str.isdigit()]
    as_of = px.date.max()

    # 大盤閘：TAIEX > 100 日均線
    b = bench.set_index("date").close
    regime_on = bool(b.iloc[-1] > b.rolling(100).mean().iloc[-1])

    # PIT 可見月營收（M+1/10）：只保留今日已可見的月份
    rev = rev.dropna(subset=["revenue"]).copy()
    rev["ym"] = rev.date.str[:4].astype(int) * 12 + rev.date.str[5:7].astype(int)
    rev = rev.sort_values(["stock_id", "ym"]).drop_duplicates(["stock_id", "ym"], keep="last")
    y, m = rev.ym // 12, rev.ym % 12
    m2 = m + 1
    y2 = y + (m2 > 12).astype(int)
    m2 = np.where(m2 > 12, 1, m2)
    rev["visible"] = [f"{yy:04d}-{mm:02d}-10" for yy, mm in zip(y2, m2)]
    rev = rev[rev.visible <= as_of]
    g = rev.groupby("stock_id", sort=False)
    rev["yoy"] = (rev.revenue / g.revenue.shift(12) - 1) * 100
    rev["yoy_prev"] = rev.groupby("stock_id", sort=False).yoy.shift(1)
    latest_rev = rev.sort_values("ym").groupby("stock_id").tail(1).set_index("stock_id")

    items = []
    for sid, gpx in px.groupby("stock_id"):
        if sid in FINANCIAL_CODES:
            continue
        gpx = gpx.sort_values("date")
        if gpx.date.iloc[-1] != as_of or len(gpx) < 252:
            continue
        close = float(gpx.close.iloc[-1])
        avg20_turn = float(gpx.turnover.tail(20).mean() or 0)
        if close < 10 or avg20_turn < 30_000_000:
            continue
        hi252 = float(gpx.close.tail(252).max())
        if close < 0.95 * hi252:
            continue
        r = latest_rev.loc[sid] if sid in latest_rev.index else None
        if r is None or pd.isna(r.yoy) or pd.isna(r.yoy_prev):
            continue
        if not (r.yoy >= 10 and r.yoy > r.yoy_prev):
            continue
        vol = float(gpx.volume.iloc[-1] or 0)
        avg20_vol = float(gpx.volume.iloc[-21:-1].mean() or 0)
        vol_ok = avg20_vol > 0 and vol >= 1.5 * avg20_vol
        at_high = close >= hi252
        sma20 = float(gpx.close.tail(20).mean())
        # 飆股雷達：近 5 日出現接近漲停的單日漲幅（>=9%）——純觀察切片，未驗證，
        # 且與 MAX 效應（樂透股平均後期報酬較低）正面衝突，前端必須帶警語。
        last5_ret = gpx.close.pct_change().tail(5)
        max5 = float(last5_ret.max()) if len(last5_ret) else 0.0
        radar = max5 >= 0.09
        if not regime_on:
            grade = "B"  # 大盤閘關閉 → 一律觀察級
        elif vol_ok and at_high and r.yoy >= 30:
            grade = "S"
        elif vol_ok:
            grade = "A"
        else:
            grade = "B"
        items.append({
            "stock_id": sid, "close": close, "grade": grade, "radar": radar,
            "basis": (
                f"收盤位於 252 日高點 {close / hi252:.0%}"
                f"{'（創高）' if at_high else ''}；月營收 YoY {r.yoy:+.1f}% 且高於前月"
                f"（{r.yoy_prev:+.1f}%）；當日量能 {vol / avg20_vol:.1f}x 20日均量"
                + (f"；近5日含單日 {max5:+.0%} 漲幅" if radar else "")
                if avg20_vol > 0 else "量能資料不足"
            ),
            "metrics": {
                "dist_to_252d_high": round(close / hi252 - 1, 4),
                "revenue_yoy": round(float(r.yoy), 2),
                "revenue_yoy_prev": round(float(r.yoy_prev), 2),
                "volume_ratio_20d": round(vol / avg20_vol, 2) if avg20_vol > 0 else None,
                "sma20": round(sma20, 2),
                "dist_to_sma20": round(close / sma20 - 1, 4) if sma20 else None,
                "max_gain_5d": round(max5, 4),
            },
        })

    items.sort(key=lambda x: ("SAB".index(x["grade"]), -x["metrics"]["revenue_yoy"]))
    out = {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regime_on": regime_on,
        "items": items[:20],
        "n_qualified": len(items),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"as_of={as_of} regime_on={regime_on} qualified={len(items)} -> {OUT}")
    for it in items[:10]:
        print(it["grade"], it["stock_id"], it["basis"])


if __name__ == "__main__":
    main()
