"""Entry-context layer (Task 1A) — verb-free timing/价位 conditions for a screened stock.

Answers, for a stock that ALREADY passed the durable-quality screen, the three questions a
discretionary swing investor asks — WITHOUT issuing any buy/sell/target command (it emits
conditions, zones and states; the user pulls the trigger):
  A. 貴不貴  — technical extension (distance from MAs / 52w high) + valuation percentile (PE/PB
               vs the stock's OWN 5-year history). A short-MA pullback at a 95th-pct valuation
               is NOT cheap.
  B. 等哪裡  — dynamic supports (MAs) + structural supports (box low / breakout neckline);
               when a dynamic and a structural level coincide within a small tolerance ->
               a high-probability CONFLUENCE zone.
  C. 能不能加 — structure intact/weakening/invalidated + at a pullback level + volume confirmed
               -> a verb-free "加碼觀察" condition (never on a broken structure = no falling knife).

DUAL-TRACK PRICE (critical for correctness, per the entry-framework research):
  - MAs / 52w-high / trend  -> ADJUSTED close (除權息還原), so ex-dividend gaps do not create
    false MA breaks. Supplied via `adj_closes` (tw_adjusted_prices).
  - Structural levels (box low / neckline) -> RAW close, the real traded prices the market
    remembers. Supplied via `raw_*` arrays.
  - Comparison space: every level is expressed as a % distance from the CURRENT close (today's
    adjusted == raw, a shared anchor), so confluence between an adjusted MA and a raw structural
    level is measured consistently.
All thresholds live in the YAML `entry_context:` block (tunable). Missing data -> that read is
omitted (no fabrication).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SupportLevel:
    kind: str            # dynamic_ma60 | dynamic_ma200 | structural_box_low | structural_neckline
    price: float
    pct_below: float     # (price/current - 1); negative = below current


@dataclass(frozen=True)
class EntryContext:
    symbol: str
    current_price: float | None = None
    # A — 貴不貴
    extension: dict[str, Any] = field(default_factory=dict)     # pct_from_ma20/60, pct_from_52w_high, label
    valuation: dict[str, Any] = field(default_factory=dict)     # pe, pe_pctile, pb, pb_pctile, label
    expensiveness: str = "unknown"                              # 偏便宜 / 合理 / 偏貴 / unknown
    # B — 等哪裡
    supports: list[SupportLevel] = field(default_factory=list)
    confluence_zones: list[dict[str, Any]] = field(default_factory=list)   # {low, high, kinds}
    # C — 能不能加
    structure_status: str = "unknown"                          # intact / weakening / invalidated
    add_on_context: dict[str, Any] = field(default_factory=dict)   # structure_ok, at_support, volume_confirmed, note
    data_quality: dict[str, Any] = field(default_factory=dict)     # adjusted_available, dividend_events, missing
    missing: list[str] = field(default_factory=list)


def compute_entry_context(
    symbol: str,
    *,
    adj_closes: list[float] | None,
    raw_closes: list[float] | None,
    raw_highs: list[float] | None,
    raw_lows: list[float] | None,
    volumes: list[float] | None,
    per_history: list[float] | None,
    pbr_history: list[float] | None,
    params: Mapping[str, Any],
    adjusted_available: bool = True,
    dividend_events: int = 0,
) -> EntryContext:
    cfg = params.get("entry_context", {}) if isinstance(params, Mapping) else {}
    missing: list[str] = []

    # Current price: latest adjusted == latest raw (shared anchor). Prefer adjusted.
    current = _last(adj_closes) or _last(raw_closes)
    if current is None or current <= 0:
        return EntryContext(symbol=symbol, missing=["price"],
                            data_quality={"adjusted_available": adjusted_available, "dividend_events": dividend_events})

    extension, ext_label = _extension_read(adj_closes, current, cfg, missing)
    valuation, val_label = _valuation_read(per_history, pbr_history, cfg, missing)
    expensiveness = _combine_expensiveness(ext_label, val_label, cfg)

    supports = _support_levels(adj_closes, raw_closes, raw_highs, current, cfg, missing)
    confluence = _confluence_zones(supports, cfg)

    structure = _structure_status(adj_closes, raw_lows, current, cfg, missing)
    add_on = _add_on_context(structure, supports, volumes, current, cfg)

    return EntryContext(
        symbol=symbol, current_price=round(current, 4),
        extension=extension, valuation=valuation, expensiveness=expensiveness,
        supports=supports, confluence_zones=confluence,
        structure_status=structure, add_on_context=add_on,
        data_quality={"adjusted_available": bool(adjusted_available), "dividend_events": int(dividend_events)},
        missing=missing,
    )


# ── A. 貴不貴 ─────────────────────────────────────────────────────────────────
def _extension_read(adj: list[float] | None, current: float, cfg: Mapping[str, Any], missing: list[str]):
    out: dict[str, Any] = {}
    ma20 = _ma(adj, 20)
    ma60 = _ma(adj, 60)
    hi52 = max(adj[-252:]) if adj and len(adj) >= 60 else None   # use available window (>=~3m)
    if ma20:
        out["pct_from_ma20"] = round(current / ma20 - 1.0, 4)
    if ma60:
        out["pct_from_ma60"] = round(current / ma60 - 1.0, 4)
    if hi52:
        out["pct_from_52w_high"] = round(current / hi52 - 1.0, 4)
    if not out:
        missing.append("extension")
        return out, "unknown"
    overext = float(cfg.get("extension_overheat_pct", 0.15))
    pullback = float(cfg.get("extension_pullback_pct", 0.0))
    e60 = out.get("pct_from_ma60")
    if e60 is None:
        label = "unknown"
    elif e60 >= overext:
        label = "延伸過熱"
    elif e60 <= pullback:
        label = "回檔區"
    else:
        label = "合理"
    out["label"] = label
    return out, label


def _valuation_read(per_hist: list[float] | None, pbr_hist: list[float] | None, cfg: Mapping[str, Any], missing: list[str]):
    out: dict[str, Any] = {}
    min_n = int(cfg.get("valuation_min_history", 60))
    pe_p = _percentile_of_last(per_hist, min_n)
    pb_p = _percentile_of_last(pbr_hist, min_n)
    if pe_p is not None:
        out["pe"] = round(per_hist[-1], 2)
        out["pe_percentile"] = round(pe_p, 1)
    if pb_p is not None:
        out["pb"] = round(pbr_hist[-1], 2)
        out["pb_percentile"] = round(pb_p, 1)
    if not out:
        missing.append("valuation")
        return out, "unknown"
    hi = float(cfg.get("valuation_expensive_pctile", 80))
    lo = float(cfg.get("valuation_cheap_pctile", 30))
    # Use the higher of the available percentiles as the binding "expensive" signal.
    pctiles = [p for p in (out.get("pe_percentile"), out.get("pb_percentile")) if p is not None]
    ref = max(pctiles)
    label = "偏貴" if ref >= hi else "偏便宜" if ref <= lo else "合理"
    out["label"] = label
    return out, label


def _combine_expensiveness(ext_label: str, val_label: str, cfg: Mapping[str, Any]) -> str:
    """Valuation dominates ('便宜便宜' guard): a name is only 偏便宜 when valuation is not 偏貴.
    A short-MA pullback at a 95th-pct valuation must NOT read as cheap."""
    if val_label == "unknown" and ext_label == "unknown":
        return "unknown"
    if val_label == "偏貴":
        return "偏貴"                                  # expensive valuation overrides technical pullback
    if ext_label == "延伸過熱":
        return "偏貴"
    if val_label == "偏便宜" and ext_label in {"回檔區", "合理"}:
        return "偏便宜"
    if ext_label == "回檔區" and val_label != "偏貴":
        return "偏便宜"
    return "合理"


# ── B. 等哪裡 ─────────────────────────────────────────────────────────────────
def _support_levels(adj, raw, raw_highs, current, cfg, missing) -> list[SupportLevel]:
    out: list[SupportLevel] = []
    # Dynamic (MAs on ADJUSTED close) — only those below current count as support.
    for n, kind in ((60, "dynamic_ma60"), (200, "dynamic_ma200")):
        ma = _ma(adj, n)
        if ma and ma < current:
            out.append(SupportLevel(kind, round(ma, 4), round(ma / current - 1.0, 4)))
    # Structural (RAW close) — recent consolidation low + prior breakout high (neckline).
    win = int(cfg.get("structural_lookback", 60))
    if raw and len(raw) >= 20:
        box_low = min(raw[-win:]) if len(raw) >= win else min(raw)
        if box_low < current:
            out.append(SupportLevel("structural_box_low", round(box_low, 4), round(box_low / current - 1.0, 4)))
    if raw_highs and len(raw_highs) >= 40:
        # Breakout neckline: prior consolidation high (excluding the most recent ~20 bars), which
        # flips to support after a breakout (support/resistance flip).
        neckline = max(raw_highs[-win:-20]) if len(raw_highs) >= win else max(raw_highs[:-20])
        if neckline and neckline < current:
            out.append(SupportLevel("structural_neckline", round(neckline, 4), round(neckline / current - 1.0, 4)))
    if not out:
        missing.append("supports")
    return sorted(out, key=lambda s: s.pct_below, reverse=True)   # nearest-below first


def _confluence_zones(supports: list[SupportLevel], cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A dynamic MA and a structural level within tolerance (% of price) = high-probability zone."""
    tol = float(cfg.get("confluence_tolerance_pct", 0.02))
    zones: list[dict[str, Any]] = []
    dyn = [s for s in supports if s.kind.startswith("dynamic")]
    stru = [s for s in supports if s.kind.startswith("structural")]
    for d in dyn:
        for s in stru:
            if abs(d.pct_below - s.pct_below) <= tol:
                lo, hi = sorted((d.price, s.price))
                zones.append({"low": round(lo, 4), "high": round(hi, 4),
                              "pct_below": round(max(d.pct_below, s.pct_below), 4),
                              "kinds": [d.kind, s.kind]})
    return zones


# ── C. 能不能加 ───────────────────────────────────────────────────────────────
def _structure_status(adj, raw_lows, current, cfg, missing) -> str:
    ma20 = _ma(adj, 20)
    ma60 = _ma(adj, 60)
    if ma20 is None and ma60 is None:
        missing.append("structure")
        return "unknown"
    # Invalidated: lost the mid-term MA or the recent swing low. Weakening: lost the short MA.
    swing_low = min(raw_lows[-int(cfg.get("structural_lookback", 60)):]) if raw_lows and len(raw_lows) >= 20 else None
    if (ma60 and current < ma60) or (swing_low and current < swing_low):
        return "invalidated"
    if ma20 and current < ma20:
        return "weakening"
    return "intact"


def _add_on_context(structure: str, supports: list[SupportLevel], volumes, current, cfg) -> dict[str, Any]:
    near = float(cfg.get("at_support_pct", 0.03))
    at_support = any(abs(s.pct_below) <= near for s in supports)
    vol_ok = None
    if volumes and len(volumes) >= 21:
        avg20 = sum(volumes[-21:-1]) / 20.0
        vol_ok = bool(avg20 > 0 and volumes[-1] >= avg20 * float(cfg.get("volume_confirm_mult", 1.0)))
    structure_ok = structure == "intact"
    # Verb-free: only a CONDITION label, never a command.
    if not structure_ok:
        note = "結構轉弱/失效:不在加碼觀察條件內(避免接刀)"
    elif at_support and (vol_ok is None or vol_ok):
        note = "結構完整 + 回檔至支撐 + 量能未背離:符合加碼觀察條件"
    elif at_support:
        note = "回檔至支撐但量能未確認:加碼觀察需待帶量"
    else:
        note = "結構完整但未回檔至支撐:等待回檔觀察區"
    return {"structure_ok": structure_ok, "at_support": at_support, "volume_confirmed": vol_ok, "note": note}


# ── helpers ──────────────────────────────────────────────────────────────────
def _ma(vals: list[float] | None, n: int) -> float | None:
    if not vals or len(vals) < n:
        return None
    window = vals[-n:]
    return sum(window) / len(window)


def _percentile_of_last(hist: list[float] | None, min_n: int) -> float | None:
    """Percentile rank (0-100) of the latest value within its own history."""
    if not hist or len(hist) < min_n:
        return None
    vals = [v for v in hist if isinstance(v, (int, float)) and v == v]
    if len(vals) < min_n:
        return None
    cur = vals[-1]
    below = sum(1 for v in vals if v < cur)
    return 100.0 * below / len(vals)


def _last(vals: list[float] | None) -> float | None:
    return float(vals[-1]) if vals else None


# ── live convenience: assemble the dual-track inputs from the stores ──────────
def entry_context_for_symbol(symbol: str, *, days: int = 280, store=None, pit_store=None, params=None) -> EntryContext:
    """Fetch dual-track inputs (adjusted closes for MAs, raw OHLCV for structural levels,
    PER/PBR history for valuation) and compute the entry context for live single-stock use."""
    import pandas as pd
    from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
    from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore, DEFAULT_PIT_DB_PATH
    from backend.app.services.tw_adjusted_prices import get_adjusted_prices
    from backend.app.services.strategy.canslim.params import load_params

    params = params or load_params()
    store = store or HistoricalDataStore(DEFAULT_DB_PATH)
    pit_store = pit_store or PitFundamentalsStore(DEFAULT_PIT_DB_PATH)

    adj = get_adjusted_prices(symbol, days=days, store=store)
    adj_closes = [r["adj_close"] for r in adj.get("rows", []) if r.get("adj_close") is not None]
    as_of = adj["rows"][-1]["date"] if adj.get("rows") else None
    if as_of is None:
        return EntryContext(symbol=symbol, missing=["price"],
                            data_quality={"adjusted_available": False, "dividend_events": adj.get("events", 0)})

    df = store.get_ohlcv_as_of(symbol, as_of, days)
    def _col(name):
        return pd.to_numeric(df[name], errors="coerce").dropna().tolist() if df is not None and not df.empty else None
    raw_closes, raw_highs, raw_lows, vols = _col("close"), _col("high"), _col("low"), _col("volume")

    per = pit_store.get_per_as_of(symbol, as_of, limit=1300)
    per_h = pd.to_numeric(per["per"], errors="coerce").dropna().tolist() if per is not None and not per.empty else None
    pbr_h = pd.to_numeric(per["pbr"], errors="coerce").dropna().tolist() if per is not None and not per.empty else None

    return compute_entry_context(
        symbol, adj_closes=adj_closes, raw_closes=raw_closes, raw_highs=raw_highs, raw_lows=raw_lows,
        volumes=vols, per_history=per_h, pbr_history=pbr_h, params=params,
        adjusted_available=adj.get("events", 0) > 0, dividend_events=adj.get("events", 0),
    )
