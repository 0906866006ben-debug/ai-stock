from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class SourceInfo:
    ohlcv_source: str = "unavailable"
    turnover_source: str = "missing"
    market_index_source: str = "unavailable"
    is_mock_data: bool = False
    bars_count: int = 0
    data_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OhlcvLoadResult:
    candles: list[dict[str, Any]]
    source_info: SourceInfo
    finmind_rate_limited: bool = False
    finmind_disabled_until: Optional[str] = None
    error: Optional[str] = None


@dataclass
class MarketIndexLoadResult:
    dataframe: Any = None
    source: str = "unavailable"
    available: bool = False
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_report(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "available": self.available,
            "fallback_used": self.fallback_used,
            "warnings": list(self.warnings),
        }

