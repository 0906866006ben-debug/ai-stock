"""Dataclasses shared by the v2-preview backtest runner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class BacktestConfig:
    symbols: list[str]
    start: date
    end: date
    strategy: str = "v2_quant"
    initial_capital: Decimal = Decimal("1000000")
    base_position_pct: Decimal = Decimal("0.10")
    max_position_pct: Decimal = Decimal("0.25")
    min_signal: int = 60
    min_confidence: int = 45
    max_risk: int = 75
    require_rr_pass: bool = False
    allow_fundamental_unknown: bool = True
    max_holding_days: int = 20
    forward_days: int = 20
    warmup_bars: int = 140
    fee_rate: Decimal = Decimal("0.001425")
    tax_rate: Decimal = Decimal("0.003")
    slippage_bps: Decimal = Decimal("5")
    data_dir: Optional[Path] = None
    output_dir: Path = Path("backend/backtest_results")
    allow_mock: bool = False


@dataclass(frozen=True)
class DailySignal:
    symbol: str
    signal_date: date
    close: Decimal
    signal: int
    confidence: int
    risk: int
    direction: str
    fundamental_gate: str
    rr_ratio: Optional[Decimal]
    rr_pass: bool
    kelly_fraction: Decimal
    poc_price: Optional[Decimal]
    poc_breakdown: bool
    two_b_status: str
    two_b_confirmed: bool
    ma20_p_crit: Optional[Decimal]
    ma60_p_crit: Optional[Decimal]
    forced_exit: bool
    forced_exit_reason: Optional[str]
    entry_candidate: bool
    reject_reason: Optional[str]
    data_quality: str


@dataclass(frozen=True)
class Trade:
    trade_id: str
    symbol: str
    signal_date: date
    entry_date: date
    entry_price: Decimal
    exit_date: date
    exit_price: Decimal
    exit_reason: str
    shares: Decimal
    position_pct: Decimal
    gross_return_pct: Decimal
    net_return_pct: Decimal
    gross_pnl: Decimal
    fees: Decimal
    tax: Decimal
    net_pnl: Decimal
    holding_days: int
    signal: int
    confidence: int
    risk: int
    rr_ratio: Optional[Decimal]
    rr_pass: bool
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    two_b_status: str
    poc_price: Optional[Decimal]
    hypothesis_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HypothesisBacktestRow:
    hypothesis_id: str
    module: str
    topic: str
    description: str
    event_count: int
    hit_count: int
    hit_rate: Optional[Decimal]
    avg_forward_return_pct: Optional[Decimal]
    avg_trade_return_pct: Optional[Decimal]
    sample_type: Literal["forward_return", "trade_return", "none"]


@dataclass(frozen=True)
class BacktestSummary:
    strategy: str
    start: date
    end: date
    symbols: list[str]
    initial_capital: Decimal
    final_equity: Decimal
    total_return_pct: Decimal
    annualized_return_pct: Optional[Decimal]
    max_drawdown_pct: Decimal
    sharpe_ratio: Optional[Decimal]
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[Decimal]
    avg_trade_return_pct: Optional[Decimal]
    expectancy_pct: Optional[Decimal]
    profit_factor: Optional[Decimal]
    avg_holding_days: Optional[Decimal]
    exposure_pct: Optional[Decimal]


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    summary: BacktestSummary
    trades: list[Trade]
    daily_signals: list[DailySignal]
    hypothesis_rows: list[HypothesisBacktestRow]
    equity_curve: list[dict[str, Any]]
    generated_files: dict[str, Path] = field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return asdict(self.summary)
