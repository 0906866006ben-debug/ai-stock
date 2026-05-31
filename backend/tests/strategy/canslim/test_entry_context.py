from __future__ import annotations

from backend.app.services.strategy.canslim.entry_context import compute_entry_context
from backend.app.services.strategy.canslim.params import load_params

PARAMS = load_params()


def _ctx(**kw):
    base = dict(
        symbol="TEST", adj_closes=None, raw_closes=None, raw_highs=None, raw_lows=None,
        volumes=None, per_history=None, pbr_history=None, params=PARAMS,
    )
    base.update(kw)
    return compute_entry_context(**base)


def test_extension_overheat_vs_pullback():
    # Price 19% above a flat MA60 -> 延伸過熱.
    hot = [100.0] * 60 + [119.0]
    c = _ctx(adj_closes=hot)
    assert c.extension["label"] == "延伸過熱"
    assert c.extension["pct_from_ma60"] > 0.15
    # Price below MA60 -> 回檔區.
    cold = [100.0] * 60 + [92.0]
    assert _ctx(adj_closes=cold).extension["label"] == "回檔區"


def test_valuation_percentile_expensive_cheap():
    px = [100.0] * 61                                       # provide a current price
    rising_pe = [float(x) for x in range(10, 110)]          # latest = highest -> ~99th pctile
    assert _ctx(adj_closes=px, per_history=rising_pe).valuation["label"] == "偏貴"
    falling_pe = [float(x) for x in range(110, 10, -1)]     # latest = lowest -> 0th pctile
    assert _ctx(adj_closes=px, per_history=falling_pe).valuation["label"] == "偏便宜"


def test_pullback_at_expensive_valuation_is_not_cheap():
    # THE guard: technically at a pullback (below MA60) BUT valuation at 99th pctile -> 偏貴, not 便宜.
    cold = [100.0] * 60 + [92.0]
    expensive = [float(x) for x in range(10, 110)]
    c = _ctx(adj_closes=cold, per_history=expensive)
    assert c.extension["label"] == "回檔區"
    assert c.valuation["label"] == "偏貴"
    assert c.expensiveness == "偏貴"                          # valuation overrides the technical pullback


def test_supports_and_confluence_zone():
    # Build raw series where the box low (~90) and MA60 (~90) coincide -> confluence near -10%.
    adj = [90.0] * 60 + [100.0]                              # MA60 ~ 90.16, current 100
    raw = [90.0] * 60 + [100.0]
    highs = [95.0] * 40 + [100.0] * 21                       # prior high 95 (neckline) below current
    c = _ctx(adj_closes=adj, raw_closes=raw, raw_highs=highs)
    kinds = {s.kind for s in c.supports}
    assert "dynamic_ma60" in kinds and "structural_box_low" in kinds
    assert c.confluence_zones                                # ma60 ~ box_low -> a confluence zone
    assert c.confluence_zones[0]["pct_below"] < 0


def test_structure_status_transitions():
    up = [float(90 + i * 0.2) for i in range(60)] + [104.0]  # above MA20 & MA60 -> intact
    assert _ctx(adj_closes=up).structure_status == "intact"
    # Uptrend (MA20 > MA60) with current below MA20 but above MA60 -> weakening.
    weak = [float(x) for x in range(40, 100)] + [85.0]       # MA20~89.8, MA60~70.9, close 85
    assert _ctx(adj_closes=weak).structure_status == "weakening"
    # Below MA60 -> invalidated.
    broken = [100.0] * 60 + [90.0]
    assert _ctx(adj_closes=broken).structure_status == "invalidated"


def test_add_on_context_gated_by_structure():
    # Broken structure -> NOT in add-on observation (no falling knife), regardless of support.
    broken = [100.0] * 60 + [90.0]
    c = _ctx(adj_closes=broken, raw_closes=broken)
    assert c.add_on_context["structure_ok"] is False
    assert "接刀" in c.add_on_context["note"]


def test_missing_data_omits_reads():
    c = _ctx(adj_closes=[100.0, 101.0])                       # too few for MAs/valuation
    assert "valuation" in c.missing
    assert c.expensiveness in {"unknown", "合理", "偏便宜", "偏貴"}
    assert c.current_price == 101.0


def test_no_price_returns_safe_empty():
    c = _ctx()
    assert c.missing == ["price"] and c.current_price is None
