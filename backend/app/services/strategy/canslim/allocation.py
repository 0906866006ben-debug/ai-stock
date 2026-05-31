"""Capital allocation & position-sizing calculator (Task 1B) — verb-free arithmetic.

Given the USER's inputs (total capital, reserve %, caps) and a chosen durable-quality
watchlist (with per-symbol durability score, ATR, structure status, support/confluence
prices from Task 1A), compute three plain data tables — base allocation, decreasing
pyramiding ladder, and a risk dashboard. It is a CALCULATOR on the user's own numbers,
NOT a recommender: it emits no buy/sell/target/stop command, only quantities the user acts on.

Design (from the Task 1B research):
- Weighting = Quality-Adjusted Risk Parity (QWRP): inverse %-volatility base (IV = price/ATR,
  i.e. 1/ATR%, so a high-priced low-%-vol blue chip is NOT mis-flagged as risky) × a quality
  multiplier from the durability Z-score (MSCI-style transform). Robust vs MVO's estimation error.
- Risk guards (iterative): single-position cap, sector cap; overflow redistributed.
- Reserve capital (dry powder) funds a DECREASING pyramiding ladder (Anti-Martingale, α=0.5)
  anchored to the structural/confluence support prices — never fixed-% Martingale averaging down.
- Structure state machine: Invalidated -> the ladder is frozen and its reserve returned to pool
  (no adding into a broken structure / no falling knife).
- TW microstructure: 1 lot = 1000 shares + odd-lot; broker fee (with discount); a tranche below
  the friction floor is dropped (Insufficient_Friction_Margin) so tiny lots don't bleed to fees.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

LOT = 1000
DEFAULT_FEE = 0.001425          # broker fee per side (before discount)
DEFAULT_TAX = 0.003             # securities tax (sell side; for round-trip reference only)


@dataclass(frozen=True)
class AllocationResult:
    base_matrix: list[dict[str, Any]] = field(default_factory=list)
    ladder_matrix: list[dict[str, Any]] = field(default_factory=list)
    risk_dashboard: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def compute_allocation(
    *,
    total_capital_ntd: float,
    watchlist: list[dict[str, Any]],
    reserve_pct: float = 0.20,
    max_position_pct: float = 0.25,
    sector_limit_pct: float = 0.40,
    fee_discount_rate: float = 0.28,
    min_trade_amt_ntd: float = 15_000.0,
    insufficient_floor_ntd: float = 3_000.0,
    ladder_alpha: float = 0.5,
) -> AllocationResult:
    notes: list[str] = []
    fee = DEFAULT_FEE * (1.0 - max(0.0, min(1.0, fee_discount_rate)))
    items = [dict(it) for it in watchlist if _f(it.get("current_price")) and _f(it.get("current_price")) > 0]
    if not items or total_capital_ntd <= 0:
        return AllocationResult(notes=["no usable watchlist / capital"])

    active_capital = total_capital_ntd * (1.0 - reserve_pct)

    # ── QWRP weights ─────────────────────────────────────────────────────────
    scores = [_f(it.get("durability_score")) for it in items if _f(it.get("durability_score")) is not None]
    mean = sum(scores) / len(scores) if scores else 0.0
    std = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5 if len(scores) > 1 else 0.0
    raw: dict[str, float] = {}
    for it in items:
        price = _f(it["current_price"])
        atr = _f(it.get("atr_14_pit"))
        atr_pct = (atr / price) if (atr and price) else None
        iv = (1.0 / atr_pct) if atr_pct and atr_pct > 0 else 1.0          # inverse %-vol; flat if ATR missing
        z = ((_f(it.get("durability_score")) - mean) / std) if (std > 0 and _f(it.get("durability_score")) is not None) else 0.0
        z = max(-3.0, min(3.0, z))                                        # winsorize
        mult = (1.0 + z) if z >= 0 else 1.0 / (1.0 - z)                   # MSCI-style quality multiplier (>0)
        raw[it["symbol"]] = max(0.0, iv * mult)
    weights = _normalize(raw)
    weights = _apply_caps(weights, items, max_position_pct, sector_limit_pct, notes)

    # ── Base allocation (微結構轉換) ─────────────────────────────────────────
    base_matrix: list[dict[str, Any]] = []
    by_symbol = {it["symbol"]: it for it in items}
    sector_exposure: dict[str, float] = {}
    deployed = 0.0
    for sym, w in weights.items():
        it = by_symbol[sym]
        price = _f(it["current_price"])
        target_amt = active_capital * w
        shares = int(target_amt // price)
        if shares <= 0:
            base_matrix.append({"symbol": sym, "target_lots": 0, "target_odd": 0,
                                "est_capital_req": 0.0, "final_weight": round(w, 4), "status": "Below_Min"})
            continue
        est = shares * price * (1.0 + fee)
        deployed += est
        sector_exposure[it.get("sector", "Unknown")] = sector_exposure.get(it.get("sector", "Unknown"), 0.0) + est
        base_matrix.append({
            "symbol": sym, "target_lots": shares // LOT, "target_odd": shares % LOT,
            "est_capital_req": round(est, 0), "final_weight": round(w, 4),
            "status": "Allocated" if target_amt >= min_trade_amt_ntd else "Odd_Lot_Only",
        })

    # ── Decreasing pyramiding ladder (reserve, structure-gated) ──────────────
    ladder_matrix: list[dict[str, Any]] = []
    frozen: list[str] = []
    reserve_pool_returned = 0.0
    for sym, w in weights.items():
        it = by_symbol[sym]
        r_amt = total_capital_ntd * reserve_pct * w
        status = str(it.get("structure_status", "unknown")).lower()
        add_levels = _add_levels(it)
        if status == "invalidated":
            frozen.append(sym)
            reserve_pool_returned += r_amt
            ladder_matrix.append({"symbol": sym, "level": "L1", "target_price": None, "target_shares": 0,
                                  "target_lots": 0, "target_odd": 0, "est_capital_req": 0.0,
                                  "condition_flag": "Invalidated_Frozen"})
            continue
        if r_amt <= 0 or not add_levels:
            continue
        flag = "Armed_Intact" if status == "intact" else "Armed_Weakening"
        n = len(add_levels)
        denom = sum(ladder_alpha ** k for k in range(1, n + 1))
        for k, lvl_price in enumerate(add_levels, start=1):
            amt_k = r_amt * (ladder_alpha ** k) / denom if denom > 0 else 0.0
            if amt_k < insufficient_floor_ntd:
                reserve_pool_returned += amt_k
                ladder_matrix.append({"symbol": sym, "level": f"L{k}", "target_price": round(lvl_price, 2),
                                      "target_shares": 0, "target_lots": 0, "target_odd": 0,
                                      "est_capital_req": 0.0, "condition_flag": "Insufficient_Friction_Margin"})
                continue
            shares = int(amt_k // lvl_price) if lvl_price > 0 else 0
            est = shares * lvl_price * (1.0 + fee)
            ladder_matrix.append({
                "symbol": sym, "level": f"L{k}", "target_price": round(lvl_price, 2),
                "target_shares": shares, "target_lots": shares // LOT, "target_odd": shares % LOT,
                "est_capital_req": round(est, 0),
                "condition_flag": flag + ("" if amt_k >= min_trade_amt_ntd else "_OddLot"),
            })

    # Sector exposure on the SAME basis as the cap (% of deployed/active capital, from weights).
    sector_w: dict[str, float] = {}
    for sym, w in weights.items():
        sector_w[by_symbol[sym].get("sector", "Unknown")] = sector_w.get(by_symbol[sym].get("sector", "Unknown"), 0.0) + w
    max_sector = max(sector_w.items(), key=lambda kv: kv[1]) if sector_w else ("-", 0.0)
    max_pos_w = max((r["final_weight"] for r in base_matrix), default=0.0)
    risk_dashboard = {
        "total_active_capital": round(deployed, 0),
        "total_active_pct": round(deployed / total_capital_ntd, 4) if total_capital_ntd else 0.0,
        "total_reserve_capital": round(total_capital_ntd * reserve_pct, 0),
        "reserve_returned_to_pool": round(reserve_pool_returned, 0),
        "max_position_pct_active": round(max_pos_w, 4),
        "max_sector": max_sector[0],
        "max_sector_pct": round(max_sector[1], 4),          # active-relative, matches sector_limit_pct
        "sector_limit_pct": sector_limit_pct,
        "n_positions": sum(1 for r in base_matrix if r["status"] in {"Allocated", "Odd_Lot_Only"}),
        "frozen_symbols": frozen,
        "fee_effective": round(fee, 6),
    }
    return AllocationResult(base_matrix=base_matrix, ladder_matrix=ladder_matrix,
                            risk_dashboard=risk_dashboard, notes=notes)


# ── helpers ──────────────────────────────────────────────────────────────────
def _apply_caps(weights, items, max_pos, sector_limit, notes, max_iter=50):
    """Iteratively enforce single-position + sector caps, redistributing overflow. Caps are
    relative to the deployed (non-reserve) capital. Caps that are jointly infeasible for the
    given count are relaxed to the feasibility floor (1/n) and noted, so the result never
    silently violates a stated cap."""
    sector_of = {it["symbol"]: it.get("sector", "Unknown") for it in items}
    w = dict(weights)
    n = len(w)
    floor = 1.0 / n if n else 1.0
    if max_pos < floor - 1e-9:
        notes.append(f"max_position_pct {max_pos:.0%} infeasible for {n} positions; relaxed to {floor:.1%}")
        max_pos = floor
    for _ in range(max_iter):
        changed = False
        # single-position cap
        over = {s: v for s, v in w.items() if v > max_pos + 1e-9}
        if over:
            changed = True
            excess = sum(v - max_pos for s, v in over.items())
            for s in over:
                w[s] = max_pos
            free = {s: v for s, v in w.items() if v < max_pos - 1e-9}
            tot = sum(free.values())
            if tot > 0:
                for s in free:
                    w[s] += excess * free[s] / tot
            else:
                break
        # sector cap
        sector_sum: dict[str, float] = {}
        for s, v in w.items():
            sector_sum[sector_of[s]] = sector_sum.get(sector_of[s], 0.0) + v
        over_sec = {sec: tot for sec, tot in sector_sum.items() if tot > sector_limit + 1e-9}
        if over_sec:
            changed = True
            for sec, tot in over_sec.items():
                scale = sector_limit / tot
                for s in [x for x in w if sector_of[x] == sec]:
                    w[s] *= scale
            w = _normalize(w)   # re-normalize; next iteration re-checks single-pos cap
        if not changed:
            break
    else:
        notes.append("cap redistribution did not fully converge (caps may be jointly infeasible)")
    return _normalize(w)


def _add_levels(item: dict[str, Any]) -> list[float]:
    """Support/confluence prices below current, descending — the pyramiding anchors."""
    cur = _f(item.get("current_price"))
    levels: list[float] = []
    for z in item.get("confluence_zones", []) or []:
        lo = _f(z.get("low")) if isinstance(z, dict) else _f(z)
        if lo and cur and lo < cur:
            levels.append(lo)
    for p in item.get("add_levels", []) or []:
        pf = _f(p)
        if pf and cur and pf < cur:
            levels.append(pf)
    # dedup + sort descending (nearest pullback first)
    uniq = sorted({round(x, 2) for x in levels}, reverse=True)
    return uniq


def _normalize(raw: dict[str, float]) -> dict[str, float]:
    tot = sum(raw.values())
    return {k: (v / tot if tot > 0 else 0.0) for k, v in raw.items()}


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── live convenience: assemble per-symbol inputs from Task 1A + durability ────
def allocate_for_watchlist(symbols: list[str], params: dict[str, Any], *, sectors: dict[str, str] | None = None,
                           store=None, pit_store=None, model_params=None) -> AllocationResult:
    """Assemble the per-symbol inputs (durability score, ATR, structure, support/confluence
    prices, current price) from Task 1A's entry_context + the durability score, then run the
    pure allocation calculator. `params` carries the user's portfolio_parameters."""
    from datetime import date
    from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
    from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore, DEFAULT_PIT_DB_PATH
    from backend.app.services.strategy.canslim.params import load_params
    from backend.app.services.strategy.canslim.entry_context import entry_context_for_symbol

    model_params = model_params or load_params()
    store = store or HistoricalDataStore(DEFAULT_DB_PATH)
    pit_store = pit_store or PitFundamentalsStore(DEFAULT_PIT_DB_PATH)
    sectors = sectors or {}
    as_of = date.today().strftime("%Y-%m-%d")

    watchlist: list[dict[str, Any]] = []
    for sym in symbols:
        sym = str(sym).strip()
        try:
            ec = entry_context_for_symbol(sym, store=store, pit_store=pit_store, params=model_params)
        except Exception:
            continue
        if ec.current_price is None:
            continue
        dur = _durability_score(sym, pit_store, model_params, as_of)
        watchlist.append({
            "symbol": sym,
            "sector": sectors.get(sym, "Unknown"),
            "current_price": ec.current_price,
            "durability_score": dur,
            "atr_14_pit": ec.atr_14,
            "structure_status": ec.structure_status,
            "confluence_zones": [{"low": z.get("low")} for z in ec.confluence_zones],
            "add_levels": [s.price for s in ec.supports],   # support ladder (already below current)
        })

    pp = params or {}
    return compute_allocation(
        total_capital_ntd=float(pp.get("total_capital_ntd", 0) or 0),
        watchlist=watchlist,
        reserve_pct=float(pp.get("reserve_pct", 0.20)),
        max_position_pct=float(pp.get("max_position_pct", 0.25)),
        sector_limit_pct=float(pp.get("sector_limit_pct", 0.40)),
        fee_discount_rate=float(pp.get("fee_discount_rate", 0.28)),
        min_trade_amt_ntd=float(pp.get("min_trade_amt_ntd", 15_000)),
    )


def _durability_score(sym: str, pit_store, model_params, as_of: str) -> float | None:
    from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs
    from backend.app.services.strategy.canslim.durability import compute_durability
    try:
        fin = pit_store.get_financials_as_of(sym, as_of, limit=20)
        bs = pit_store.get_balance_sheet_as_of(sym, as_of, limit=8)
        cf = pit_store.get_cash_flow_as_of(sym, as_of, limit=12) if hasattr(pit_store, "get_cash_flow_as_of") else None
        detail, fin_metrics, _ = build_pit_inputs(sym, as_of, pit_store)
        res = compute_durability(fin_metrics=fin_metrics, detail=detail, financials=fin,
                                 balance_sheet=bs, params=model_params, cash_flow=cf)
        return float(res.score) if res.components else None
    except Exception:
        return None
