"""Technical analyzer v1 package."""

from .contracts.enums import (
    BreakoutStatus,
    ConfidenceLevel,
    FactorCategory,
    Horizon,
    TechnicalState,
    TrendDirection,
)
from .contracts.feature_contract import FeatureBundle, Pivot, SwingStructure
from .contracts.input_contract import ContextBundle, OHLCVBar, OHLCVSeries
from .contracts.output_contract import (
    FactorVote,
    HorizonResult,
    InvalidationSignal,
    ObservationCondition,
    TechnicalAnalysisResult,
)
from .classifiers.signal_aggregator import SignalAggregationResult, UnifiedSignal, UnifiedSignalEvent, aggregate_signals
from .decision import (
    CapCandidate,
    ConfidenceCapEngineResult,
    ScoreEngineResult,
    ThreeAxisScores,
    apply_confidence_caps,
    collect_cap_candidates,
    compute_three_axis_scores,
)
from .features.v2_quant import (
    FundamentalGateResult,
    FundamentalSnapshot,
    RiskExecutionPlan,
    TimeBoxProjection,
    TwoBReversalResult,
    V2QuantAnalysisResult,
    VolumeProfileResult,
    analyze_v2_quant,
)
from .orchestration import AIAnalysisResult, AIAnalysisResultBuilder, ThreeAxisScore

__all__ = [
    "BreakoutStatus",
    "AIAnalysisResult",
    "AIAnalysisResultBuilder",
    "CapCandidate",
    "ConfidenceLevel",
    "ConfidenceCapEngineResult",
    "ContextBundle",
    "FactorCategory",
    "FactorVote",
    "FeatureBundle",
    "FundamentalGateResult",
    "FundamentalSnapshot",
    "Horizon",
    "HorizonResult",
    "InvalidationSignal",
    "ObservationCondition",
    "OHLCVBar",
    "OHLCVSeries",
    "Pivot",
    "RiskExecutionPlan",
    "SignalAggregationResult",
    "ScoreEngineResult",
    "SwingStructure",
    "TechnicalAnalysisResult",
    "TechnicalState",
    "TimeBoxProjection",
    "ThreeAxisScore",
    "ThreeAxisScores",
    "TrendDirection",
    "TwoBReversalResult",
    "UnifiedSignal",
    "UnifiedSignalEvent",
    "V2QuantAnalysisResult",
    "VolumeProfileResult",
    "aggregate_signals",
    "analyze_v2_quant",
    "apply_confidence_caps",
    "collect_cap_candidates",
    "compute_three_axis_scores",
]
