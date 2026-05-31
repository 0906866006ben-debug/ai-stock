from __future__ import annotations

from backend.app.services.strategy.canslim.allocation import compute_allocation


def _item(sym, price, dur, atr, sector="X", structure="intact", levels=None):
    return {"symbol": sym, "sector": sector, "current_price": price, "durability_score": dur,
            "atr_14_pit": atr, "structure_status": structure, "add_levels": levels or []}


def _w(res, sym):
    return next(r["final_weight"] for r in res.base_matrix if r["symbol"] == sym)


def test_qwrp_tilts_to_high_quality_low_vol():
    # A: high durability + low vol; B: low durability + high vol. A should dominate.
    wl = [_item("A", 100, 90, 1.0), _item("B", 100, 50, 4.0)]
    res = compute_allocation(total_capital_ntd=1_000_000, watchlist=wl, reserve_pct=0.2,
                             max_position_pct=1.0, sector_limit_pct=1.0)
    assert _w(res, "A") > _w(res, "B")
    assert _w(res, "A") > 0.8


def test_single_position_cap_enforced():
    wl = [_item("A", 100, 95, 0.5), _item("B", 100, 50, 4.0), _item("C", 100, 50, 4.0)]
    res = compute_allocation(total_capital_ntd=1_000_000, watchlist=wl, reserve_pct=0.2,
                             max_position_pct=0.4, sector_limit_pct=1.0)
    assert all(r["final_weight"] <= 0.4 + 1e-6 for r in res.base_matrix)
    assert abs(sum(r["final_weight"] for r in res.base_matrix) - 1.0) < 1e-6


def test_sector_cap_enforced():
    wl = [_item("A", 100, 90, 1.0, sector="Semi"), _item("B", 100, 88, 1.0, sector="Semi"),
          _item("C", 100, 50, 1.0, sector="Other")]
    res = compute_allocation(total_capital_ntd=1_000_000, watchlist=wl, reserve_pct=0.2,
                             max_position_pct=1.0, sector_limit_pct=0.5)
    semi = _w(res, "A") + _w(res, "B")
    assert semi <= 0.5 + 1e-6


def test_lot_and_odd_conversion():
    # active = 156250 * 0.8 = 125000; single stock @100 -> 1250 shares -> 1 lot + 250 odd.
    wl = [_item("A", 100, 80, 1.0)]
    res = compute_allocation(total_capital_ntd=156_250, watchlist=wl, reserve_pct=0.2,
                             max_position_pct=1.0, sector_limit_pct=1.0, fee_discount_rate=1.0)
    row = res.base_matrix[0]
    assert row["target_lots"] == 1 and row["target_odd"] == 250


def test_pyramiding_ladder_is_decreasing_and_anchored():
    wl = [_item("A", 100, 80, 1.0, structure="intact", levels=[90, 80, 70])]
    res = compute_allocation(total_capital_ntd=500_000, watchlist=wl, reserve_pct=0.3,
                             max_position_pct=1.0, sector_limit_pct=1.0)
    ladder = [r for r in res.ladder_matrix if r["symbol"] == "A"]
    assert [r["target_price"] for r in ladder] == [90.0, 80.0, 70.0]      # anchored, descending
    ests = [r["est_capital_req"] for r in ladder]
    assert ests[0] > ests[1] > ests[2]                                    # decreasing (Anti-Martingale)
    assert all(r["condition_flag"].startswith("Armed_Intact") for r in ladder)


def test_invalidated_structure_freezes_ladder():
    wl = [_item("A", 100, 80, 1.0, structure="invalidated", levels=[90, 80])]
    res = compute_allocation(total_capital_ntd=500_000, watchlist=wl, reserve_pct=0.3,
                             max_position_pct=1.0, sector_limit_pct=1.0)
    frozen = [r for r in res.ladder_matrix if r["condition_flag"] == "Invalidated_Frozen"]
    assert frozen and frozen[0]["target_shares"] == 0
    assert "A" in res.risk_dashboard["frozen_symbols"]
    assert res.risk_dashboard["reserve_returned_to_pool"] > 0             # locked reserve returned


def test_insufficient_friction_margin_dropped():
    # Tiny reserve -> the deepest tranche falls below the friction floor (3000) -> dropped.
    wl = [_item("A", 100, 80, 1.0, structure="intact", levels=[90, 80, 70])]
    res = compute_allocation(total_capital_ntd=100_000, watchlist=wl, reserve_pct=0.1,
                             max_position_pct=1.0, sector_limit_pct=1.0,
                             min_trade_amt_ntd=15_000, insufficient_floor_ntd=3_000)
    flags = [r["condition_flag"] for r in res.ladder_matrix if r["symbol"] == "A"]
    assert any("Insufficient_Friction_Margin" == f for f in flags)


def test_no_capital_or_empty_is_safe():
    assert compute_allocation(total_capital_ntd=0, watchlist=[_item("A", 100, 80, 1.0)]).notes
    assert compute_allocation(total_capital_ntd=1_000_000, watchlist=[]).notes
