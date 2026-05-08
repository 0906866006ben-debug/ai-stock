# Taiwan Stock AI Analysis Platform - Evolution Specification

## 📋 Overview

Evolve the current MVP into a professional 4-pillar Taiwan stock analysis platform:
- 基本面 (Fundamental Analysis)
- 技術面 (Technical Analysis)
- 籌碼面 (Chip/Institutional Analysis)
- 消息面 (News/Sentiment Analysis)

---

## 🏗️ Architecture Design

### Core Principles
- **Modular**: Each analysis category is a dedicated module/agent
- **Reusable**: Shared schemas, utilities, data fetching
- **Resilient**: Mock fallback for all external APIs
- **Observable**: Clear data flow through LangGraph
- **Type-Safe**: Strict Pydantic validation
- **Backward Compatible**: Preserve existing `/analyze/tw` contract

### Data Flow

```
Request: GET /analyze/tw?symbol=2330
  ↓
[Market Data Agent]
  - Fetch OHLCV, price, volume
  - FinMind API
  ↓
[Technical Analysis Agent]
  - Compute indicators (MA, RSI, MACD, KD, BB, ATR)
  - Detect support/resistance, breakouts
  - Generate technical narrative
  ↓
[Fundamental Analysis Agent]
  - Fetch financials (revenue, EPS, PE, ROE, margins)
  - FinMind + mock fallback
  - 5-year trend analysis
  - Generate fundamental narrative
  ↓
[Chip Analysis Agent]
  - Fetch institutional data
  - Foreign/投信/dealer flows
  - Margin/short interest
  - Generate chip narrative
  ↓
[News Analysis Agent]
  - Fetch headlines (Finnhub, Yahoo, Google News)
  - Sentiment classification
  - Catalyst identification
  - Generate sentiment narrative
  ↓
[Synthesis Agent]
  - Combine all narratives
  - Calculate composite confidence
  - Identify conflicts/confirmations
  - Generate final recommendation
  ↓
Response: TaiwanStockAnalysisResponse
  (with all 4 pillars + AI synthesis)
```

### LangGraph Workflow

```python
graph = StateGraph(AnalysisState)

# Add nodes (async, can run in parallel where possible)
graph.add_node("market_data", fetch_market_data)
graph.add_node("technical", analyze_technical)
graph.add_node("fundamental", analyze_fundamental)
graph.add_node("chip", analyze_chip)
graph.add_node("news", analyze_news)
graph.add_node("synthesis", synthesize_analysis)

# Sequential edges (dependencies)
graph.set_entry_point("market_data")
graph.add_edge("market_data", "technical")
graph.add_edge("market_data", "fundamental")
graph.add_edge("market_data", "chip")
graph.add_edge("market_data", "news")
graph.add_edge("technical", "synthesis")
graph.add_edge("fundamental", "synthesis")
graph.add_edge("chip", "synthesis")
graph.add_edge("news", "synthesis")
graph.add_edge("synthesis", END)
```

---

## 📊 [1] Fundamental Analysis Module

### Data Sources (Priority Order)
1. **FinMind** - Taiwan company financials
2. **Mock** - Fallback realistic data

### Metrics to Collect

#### Income Statement
- **Revenue**: Latest, YoY %, MoM %
- **Monthly Revenue Trend**: Last 12 months
- **Gross Profit**: Amount, margin %
- **Operating Income**: Amount, margin %
- **Net Income**: Amount, YoY %
- **EPS**: Quarterly & latest
- **Dividend Per Share**: Cash + stock

#### Balance Sheet
- **Assets**: Total, breakdown
- **Liabilities**: Total, current vs long-term
- **Equity**: Book value
- **Cash & Equivalents**: Amount
- **Debt**: Total debt ratio

#### Ratios
- **PE Ratio**: Price-to-Earnings
- **PB Ratio**: Price-to-Book
- **ROE**: Return on Equity %
- **ROA**: Return on Assets %
- **Debt Ratio**: Total debt / assets

#### Cash Flow
- **Operating CF**: Trend last 4 quarters
- **Free CF**: Operating CF - CapEx
- **CF Trend**: Positive vs declining

#### Payout Analysis
- **Dividend Yield**: Annual dividend / price
- **Payout Ratio**: Dividend / earnings

### AI Analysis Output

```json
{
  "summary": "...",
  "revenue_trend": "improving|stable|declining",
  "profitability": {
    "trend": "improving|stable|declining",
    "quality": "high|medium|low",
    "key_metrics": { "pe_ratio": 15.2, "roe": "18.5%", ... }
  },
  "valuation": {
    "level": "cheap|fair|expensive",
    "support": "..."
  },
  "financial_health": {
    "debt_risk": "low|medium|high",
    "liquidity": "strong|adequate|weak",
    "cash_flow_quality": "good|fair|poor"
  },
  "risks": ["..."],
  "catalysts": ["..."]
}
```

---

## 📈 [2] Technical Analysis Module

### Indicators to Compute (pandas + ta library)

#### Moving Averages
- MA5, MA20, MA60, MA120, MA240
- Volume MA20
- Price position relative to MAs

#### Momentum
- **RSI(14)**: Overbought/oversold
- **MACD(12,26,9)**: Line, signal, histogram
- **KD(9,3,3)**: Fast & Slow K/D
- **Stochastic**: %K, %D

#### Volatility
- **Bollinger Bands(20,2)**: Upper, middle, lower
- **ATR(14)**: Average True Range
- **Volatility %**: Std dev of returns

#### Volume
- **Volume MA20**: Average volume
- **Current vs Average**: Ratio
- **OBV**: On-Balance Volume trend

#### Level Detection
- **Support/Resistance**: Pivot points, recent highs/lows
- **Breakout Detection**: Price breaking key levels
- **Trend Direction**: Higher highs/lows (uptrend) vs lower highs/lows (downtrend)

### AI Analysis Output

```json
{
  "summary": "...",
  "trend": {
    "direction": "uptrend|downtrend|sideways",
    "strength": "strong|medium|weak",
    "key_level": 2300
  },
  "momentum": {
    "rsi": 65,
    "rsi_signal": "approaching_overbought|overbought|normal|oversold",
    "macd_signal": "bullish|bearish|neutral",
    "trend_confirmation": "confirmed|mixed|conflicting"
  },
  "volatility": {
    "atr": 25.5,
    "bb_position": "upper|middle|lower",
    "volatility_level": "high|normal|low"
  },
  "key_levels": {
    "support": [2280, 2250],
    "resistance": [2320, 2350],
    "breakout_potential": "upside|downside|none"
  },
  "risks": ["..."],
  "opportunities": ["..."]
}
```

---

## 👥 [3] Chip Analysis Module

### Data Sources
- **FinMind**: Taiwan institutional data
- **Taiwan Stock Exchange**: Official reports
- **Mock**: Fallback realistic distributions

### Metrics to Track

#### Institutional Flows (5d, 10d, 20d)
- **Foreign Investor**: Buy volume - Sell volume
- **投信 (Mutual Funds)**: Net buy/sell
- **Dealer (自營): Net buy/sell

#### Accumulation Signals
- **Trend**: Accumulating vs distributing
- **Concentration**: Net buying persistence
- **Volume Impact**: Relative to daily volume

#### Margin & Short Interest
- **Margin Balance**: Debt ratio
- **Short Interest**: Open short positions
- **Trend**: Increasing vs decreasing

#### ETF & Major Shareholders
- **Top ETF Holdings**: Which ETFs hold
- **Major Shareholder**: Top 10, concentration
- **Pledged Shares**: If available

### AI Analysis Output

```json
{
  "summary": "...",
  "institutional_sentiment": {
    "foreign": {
      "5d_net": 2500000,
      "trend": "accumulating|distributing",
      "signal": "strong|moderate|weak"
    },
    "domestic_fund": {
      "5d_net": 1200000,
      "trend": "accumulating|distributing"
    },
    "dealer": {
      "5d_net": -800000,
      "activity": "active|normal|quiet"
    }
  },
  "chip_position": {
    "overall_trend": "accumulation|distribution|neutral",
    "abnormal_movement": true|false,
    "interpretation": "..."
  },
  "risk_indicators": {
    "margin_ratio": "normal|elevated|warning",
    "short_interest": "low|moderate|high",
    "concentration_risk": "low|medium|high"
  },
  "liquidity": {
    "daily_turnover": 5000000,
    "liquidity_risk": "low|medium|high"
  },
  "risks": ["..."],
  "signals": ["..."]
}
```

---

## 📰 [4] News & Sentiment Analysis Module

### Data Sources (Priority Order)
1. **Finnhub**: Real-time news + sentiment
2. **Yahoo Finance**: Headlines
3. **Google News**: General news
4. **FinMind**: Taiwan-specific news (if available)
5. **Mock**: Fallback sample news

### News Processing

#### Collection
- Fetch last 20-30 headlines
- Include: title, source, date, URL

#### Sentiment Classification
- **Positive**: Bullish keywords/tone
- **Negative**: Bearish keywords/tone
- **Neutral**: No clear sentiment

#### Impact Assessment
- **Short-term** (days-weeks): Immediate market impact
- **Long-term** (months): Strategic implications
- **Relevance**: Company-specific vs industry vs macro

### Key Topics to Track
- **Earnings**: Guidance, beat/miss
- **M&A**: Acquisitions, partnerships
- **Products**: New launches, recalls
- **Regulation**: Policy changes, restrictions
- **Industry**: Sector trends, competition
- **Macro**: Interest rates, trade, tech cycles

### AI Analysis Output

```json
{
  "summary": "...",
  "recent_headlines": [
    {
      "title": "...",
      "source": "...",
      "date": "2025-05-08",
      "sentiment": "positive|neutral|negative",
      "impact": "short_term|long_term|both",
      "relevance_score": 0.85,
      "interpretation": "..."
    }
  ],
  "sentiment_aggregate": {
    "bullish_count": 5,
    "neutral_count": 3,
    "bearish_count": 1,
    "overall_score": 0.72,
    "trend": "improving|stable|deteriorating"
  },
  "key_catalysts": [
    {
      "event": "Q2 earnings release",
      "date": "2025-08-15",
      "potential_impact": "high|medium|low",
      "direction": "bullish|bearish|neutral"
    }
  ],
  "macro_impact": {
    "relevant_factors": ["US rate hike", "chip shortage"],
    "impact_on_stock": "positive|neutral|negative"
  },
  "risks": ["..."],
  "opportunities": ["..."]
}
```

---

## 🤖 [5] Synthesis Agent

### Role
- Combine all 4 pillars into coherent narrative
- Identify confirmations, conflicts, contradictions
- Calculate composite confidence score
- Generate final recommendation

### Input
- Technical analysis result
- Fundamental analysis result
- Chip analysis result
- News analysis result

### Processing

#### Conflict Detection
- If technical bullish but fundamental weak: flag
- If institutional accumulating but price falling: flag
- If positive news but negative momentum: flag

#### Confirmation Scoring
- Each pillar votes on direction (bullish/neutral/bearish)
- Weighted vote: confidence = agreement count / 4
- Edge case: 2-2 split = neutral

#### Risk Assessment
- Combine risks from all pillars
- Rank by severity
- Highlight critical risks

#### Opportunity Identification
- Combine catalysts from all pillars
- Short-term vs long-term
- Probability assessment

### Output Schema

```json
{
  "symbol": "2330",
  "company_name": "台積電",
  "analyzed_at": "2025-05-08T10:30:00Z",
  
  "pillars": {
    "fundamental": { ... },
    "technical": { ... },
    "chip": { ... },
    "news": { ... }
  },
  
  "synthesis": {
    "summary": "Comprehensive narrative combining all pillars",
    "trend": "uptrend|downtrend|sideways",
    "confidence": 0.75,
    "thesis": "Core investment thesis",
    
    "confirmation_analysis": {
      "bullish_pillars": ["technical", "chip"],
      "bearish_pillars": [],
      "neutral_pillars": ["fundamental"],
      "conflicts": []
    },
    
    "composite_risks": [
      { "category": "technical", "risk": "...", "severity": "high" },
      { "category": "fundamental", "risk": "...", "severity": "medium" }
    ],
    
    "catalysts": [
      { "source": "news", "event": "...", "timeframe": "short_term", "impact": "positive" }
    ],
    
    "recommendation": {
      "action": "buy|hold|sell",
      "target_price": 2500,
      "stop_loss": 2100,
      "timeframe": "3-6 months",
      "conviction": 0.75
    }
  },
  
  "data_sources": {
    "market_data": "live|mock",
    "fundamentals": "live|mock",
    "chip_data": "live|mock",
    "news": "live|mock"
  }
}
```

---

## 💾 Backend Architecture

### Directory Structure

```
backend/
├── app/
│   ├── main.py                          # FastAPI app, routes
│   ├── graphs/
│   │   ├── tw_stock_graph.py            # Current graph (keep)
│   │   └── comprehensive_analysis_graph.py  # NEW: 4-pillar graph
│   ├── agents/                          # NEW: Analysis agents
│   │   ├── market_agent.py
│   │   ├── technical_agent.py
│   │   ├── fundamental_agent.py
│   │   ├── chip_agent.py
│   │   ├── news_agent.py
│   │   └── synthesis_agent.py
│   ├── services/
│   │   ├── finmind_*.py                 # Keep existing
│   │   ├── fintech_fundamentals.py      # NEW: Revenue, EPS, PE, ROE, etc.
│   │   ├── tw_technical_indicators.py   # NEW: Extended indicators (MA120, KD, BB, ATR)
│   │   ├── tw_chip_analysis.py          # NEW: Institutional data
│   │   ├── news_aggregator.py           # NEW: Finnhub, Yahoo, Google News
│   │   └── sentiment_analyzer.py        # NEW: Sentiment classification
│   └── models/
│       ├── schemas.py                   # Keep existing, extend
│       └── analysis_models.py            # NEW: 4-pillar schemas
│
└── tests/
    ├── test_market_agent.py
    ├── test_technical_agent.py
    ├── test_fundamental_agent.py
    ├── test_chip_agent.py
    ├── test_news_agent.py
    ├── test_synthesis_agent.py
    └── test_comprehensive_graph.py
```

### Service Layer Pattern

Each service follows the same contract:

```python
async def analyze_CATEGORY(symbol: str, market_data: dict) -> dict:
    """
    Fetch data + compute analysis.
    
    Returns: {
        "analysis": { ... detailed metrics ... },
        "narrative": "Traditional Chinese text",
        "confidence": 0.75,
        "is_mock": False,
        "risks": [...],
        "catalysts": [...]
    }
    """
    try:
        # Try to fetch real data
        data = await fetch_from_api(symbol)
        return {
            "analysis": compute_analysis(data),
            "is_mock": False
        }
    except:
        # Fallback to mock
        return {
            "analysis": generate_mock_analysis(symbol),
            "is_mock": True
        }
```

### API Contract Preservation

**Existing Endpoint (Keep Compatible)**
```
GET /analyze/tw?symbol=2330
```

Response structure **extended** but backward compatible:

```json
{
  "symbol": "2330",
  "company_name": "台積電",
  "market_type": "TWSE",
  "current_price": 2290,
  "price_change_percent": -0.87,
  "volume": 5000000,
  "trend": "中立",
  "confidence": 0.75,
  "summary": "...",
  "risks": [...],
  "catalysts": [...],
  "recommendation": "...",
  "chart_data": [...],
  
  // NEW: 4 pillars
  "analysis": {
    "fundamental": { ... },
    "technical": { ... },
    "chip": { ... },
    "news": { ... },
    "synthesis": { ... }
  },
  
  "data_source": "live|mock",
  "analyzed_at": "2025-05-08T10:30:00Z"
}
```

---

## 🎨 Frontend Architecture

### Dashboard Layout

```
┌─────────────────────────────────────────────┐
│ Stock Header: 2330 台積電 | TWSE | Price   │
├─────────────────────────────────────────────┤
│
│ [Technical Chart Section]
│ Candlestick + overlays (MA5/20/60/120)
│ Volume, RSI, MACD, KD, BB, ATR
│ Toggle indicators: ☐ MA ☐ RSI ☐ MACD...
│
├─────────────────────────────────────────────┤
│
│ 4-Column Analysis Grid:
│
│ ┌─────────────┐ ┌─────────────┐
│ │ 基本面分析   │ │ 技術面分析   │
│ │ Revenue     │ │ Trend       │
│ │ EPS         │ │ Momentum    │
│ │ PE Ratio    │ │ Levels      │
│ │ ROE         │ │ Volatility  │
│ └─────────────┘ └─────────────┘
│
│ ┌─────────────┐ ┌─────────────┐
│ │ 籌碼面分析   │ │ 消息面分析   │
│ │ 機構買賣     │ │ 最新頭條     │
│ │ 融資融券     │ │ 情緒分析     │
│ │ 持股濃度     │ │ 催化劑       │
│ └─────────────┘ └─────────────┘
│
├─────────────────────────────────────────────┤
│
│ AI Synthesis Section
│ 📊 Overall Assessment
│ ✓ Bullish/Neutral/Bearish
│ 📈 Target Price | 🛑 Stop Loss
│ ⏰ Timeframe | 💪 Conviction
│
├─────────────────────────────────────────────┤
│
│ Risk & Opportunities
│ 🔴 Critical Risks (from all pillars)
│ 🟢 Key Opportunities
│ 📅 Upcoming Catalysts
│
└─────────────────────────────────────────────┘
```

### Component Structure

```
pages/
├── page.tsx                          # Keep main app
├── stock/
│   └── [symbol]/
│       └── page.tsx                  # NEW: Detail page

components/
├── StockHeader.tsx                   # Header with price
├── TechnicalChart.tsx                # Candlestick + indicators
├── analysis/
│   ├── FundamentalCard.tsx           # NEW: 基本面
│   ├── TechnicalCard.tsx             # NEW: 技術面
│   ├── ChipCard.tsx                  # NEW: 籌碼面
│   ├── NewsCard.tsx                  # NEW: 消息面
│   └── SynthesisCard.tsx             # NEW: AI結論

lib/
├── api.ts                            # Keep + add new endpoints
├── types.ts                          # Extend types
└── utils/
    └── indicators.ts                 # Indicator formatting
```

---

## ✅ Scope & Non-Scope

### IN SCOPE
- ✓ 4-pillar analysis engine
- ✓ LangGraph orchestration
- ✓ PydanticAI synthesis
- ✓ Extended technical indicators
- ✓ Fundamental metrics fetching
- ✓ Institutional data aggregation
- ✓ News sentiment analysis
- ✓ Enhanced frontend dashboard
- ✓ Mock fallback for all APIs
- ✓ Backward compatibility

### OUT OF SCOPE (Phase 2+)
- ✗ Login / Authentication
- ✗ Payment / Monetization
- ✗ Portfolio management / Trading
- ✗ Docker / Kubernetes
- ✗ CI/CD pipelines
- ✗ Database persistence
- ✗ Telegram integration
- ✗ Real-time WebSocket updates
- ✗ Mobile native apps

---

## 🗺️ Development Roadmap

### Phase 1: Architecture & Agents (Task 1-6)
- [ ] Task 1: Design comprehensive analysis state schema
- [ ] Task 2: Build fundamental analysis agent + service
- [ ] Task 3: Build technical analysis agent (extended indicators)
- [ ] Task 4: Build chip analysis agent
- [ ] Task 5: Build news analysis agent
- [ ] Task 6: Build synthesis agent + LangGraph

### Phase 2: Integration & Testing (Task 7-9)
- [ ] Task 7: Integrate agents into comprehensive_analysis_graph
- [ ] Task 8: Update API schema, extend `/analyze/tw` response
- [ ] Task 9: Comprehensive integration tests

### Phase 3: Frontend (Task 10-12)
- [ ] Task 10: Build technical chart with extended indicators
- [ ] Task 11: Build 4-pillar analysis dashboard
- [ ] Task 12: Build synthesis/recommendation section

### Phase 4: Polish & Launch
- [ ] Task 13: Error handling, edge cases, docs
- [ ] Task 14: Performance optimization
- [ ] Task 15: Final QA & launch

---

## 🎯 Success Criteria

Each pillar must:
- ✓ Fetch data from 1+ reliable sources (or mock)
- ✓ Compute all specified metrics
- ✓ Generate Traditional Chinese narrative via PydanticAI
- ✓ Provide structured JSON output
- ✓ Have >85% unit test coverage
- ✓ Handle API failures gracefully

Synthesis agent must:
- ✓ Combine all 4 pillars coherently
- ✓ Detect conflicts & confirm confirmations
- ✓ Assign composite confidence score
- ✓ Generate actionable recommendation
- ✓ Explain reasoning in Traditional Chinese

---

## 📝 Development Notes

- **Work task-by-task**: Each agent is 1 task
- **Show commits**: Clear git history of feature additions
- **Test first**: Unit tests before integration
- **Mock always**: No feature requires real API key
- **Traditional Chinese**: All AI narratives in 繁體中文
- **Type safety**: Strict Pydantic validation
- **Backward compat**: Existing clients work unchanged

---

## 🚀 Next Steps

1. **Approve architecture**: Review this spec, suggest changes
2. **Start Phase 1**: Begin with fundamental analysis agent
3. **Iterate**: Each task shows results, proposes next task
4. **Integrate**: Phase 2 combines all agents
5. **Verify**: Comprehensive testing before frontend
6. **Deploy**: Launch enhanced platform

