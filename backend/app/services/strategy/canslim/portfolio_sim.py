"""Portfolio-level CAN SLIM overlay research tools.

Phase N is measurement-only. It consumes M3 tagged trades and simulates a
portfolio equity curve under optional portfolio overlays. No signal, score,
grade, YAML, or production gate is changed here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH, HistoricalDataStore

BAD_YEARS = (2011, 2012, 2016, 2018, 2022)
REGIME_SIZE = {"risk_on": 1.0, "risk_off": 0.5, "severe": 0.0, "unknown": 1.0}
NAMED_CYCLES = (
    ("2011-H2-euro", "2011-07-01", "2011-12-31"),
    ("2015-H2-correction", "2015-07-01", "2015-12-31"),
    ("2018-Q4-selloff", "2018-10-01", "2018-12-31"),
    ("2020-COVID", "2020-02-01", "2020-06-30"),
    ("2022-bear", "2022-01-01", "2022-12-31"),
    ("2023-24-bull", "2023-01-01", "2024-12-31"),
)


@dataclass(frozen=True)
class OverlayConfig:
    name: str = "baseline"
    max_concurrent: int = 10
    ma_long: int | None = None
    drawdown_halt: float | None = None
    regime_scaled: bool = False


@dataclass(frozen=True)
class PortfolioResult:
    name: str
    metrics: dict[str, Any]
    annual_returns: dict[str, float]
    named_cycle_returns: dict[str, float]
    equity_curve: pd.DataFrame
    accepted_trades: pd.DataFrame
    skipped_trades: pd.DataFrame


def run_overlay_report(
    *,
    tagged_trades_csv: Path | str,
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    output_dir: Path | str = "artifacts/canslim_portfolio_overlay",
    max_concurrent: int = 10,
    initial_capital: float = 1.0,
) -> dict[str, Any]:
    trades = pd.read_csv(tagged_trades_csv)
    store = HistoricalDataStore(ohlcv_db_path)
    market = load_taiex_trend(store, trades["entry_date"].min(), trades["entry_date"].max(), ma_windows=(150, 200))
    configs = _overlay_configs(max_concurrent=max_concurrent)
    results = [
        simulate_portfolio(
            trades,
            config=config,
            market_trend=market,
            initial_capital=initial_capital,
        )
        for config in configs
    ]
    report = build_overlay_report(results)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "overlay_report.json"
    md_path = out_dir / "overlay_report.md"
    report["artifact_json"] = str(json_path)
    report["artifact_md"] = str(md_path)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return report


def simulate_portfolio(
    trades: pd.DataFrame,
    *,
    config: OverlayConfig | None = None,
    market_trend: pd.DataFrame | None = None,
    initial_capital: float = 1.0,
) -> PortfolioResult:
    cfg = config or OverlayConfig()
    prepared = prepare_trades(trades)
    if prepared.empty:
        empty_curve = pd.DataFrame(columns=["date", "equity", "daily_return", "drawdown"])
        return PortfolioResult(cfg.name, _metrics(empty_curve, 0, 0), {}, {}, empty_curve, prepared, prepared)

    dates = _calendar(prepared["entry_date"].min(), prepared["exit_date"].max())
    entries_by_date = {date: frame for date, frame in prepared.groupby("entry_date", sort=False)}
    exits_by_date: dict[str, list[dict[str, Any]]] = {}
    active: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    equity = float(initial_capital)
    peak = equity
    halted = False
    rows: list[dict[str, Any]] = []
    position_fraction = 1.0 / float(cfg.max_concurrent)

    for date in dates:
        for pos in exits_by_date.pop(date, []):
            equity *= 1.0 + float(pos["portfolio_return"])
            active = [item for item in active if item["id"] != pos["id"]]
        peak = max(peak, equity)
        dd = equity / peak - 1.0 if peak else 0.0
        if cfg.drawdown_halt is not None:
            if not halted and dd <= -float(cfg.drawdown_halt):
                halted = True
            elif halted and dd >= -float(cfg.drawdown_halt) / 2.0:
                halted = False

        day_entries = entries_by_date.get(date)
        if day_entries is not None:
            for trade in day_entries.to_dict("records"):
                reason = _entry_skip_reason(trade, active, cfg, market_trend, halted)
                if reason is not None:
                    item = dict(trade)
                    item["skip_reason"] = reason
                    skipped.append(item)
                    continue
                multiplier = _regime_multiplier(trade, cfg)
                if multiplier <= 0:
                    item = dict(trade)
                    item["skip_reason"] = "regime_size_zero"
                    skipped.append(item)
                    continue
                item = dict(trade)
                item["id"] = len(accepted) + len(skipped) + len(active) + 1
                item["position_fraction"] = position_fraction * multiplier
                item["portfolio_return"] = float(item["net_return_pct"]) * item["position_fraction"]
                active.append(item)
                accepted.append(item)
                exits_by_date.setdefault(str(item["exit_date"]), []).append(item)

        rows.append({"date": date, "equity": equity, "drawdown": dd, "active_positions": len(active)})

    curve = pd.DataFrame(rows)
    curve["daily_return"] = curve["equity"].pct_change().fillna(0.0)
    accepted_df = pd.DataFrame(accepted)
    skipped_df = pd.DataFrame(skipped)
    return PortfolioResult(
        name=cfg.name,
        metrics=_metrics(curve, accepted_count=len(accepted_df), skipped_count=len(skipped_df)),
        annual_returns=period_returns(curve, "Y"),
        named_cycle_returns=named_cycle_returns(curve),
        equity_curve=curve,
        accepted_trades=accepted_df,
        skipped_trades=skipped_df,
    )


def prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    out = trades.copy()
    out["entry_date"] = pd.to_datetime(out["entry_date"]).dt.strftime("%Y-%m-%d")
    holding = pd.to_numeric(out.get("holding_days", 0), errors="coerce").fillna(0).astype(int).clip(lower=0)
    out["exit_date"] = (pd.to_datetime(out["entry_date"]) + pd.to_timedelta(holding, unit="D")).dt.strftime("%Y-%m-%d")
    out["net_return_pct"] = pd.to_numeric(out["net_return_pct"], errors="coerce").fillna(0.0)
    return out.sort_values(["entry_date", "stock_id"]).reset_index(drop=True)


def load_taiex_trend(store: HistoricalDataStore, start_date: str, end_date: str, *, ma_windows: tuple[int, ...]) -> pd.DataFrame:
    buffer_days = max(ma_windows) * 3
    load_start = (pd.Timestamp(start_date) - pd.Timedelta(days=buffer_days)).strftime("%Y-%m-%d")
    frame = store.get_ohlcv("TAIEX", load_start, end_date)
    if frame.empty:
        return pd.DataFrame(columns=["date"])
    out = frame[["date", "close"]].copy().sort_values("date")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    for window in ma_windows:
        out[f"ma_{window}"] = out["close"].rolling(window, min_periods=window).mean()
        out[f"ma_{window}_slope"] = out[f"ma_{window}"].diff(5)
    return out[out["date"] >= start_date].reset_index(drop=True)


def period_returns(curve: pd.DataFrame, freq: str) -> dict[str, float]:
    if curve.empty:
        return {}
    frame = curve.copy()
    frame["date_ts"] = pd.to_datetime(frame["date"])
    if freq == "Y":
        groups = frame.groupby(frame["date_ts"].dt.year, sort=True)
        return {str(year): round(_period_return(group), 4) for year, group in groups}
    raise ValueError(f"Unsupported freq: {freq}")


def named_cycle_returns(curve: pd.DataFrame) -> dict[str, float]:
    if curve.empty:
        return {}
    out: dict[str, float] = {}
    for name, start, end in NAMED_CYCLES:
        sub = curve[(curve["date"] >= start) & (curve["date"] <= end)]
        out[name] = round(_period_return(sub), 4) if not sub.empty else 0.0
    return out


def build_overlay_report(results: list[PortfolioResult]) -> dict[str, Any]:
    baseline = next((result for result in results if result.name == "baseline"), results[0])
    rows = []
    for result in results:
        row = {
            "name": result.name,
            **result.metrics,
            "bad_year_return": _sum_years(result.annual_returns, BAD_YEARS),
            "good_year_return": _sum_good_years(result.annual_returns, BAD_YEARS),
            "bad_year_improvement_vs_baseline": round(
                _sum_years(result.annual_returns, BAD_YEARS) - _sum_years(baseline.annual_returns, BAD_YEARS),
                4,
            ),
            "cagr_sacrifice_vs_baseline": round(float(baseline.metrics["cagr"]) - float(result.metrics["cagr"]), 4),
        }
        rows.append(row)
    return {
        "comparison": rows,
        "annual_returns": {result.name: result.annual_returns for result in results},
        "named_cycle_returns": {result.name: result.named_cycle_returns for result in results},
        "verdict": _verdict(rows),
    }


def _overlay_configs(*, max_concurrent: int) -> list[OverlayConfig]:
    configs = [OverlayConfig(name="baseline", max_concurrent=max_concurrent)]
    configs.extend(OverlayConfig(name=f"O1_TAIEX_MA{ma}", max_concurrent=max_concurrent, ma_long=ma) for ma in (150, 200))
    configs.extend(OverlayConfig(name=f"O2_DD_{int(dd*100)}", max_concurrent=max_concurrent, drawdown_halt=dd) for dd in (0.10, 0.15, 0.20))
    configs.append(OverlayConfig(name="O3_regime_scaled", max_concurrent=max_concurrent, regime_scaled=True))
    for ma in (150, 200):
        for dd in (0.10, 0.15, 0.20):
            configs.append(OverlayConfig(name=f"O1_MA{ma}_O2_DD_{int(dd*100)}", max_concurrent=max_concurrent, ma_long=ma, drawdown_halt=dd))
    return configs


def _entry_skip_reason(
    trade: dict[str, Any],
    active: list[dict[str, Any]],
    cfg: OverlayConfig,
    market_trend: pd.DataFrame | None,
    halted: bool,
) -> str | None:
    if len(active) >= cfg.max_concurrent:
        return "max_concurrent"
    if cfg.ma_long is not None and not _market_allows_entry(str(trade["entry_date"]), market_trend, cfg.ma_long):
        return f"market_trend_ma_{cfg.ma_long}"
    if halted:
        return "drawdown_circuit"
    return None


def _market_allows_entry(entry_date: str, market_trend: pd.DataFrame | None, ma_long: int) -> bool:
    if market_trend is None or market_trend.empty:
        return True
    available = market_trend[market_trend["date"] <= entry_date]
    if available.empty:
        return True
    latest = available.iloc[-1]
    ma = latest.get(f"ma_{ma_long}")
    slope = latest.get(f"ma_{ma_long}_slope")
    if pd.isna(ma) or pd.isna(slope):
        return True
    return bool(float(latest["close"]) >= float(ma) and float(slope) >= 0.0)


def _regime_multiplier(trade: dict[str, Any], cfg: OverlayConfig) -> float:
    if not cfg.regime_scaled:
        return 1.0
    return float(REGIME_SIZE.get(str(trade.get("regime_bucket_at_entry")), 1.0))


def _calendar(start_date: str, end_date: str) -> list[str]:
    return pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d").tolist()


def _metrics(curve: pd.DataFrame, accepted_count: int, skipped_count: int) -> dict[str, Any]:
    if curve.empty:
        return {
            "cagr": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "exposure_pct": 0.0,
            "accepted_trades": int(accepted_count),
            "skipped_trades": int(skipped_count),
        }
    start = pd.Timestamp(curve["date"].iloc[0])
    end = pd.Timestamp(curve["date"].iloc[-1])
    years = max((end - start).days / 365.25, 1 / 365.25)
    ending = float(curve["equity"].iloc[-1])
    beginning = float(curve["equity"].iloc[0])
    cagr = ending / beginning
    cagr = cagr ** (1.0 / years) - 1.0 if beginning > 0 and cagr > 0 else -1.0
    max_dd = float(curve["drawdown"].min()) if "drawdown" in curve else 0.0
    returns = pd.to_numeric(curve["daily_return"], errors="coerce").dropna()
    sharpe = _ratio(returns.mean(), returns.std(ddof=0)) * math.sqrt(252) if not returns.empty else 0.0
    downside = returns[returns < 0]
    sortino = _ratio(returns.mean(), downside.std(ddof=0)) * math.sqrt(252) if not downside.empty else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    exposure = float((pd.to_numeric(curve.get("active_positions", 0), errors="coerce").fillna(0) > 0).mean())
    return {
        "cagr": round(cagr, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "exposure_pct": round(exposure, 4),
        "accepted_trades": int(accepted_count),
        "skipped_trades": int(skipped_count),
    }


def _period_return(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    start = float(frame["equity"].iloc[0])
    end = float(frame["equity"].iloc[-1])
    return end / start - 1.0 if start > 0 else 0.0


def _ratio(num: float, denom: float) -> float:
    return float(num / denom) if denom and not pd.isna(denom) else 0.0


def _sum_years(annual_returns: dict[str, float], years: tuple[int, ...]) -> float:
    return round(sum(float(annual_returns.get(str(year), 0.0)) for year in years), 4)


def _sum_good_years(annual_returns: dict[str, float], bad_years: tuple[int, ...]) -> float:
    bad = {str(year) for year in bad_years}
    return round(sum(float(value) for year, value in annual_returns.items() if year not in bad), 4)


def _verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = rows[0]
    candidates = [
        row for row in rows[1:]
        if row["max_drawdown"] > baseline["max_drawdown"]
        and row["bad_year_improvement_vs_baseline"] > 0
    ]
    if not candidates:
        return {"selected": None, "reason": "No overlay improved bad-year returns and max drawdown versus baseline."}
    candidates.sort(key=lambda row: (-row["calmar"], row["cagr_sacrifice_vs_baseline"], -row["bad_year_improvement_vs_baseline"]))
    selected = candidates[0]
    return {
        "selected": selected["name"],
        "reason": "Selected by improved maxDD/bad-year loss with best Calmar and lowest CAGR sacrifice among candidates.",
    }


def _markdown_report(report: dict[str, Any]) -> str:
    columns = [
        "name",
        "cagr",
        "max_drawdown",
        "calmar",
        "sharpe",
        "bad_year_improvement_vs_baseline",
        "cagr_sacrifice_vs_baseline",
        "accepted_trades",
        "skipped_trades",
    ]
    lines = [
        "# CAN SLIM Portfolio Overlay Report",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        _markdown_table(report["comparison"], columns),
        "",
    ]
    return "\n".join(lines)


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows_"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(str(row.get(column, "")) for column in columns) + " |" for row in rows]
    return "\n".join([header, sep, *body])
