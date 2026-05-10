# 📊 Professional Equity Research Report Upgrade Plan

**Objective:** Transform the equity research output from generic prose to professional analyst-grade reports with structured tables, score meters, star ratings, and citation links.

**Timeline:** 4 independent tasks (can be parallelized)

**Impact:** Every Taiwan stock analysis will display detailed market narrative, catalyst timeline, risk assessment, analyst consensus, and category ratings — matching institutional research standards.

---

## Executive Summary

| Aspect | Current State | Target State |
|--------|---------------|--------------|
| Sentiment | Prose string ("Redis情緒評分66/100...") | Structured: score 0-100, avg likes/comments |
| Analyst Consensus | Prose string ("32 Buy + 1 Hold...") | Structured: counts + per-firm targets |
| Catalysts | Bullet list of strings | 4-column table: 時間 \| 事件 \| 數據 \| 影響 |
| Risks | Bullet list of strings | 3-column table: 風險 \| 機率% \| 緩解策略 |
| Category Ratings | Missing entirely | 5 categories, 1-5 stars each |
| Sources | Missing entirely | List with URLs to Yahoo Finance / FinMind / TWSE |

---

## Task Dependency Graph

```
Task 1 (Sentiment + Consensus)
     ↓
Task 2 (Catalysts + Risks)      } All 3 independent
     ↓
Task 3 (Star Ratings + Sources)
     ↓
Task 4 (Gemini Prompt Upgrade) ← depends on 1-3
```

---

## Task 1: Sentiment Score + Analyst Consensus Structure

### Overview
Convert `social_sentiment: str` and `institutional_view: str` prose fields into structured Pydantic models that enable numeric display and table rendering.

### What Changes

#### Backend — `backend/app/models/schemas.py`

**Add 3 new Pydantic models** (before the `EquityResearch` class definition):

```python
class SentimentScore(BaseModel):
    """Numeric sentiment analysis with engagement metrics"""
    score: int                                  # 0–100 scale
    stage: str                                  # euphoric | fearful | skeptical | early-stage
    avg_likes_per_post: Optional[int] = None    # e.g., 155
    avg_comments_per_post: Optional[int] = None # e.g., 29
    source: str = "mock"                        # reddit | ptt | mock

class AnalystEntry(BaseModel):
    """Individual analyst firm's rating and target"""
    firm: str                          # "Bernstein" | "Needham" | "Morgan Stanley"
    rating: str                        # "Buy" | "Hold" | "Sell"
    target_price: Optional[float] = None

class AnalystConsensus(BaseModel):
    """Aggregate analyst consensus with individual firm data"""
    buy_count: int = 0                 # Total "Buy" votes
    hold_count: int = 0                # Total "Hold" votes
    sell_count: int = 0                # Total "Sell" votes
    target_low: Optional[float] = None # Lowest target price
    target_median: Optional[float] = None
    target_high: Optional[float] = None
    entries: list[AnalystEntry] = []   # Individual firm entries for detail view
```

**Add 2 new Optional fields to `EquityResearch` class:**

```python
class EquityResearch(BaseModel):
    # ... existing fields ...
    
    # NEW: Structured sentiment & consensus data
    sentiment_data: Optional[SentimentScore] = None
    analyst_consensus_data: Optional[AnalystConsensus] = None
```

#### Backend — `backend/app/agents/equity_research_agent.py`

**Update `_mock_equity_research()` function** (around line 208) to populate the new fields:

```python
def _mock_equity_research(...):
    # ... existing code ...
    
    # NEW: Structured sentiment data
    sentiment_data = SentimentScore(
        score=random.randint(55, 75) if is_bullish else random.randint(35, 55),
        stage="early-stage" if is_bullish else "skeptical",
        avg_likes_per_post=random.randint(100, 300),
        avg_comments_per_post=random.randint(15, 50),
        source="mock"
    )
    
    # NEW: Structured analyst consensus
    analyst_consensus_data = AnalystConsensus(
        buy_count=random.randint(25, 35) if is_bullish else random.randint(10, 20),
        hold_count=random.randint(1, 5),
        sell_count=random.randint(0, 3),
        target_low=round(current_price * 0.95, 2),
        target_median=round(current_price * 1.15, 2),
        target_high=round(current_price * 1.35, 2),
        entries=[
            AnalystEntry(firm="Bernstein", rating="Buy", target_price=round(current_price * 1.20, 2)),
            AnalystEntry(firm="Needham", rating="Buy", target_price=round(current_price * 1.40, 2)),
            AnalystEntry(firm="Morgan Stanley", rating="Hold", target_price=round(current_price * 1.08, 2)),
        ]
    )
    
    return EquityResearch(
        # ... existing fields ...
        sentiment_data=sentiment_data,
        analyst_consensus_data=analyst_consensus_data,
    )
```

**Update `_format_research_for_prompt()` function** (around line 41) to include the new data:

```python
def _format_research_for_prompt(...):
    # ... existing formatting code ...
    
    # NEW: Add structured data references
    prompt_text += f"""

## 結構化數據參考
分析師買進票數: {research_data.get('analyst_rating_counts', {}).get('buy', 0)}
分析師持平票數: {research_data.get('analyst_rating_counts', {}).get('hold', 0)}
分析師賣出票數: {research_data.get('analyst_rating_counts', {}).get('sell', 0)}
目標價範圍: {research_data.get('price_target_range', {})}
"""
    return prompt_text
```

#### Frontend — `ai-stock-frontend/lib/types.ts`

**Add TypeScript interfaces** (mirror the Pydantic models exactly):

```typescript
export interface SentimentScore {
  score: number;
  stage: string;
  avg_likes_per_post?: number | null;
  avg_comments_per_post?: number | null;
  source: string;
}

export interface AnalystEntry {
  firm: string;
  rating: string;
  target_price?: number | null;
}

export interface AnalystConsensus {
  buy_count: number;
  hold_count: number;
  sell_count: number;
  target_low?: number | null;
  target_median?: number | null;
  target_high?: number | null;
  entries: AnalystEntry[];
}
```

**Add to `EquityResearch` interface:**

```typescript
export interface EquityResearch {
  // ... existing fields ...
  sentiment_data?: SentimentScore | null;
  analyst_consensus_data?: AnalystConsensus | null;
}
```

#### Frontend — `ai-stock-frontend/app/components/EquityResearchReport.tsx`

**Section [1] Market Narrative — Redesign cards** (around line 113):

Replace the current prose text cards with structured widgets:

```tsx
{/* Social Sentiment Card — Score Meter */}
<div className="flex items-center gap-4">
  <div className="flex flex-col items-center">
    <div className="w-24 h-24 rounded-full border-4 border-blue-500 flex items-center justify-center">
      <div className="text-center">
        <div className="text-2xl font-bold">{data.sentiment_data?.score || 66}</div>
        <div className="text-xs text-gray-600">/100</div>
      </div>
    </div>
    <div className="text-sm text-gray-700 dark:text-gray-300 mt-2">社群情緒</div>
  </div>
  <div className="flex-1">
    <div className="text-sm"><strong>情緒階段:</strong> {data.sentiment_data?.stage}</div>
    {data.sentiment_data?.avg_likes_per_post && (
      <div className="text-sm">❤️ 平均 {data.sentiment_data.avg_likes_per_post} 讚</div>
    )}
    {data.sentiment_data?.avg_comments_per_post && (
      <div className="text-sm">💬 平均 {data.sentiment_data.avg_comments_per_post} 評論</div>
    )}
  </div>
</div>

{/* Analyst Consensus Card — Vote Counts + Table */}
{data.analyst_consensus_data && (
  <div className="p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
    <h4 className="font-semibold mb-3">分析師共識</h4>
    {/* Vote Count Badges */}
    <div className="flex gap-3 mb-4">
      <div className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm font-medium">
        {data.analyst_consensus_data.buy_count} Buy
      </div>
      <div className="px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-sm font-medium">
        {data.analyst_consensus_data.hold_count} Hold
      </div>
      <div className="px-3 py-1 bg-red-100 text-red-700 rounded-full text-sm font-medium">
        {data.analyst_consensus_data.sell_count} Sell
      </div>
    </div>
    {/* Price Target Range */}
    {(data.analyst_consensus_data.target_low || data.analyst_consensus_data.target_median || data.analyst_consensus_data.target_high) && (
      <div className="text-sm mb-4">
        <strong>目標價範圍:</strong> TWD {data.analyst_consensus_data.target_low?.toFixed(2)} ~ {data.analyst_consensus_data.target_high?.toFixed(2)} (中位數: {data.analyst_consensus_data.target_median?.toFixed(2)})
      </div>
    )}
    {/* Firm Entries Table */}
    {data.analyst_consensus_data.entries.length > 0 && (
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-300 dark:border-gray-600">
            <th className="text-left py-2 px-2">券商</th>
            <th className="text-center py-2 px-2">評等</th>
            <th className="text-right py-2 px-2">目標價</th>
          </tr>
        </thead>
        <tbody>
          {data.analyst_consensus_data.entries.map((entry, idx) => (
            <tr key={idx} className="border-b border-gray-200 dark:border-gray-700">
              <td className="py-2 px-2">{entry.firm}</td>
              <td className="text-center py-2 px-2">
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  entry.rating === 'Buy' ? 'bg-green-100 text-green-700' :
                  entry.rating === 'Hold' ? 'bg-amber-100 text-amber-700' :
                  'bg-red-100 text-red-700'
                }`}>
                  {entry.rating}
                </span>
              </td>
              <td className="text-right py-2 px-2">{entry.target_price ? `TWD ${entry.target_price.toFixed(2)}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </div>
)}
```

### Verification

```bash
# 1. Run backend tests
.venv/bin/python -m pytest backend/tests/test_equity_research_agent.py -q
# Expected: All tests pass + new assertions for sentiment_data and analyst_consensus_data

# 2. Type-check frontend
cd ai-stock-frontend && npx tsc --noEmit
# Expected: 0 TypeScript errors

# 3. Smoke test the new fields
.venv/bin/python << 'EOF'
import asyncio
from backend.app.graphs.comprehensive_analysis_graph import run_comprehensive_analysis

async def test():
    result = await run_comprehensive_analysis('2330')
    er = result['equity_research']
    assert er.sentiment_data is not None, "sentiment_data is None"
    assert er.sentiment_data.score >= 0 and er.sentiment_data.score <= 100
    assert er.analyst_consensus_data is not None, "analyst_consensus_data is None"
    assert er.analyst_consensus_data.buy_count >= 0
    print("✅ Task 1: Sentiment + Consensus data verified")

asyncio.run(test())
EOF
```

---

## Task 2: Catalyst Table + Risk Table Structure

### Overview
Replace bullet-list catalysts and risks with typed row objects that render as 4-column and 3-column tables respectively.

### What Changes

#### Backend — `backend/app/models/schemas.py`

**Add 2 new Pydantic models:**

```python
class CatalystRow(BaseModel):
    """Individual catalyst event with impact assessment"""
    time_horizon: str   # "2026 Q1" | "2026年中" | "2026年H2"
    event: str          # "Q1財報發布" | "2nm量產" | "股利政策宣佈"
    data_point: str     # "EPS預期 >24元" | "10-20% 產能提升"
    impact: str         # "+5-8%" | "邊際收益 +3-5%"

class RiskRow(BaseModel):
    """Individual risk with probability and mitigation"""
    risk: str                       # "地緣政治升溫"
    probability_pct: int            # 15, 25, 10 (integer percentage)
    mitigation: str                 # "地緣對沖投資防守股"
```

**Add to `EquityResearch`:**

```python
    catalyst_table: Optional[list[CatalystRow]] = None
    risk_table: Optional[list[RiskRow]] = None
```

#### Backend — `backend/app/agents/equity_research_agent.py`

**Update `_mock_equity_research()`** to populate catalyst and risk tables:

```python
catalyst_table = [
    CatalystRow(
        time_horizon="2026年Q1",
        event="Q1財報發布",
        data_point="EPS預期 >24元",
        impact="+5-8%"
    ),
    CatalystRow(
        time_horizon="2026年中",
        event="2nm/3nm提價",
        data_point="先進製程 +3-5% 溢價",
        impact="邊際收益提升"
    ),
    CatalystRow(
        time_horizon="2026年H2",
        event="2nm量產",
        data_point="10-20% 新產品營收",
        impact="+10-15%"
    ),
]

risk_table = [
    RiskRow(
        risk="地緣政治風險升溫 (中台關係)",
        probability_pct=15,
        mitigation="地緣對沖: 投資防守股（台電、中華電）"
    ),
    RiskRow(
        risk="AI泡沫破裂 (估值回歸)",
        probability_pct=25,
        mitigation="分批布局，降低單次進場規模"
    ),
    RiskRow(
        risk="競爭對手技術追趕 (Intel/Samsung)",
        probability_pct=10,
        mitigation="監控先進製程市佔率指標"
    ),
]

# In EquityResearch constructor:
return EquityResearch(
    # ... existing fields ...
    catalyst_table=catalyst_table,
    risk_table=risk_table,
)
```

#### Frontend — `ai-stock-frontend/lib/types.ts`

**Add TypeScript interfaces:**

```typescript
export interface CatalystRow {
  time_horizon: string;
  event: string;
  data_point: string;
  impact: string;
}

export interface RiskRow {
  risk: string;
  probability_pct: number;
  mitigation: string;
}
```

**Add to `EquityResearch`:**

```typescript
export interface EquityResearch {
  // ... existing fields ...
  catalyst_table?: CatalystRow[] | null;
  risk_table?: RiskRow[] | null;
}
```

#### Frontend — `ai-stock-frontend/app/components/EquityResearchReport.tsx`

**Section [1] — Replace catalyst bullet list with table** (around line 135):

```tsx
{/* Catalyst Table */}
{data.catalyst_table && data.catalyst_table.length > 0 ? (
  <div className="overflow-x-auto">
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr className="bg-blue-50 dark:bg-blue-900">
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-left">時間</th>
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-left">事件</th>
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-left">數據</th>
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-right">影響</th>
        </tr>
      </thead>
      <tbody>
        {data.catalyst_table.map((row, idx) => (
          <tr key={idx} className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2 whitespace-nowrap font-medium">{row.time_horizon}</td>
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2">{row.event}</td>
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2">{row.data_point}</td>
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-right font-semibold text-green-600 dark:text-green-400">{row.impact}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
) : (
  /* Fallback to existing bullet list */
  data.catalysts && <ul className="list-disc pl-5">{data.catalysts.map((c, i) => <li key={i}>{c}</li>)}</ul>
)}
```

**Section [2] — Replace financial risks with table** (around line 171):

```tsx
{/* Risk Table */}
{data.risk_table && data.risk_table.length > 0 ? (
  <div className="overflow-x-auto">
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr className="bg-red-50 dark:bg-red-900">
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-left">風險</th>
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-center whitespace-nowrap">機率%</th>
          <th className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-left">緩解策略</th>
        </tr>
      </thead>
      <tbody>
        {data.risk_table.map((row, idx) => (
          <tr key={idx} className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2">{row.risk}</td>
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2 text-center">
              <span className="px-2 py-1 bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300 rounded font-semibold text-xs">
                {row.probability_pct}%
              </span>
            </td>
            <td className="border border-gray-300 dark:border-gray-600 px-3 py-2">{row.mitigation}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
) : (
  /* Fallback to existing bullet list */
  data.risks && <ul className="list-disc pl-5">{data.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
)}
```

### Verification

```bash
.venv/bin/python -m pytest backend/tests/test_equity_research_agent.py -q
cd ai-stock-frontend && npx tsc --noEmit

.venv/bin/python << 'EOF'
import asyncio
from backend.app.graphs.comprehensive_analysis_graph import run_comprehensive_analysis

async def test():
    result = await run_comprehensive_analysis('2330')
    er = result['equity_research']
    assert er.catalyst_table is not None and len(er.catalyst_table) == 3
    assert er.risk_table is not None and len(er.risk_table) == 3
    assert er.risk_table[0].probability_pct in [15, 25, 10]
    print("✅ Task 2: Catalyst + Risk tables verified")

asyncio.run(test())
EOF
```

---

## Task 3: Category Star Ratings + Source Citations

### Overview
Add 5-category star rating display and source citations list (neither currently exists).

### What Changes

#### Backend — `backend/app/models/schemas.py`

**Add 2 new Pydantic models:**

```python
class CategoryRating(BaseModel):
    """Per-dimension investment rating"""
    category: str    # "Fundamental"|"Valuation"|"Technical"|"Risk"|"Long-term"
    label_zh: str    # "基本面"|"估值"|"技術面"|"風險"|"長期"
    stars: int       # 1, 2, 3, 4, or 5

class SourceCitation(BaseModel):
    """Data source with optional hyperlink"""
    title: str                   # "TSMC 即時股價與新聞"
    url: Optional[str] = None    # "https://finance.yahoo.com/quote/2330.TW"
    source: str                  # "Yahoo Finance" | "FinMind" | "TWSE" | "mock"
```

**Add to `EquityResearch`:**

```python
    category_ratings: Optional[list[CategoryRating]] = None
    source_citations: Optional[list[SourceCitation]] = None
```

#### Backend — `backend/app/agents/equity_research_agent.py`

**Update `_mock_equity_research()`:**

```python
# Compute star ratings from pillar data
fundamental_stars = 5 if comprehensive.confirmation_score >= 0.8 else 4 if comprehensive.confirmation_score >= 0.6 else 3
technical_stars = 4 if is_bullish else 3
valuation_stars = 4 if "fairly valued" in valuation_verdict.lower() else 3
risk_stars = 3 if len(financial_risks) <= 3 else 2
longterm_stars = 5 if is_bullish and comprehensive.confirmation_score > 0.7 else 4

category_ratings = [
    CategoryRating(category="Fundamental", label_zh="基本面", stars=fundamental_stars),
    CategoryRating(category="Valuation", label_zh="估值", stars=valuation_stars),
    CategoryRating(category="Technical", label_zh="技術面", stars=technical_stars),
    CategoryRating(category="Risk", label_zh="風險", stars=risk_stars),
    CategoryRating(category="Long-term", label_zh="長期", stars=longterm_stars),
]

source_citations = [
    SourceCitation(
        title=f"{symbol} 即時股價與新聞",
        url=f"https://finance.yahoo.com/quote/{symbol}.TW",
        source="Yahoo Finance"
    ),
    SourceCitation(
        title="台灣股票資訊 (FinMind)",
        url="https://finmind.github.io/",
        source="FinMind"
    ),
    SourceCitation(
        title="台灣證券交易所",
        url="https://www.twse.com.tw/",
        source="TWSE"
    ),
]

return EquityResearch(
    # ... existing fields ...
    category_ratings=category_ratings,
    source_citations=source_citations,
)
```

#### Frontend — `ai-stock-frontend/lib/types.ts`

**Add TypeScript interfaces:**

```typescript
export interface CategoryRating {
  category: string;
  label_zh: string;
  stars: number;
}

export interface SourceCitation {
  title: string;
  url?: string | null;
  source: string;
}
```

**Add to `EquityResearch`:**

```typescript
export interface EquityResearch {
  // ... existing fields ...
  category_ratings?: CategoryRating[] | null;
  source_citations?: SourceCitation[] | null;
}
```

#### Frontend — `ai-stock-frontend/app/components/EquityResearchReport.tsx`

**Add Category Ratings section** (after the executive summary, before closing div):

```tsx
{/* Category Ratings — Star Display */}
{data.category_ratings && data.category_ratings.length > 0 && (
  <div className="mt-8 p-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg">
    <h3 className="text-lg font-semibold mb-6">評級評分</h3>
    <div className="space-y-4">
      {data.category_ratings.map((rating, idx) => (
        <div key={idx} className="flex items-center justify-between">
          <span className="font-medium text-gray-800 dark:text-gray-200 w-24">{rating.label_zh}</span>
          <div className="flex gap-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <span key={i} className={i < rating.stars ? "text-yellow-400 text-xl" : "text-gray-300 text-xl"}>
                {i < rating.stars ? "★" : "☆"}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  </div>
)}

{/* Source Citations — Links Footer */}
{data.source_citations && data.source_citations.length > 0 && (
  <div className="mt-6 pt-6 border-t border-gray-300 dark:border-gray-600">
    <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">📚 資料來源</h4>
    <ul className="text-sm space-y-1">
      {data.source_citations.map((citation, idx) => (
        <li key={idx}>
          {citation.url ? (
            <a href={citation.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">
              {citation.source}: {citation.title}
            </a>
          ) : (
            <span className="text-gray-700 dark:text-gray-300">{citation.source}: {citation.title}</span>
          )}
        </li>
      ))}
    </ul>
  </div>
)}
```

### Verification

```bash
.venv/bin/python -m pytest backend/tests/test_equity_research_agent.py -q
cd ai-stock-frontend && npx tsc --noEmit

.venv/bin/python << 'EOF'
import asyncio
from backend.app.graphs.comprehensive_analysis_graph import run_comprehensive_analysis

async def test():
    result = await run_comprehensive_analysis('2330')
    er = result['equity_research']
    assert er.category_ratings is not None and len(er.category_ratings) == 5
    assert all(1 <= r.stars <= 5 for r in er.category_ratings)
    assert er.source_citations is not None and len(er.source_citations) >= 3
    print("✅ Task 3: Star ratings + source citations verified")

asyncio.run(test())
EOF
```

---

## Task 4: Gemini Prompt Upgrade (Final Integration)

### Overview
After Tasks 1-3 establish the new field structure and mock data, upgrade the Gemini system prompt so live AI responses also populate all structured fields with real content from search results.

### Prerequisites
- Tasks 1, 2, 3 must be merged and deployed
- New fields must be present in the schema
- Mock data must be generating all fields

### What Changes

#### Backend — `backend/app/agents/equity_research_agent.py`

**Update `_format_research_for_prompt()`** (line ~41):

Add a new section at the end that explicitly maps the research_data dict into named variables:

```python
def _format_research_for_prompt(comprehensive, metrics_narrative, research_data):
    # ... existing formatting ...
    
    # NEW: Explicit data section for structured field generation
    prompt_text += f"""

## 結構化輸出數據參考

### 分析師共識
- 買進票數: {research_data.get('analyst_rating_counts', {}).get('buy', 0)}
- 持平票數: {research_data.get('analyst_rating_counts', {}).get('hold', 0)}
- 賣出票數: {research_data.get('analyst_rating_counts', {}).get('sell', 0)}

### 價格目標
- 低位: {research_data.get('price_target_range', {}).get('low', 'N/A')}
- 中位數: {research_data.get('price_target_range', {}).get('median', 'N/A')}
- 高位: {research_data.get('price_target_range', {}).get('high', 'N/A')}

### 新聞標題 (for source citations)
{json.dumps(research_data.get('headlines', []), ensure_ascii=False, indent=2)}
"""
    return prompt_text
```

**Extend the system prompt** (line ~316):

Add detailed field-level instructions in the `📊 輸出要求` section:

```python
SYSTEM_PROMPT = """
... [existing context] ...

## 📊 輸出要求

你必須按照以下結構生成完整的 5 段式專業研究報告:

### [1] 市場敘述
必須包含以下結構化欄位:
- **sentiment_data**: 
  - score (0-100): 根據輿情情緒計算數字評分 (正面+20, 中立0, 負面-20, 基礎分50)
  - stage: euphoric | fearful | skeptical | early-stage (根據市場現況判斷)
  - avg_likes_per_post: 估計平均每篇文章讚數 (e.g., 155)
  - avg_comments_per_post: 估計平均回覆數 (e.g., 29)
  
- **analyst_consensus_data**:
  - buy_count, hold_count, sell_count: 使用輸入的 analyst_rating_counts 數據
  - target_low, target_median, target_high: 使用輸入的 price_target_range 數據
  - entries: 列表，包含具體的券商名稱 (e.g., Bernstein, Needham, Morgan Stanley) + 評等 + 目標價

### [2] 基本面快照
必須包含以下結構化欄位:
無新增結構化欄位（但請保持現有的 valuation_verdict, valuation_assumptions, financial_risks）

### [3] 技術面快照
無新增結構化欄位

### [4] 情景分析框架
必須包含以下結構化欄位:
- **catalyst_table**: list[CatalystRow]
  - 每個 catalyst 分解為: time_horizon (e.g., "2026年Q1"), event (e.g., "Q1財報"), data_point (具體數據), impact (影響%)
  - 至少 3 個行項目
  
- **risk_table**: list[RiskRow]
  - 每個風險包含: risk (風險描述), probability_pct (15-25%), mitigation (緩解策略)
  - 至少 3 個行項目

### [5] 投資行動框架
無新增結構化欄位

### 元數據
- **category_ratings**: list[CategoryRating]
  - 5 個評級: 基本面, 估值, 技術面, 風險, 長期
  - 每個 1-5 顆星，根據對應支柱的強度判斷
  
- **source_citations**: list[SourceCitation]
  - 包含所有 headlines 的 URL
  - 至少包含: Yahoo Finance, FinMind, TWSE 的官方連結

## ⚠️ 關鍵要求
所有新結構化欄位（sentiment_data, analyst_consensus_data, catalyst_table, risk_table, category_ratings, source_citations）必須填入具體數值，不可留空或返回 null。

如果沒有從搜尋結果提取到實際數據，則使用合理的推測值 (e.g., sentiment_score 根據正負面新聞比例計算)。
"""
```

**Update the user prompt** (line ~387):

```python
user_prompt = f"""
{formatted_data}

---

## 結構化欄位填充清單
☐ sentiment_data: score (0-100), stage, 平均讚數, 平均評論數
☐ analyst_consensus_data: 票數, 目標價範圍, 券商名單
☐ catalyst_table: 時間 | 事件 | 數據 | 影響 (≥3 rows)
☐ risk_table: 風險 | 機率% | 緩解策略 (≥3 rows)
☐ category_ratings: 5 個評級, 各 1-5 星
☐ source_citations: URL 清單, ≥3 來源

所有欄位必須填入具體數值，不可為 null。
"""
```

#### Backend — `backend/app/services/tw_market_research.py`

**Replace hardcoded mock values** (around line ~12 in `_get_mock_research_data()`):

```python
def _get_mock_research_data(symbol: str) -> dict:
    """Generate realistic per-symbol mock data"""
    
    # Per-symbol analyst consensus
    consensus_map = {
        '2330': {'buy': 32, 'hold': 1, 'sell': 0},    # TSMC
        '2317': {'buy': 28, 'hold': 2, 'sell': 1},    # Foxconn
        '3008': {'buy': 22, 'hold': 3, 'sell': 2},    # Largan
        '0050': {'buy': 15, 'hold': 3, 'sell': 0},    # Taiwan Top 50 ETF
        '0056': {'buy': 12, 'hold': 4, 'sell': 1},    # High Dividend ETF
    }
    
    # Per-symbol price targets (in TWD)
    target_map = {
        '2330': {'low': 2200, 'median': 2600, 'high': 3200},
        '2317': {'low': 32, 'median': 38, 'high': 45},
        '3008': {'low': 650, 'median': 800, 'high': 950},
        '0050': {'low': 220, 'median': 250, 'high': 290},
        '0056': {'low': 42, 'median': 48, 'high': 55},
    }
    
    consensus = consensus_map.get(symbol, {'buy': 10, 'hold': 3, 'sell': 1})
    targets = target_map.get(symbol, {'low': 100, 'median': 130, 'high': 160})
    
    return {
        'analyst_rating_counts': consensus,
        'price_target_range': targets,
        # ... rest of mock data ...
    }
```

### Verification

```bash
# 1. Full backend test suite
.venv/bin/python -m pytest backend/tests/ -q

# 2. Smoke test with multiple symbols (mock path)
.venv/bin/python << 'EOF'
import asyncio
from backend.app.graphs.comprehensive_analysis_graph import run_comprehensive_analysis

async def test():
    symbols = ['2330', '2317', '0050']
    for symbol in symbols:
        result = await run_comprehensive_analysis(symbol)
        er = result['equity_research']
        
        assert er.sentiment_data is not None
        assert er.analyst_consensus_data is not None and er.analyst_consensus_data.buy_count > 0
        assert er.catalyst_table is not None and len(er.catalyst_table) >= 3
        assert er.risk_table is not None and len(er.risk_table) >= 3
        assert er.category_ratings is not None and len(er.category_ratings) == 5
        assert er.source_citations is not None and len(er.source_citations) >= 3
        
        print(f"✅ {symbol}: All structured fields populated")

asyncio.run(test())
EOF

# 3. Type check frontend
cd ai-stock-frontend && npx tsc --noEmit

# 4. Visual smoke test (start dev server, open http://localhost:3000, search "2330")
.venv/bin/uvicorn backend.app.main:app --reload &
cd ai-stock-frontend && npm run dev
```

---

## Complete Implementation Checklist

### Task 1 — Sentiment + Consensus
- [ ] Add 3 Pydantic models to `schemas.py`
- [ ] Add 2 Optional fields to `EquityResearch`
- [ ] Update `_mock_equity_research()` to populate new fields
- [ ] Add 3 TypeScript interfaces to `types.ts`
- [ ] Redesign Market Narrative section in `EquityResearchReport.tsx`
- [ ] Run tests: `pytest` + `tsc` ✓

### Task 2 — Catalysts + Risks
- [ ] Add 2 Pydantic models to `schemas.py`
- [ ] Add 2 Optional fields to `EquityResearch`
- [ ] Update `_mock_equity_research()` with realistic catalyst & risk data
- [ ] Add 2 TypeScript interfaces to `types.ts`
- [ ] Add catalyst table rendering (Section [1])
- [ ] Add risk table rendering (Section [2])
- [ ] Run tests ✓

### Task 3 — Star Ratings + Citations
- [ ] Add 2 Pydantic models to `schemas.py`
- [ ] Add 2 Optional fields to `EquityResearch`
- [ ] Update `_mock_equity_research()` to compute star ratings + source list
- [ ] Add 2 TypeScript interfaces to `types.ts`
- [ ] Add Category Ratings section after summary
- [ ] Add Source Citations footer
- [ ] Run tests ✓

### Task 4 — Gemini Prompt
- [ ] Extend `_format_research_for_prompt()` with structured data references
- [ ] Update system prompt with field-level instructions
- [ ] Update user prompt with structured checklist
- [ ] Replace hardcoded values in `tw_market_research.py`
- [ ] Full smoke test across multiple symbols
- [ ] All 88+ backend tests pass ✓
- [ ] Zero TypeScript errors ✓

---

## Success Criteria

✅ **Backend:**
- All 88+ tests pass (0 regressions)
- 4 new Pydantic models properly defined
- 8 new Optional fields on `EquityResearch` schema
- `_mock_equity_research()` populates all new fields with realistic data
- No breaking changes (all new fields are Optional)

✅ **Frontend:**
- TypeScript: 0 errors
- Market Narrative: score meter + consensus table rendering
- Catalysts: 4-column table or fallback to bullets
- Risks: 3-column table with probability badges or fallback to bullets
- New sections: star ratings (5 categories) + source citations (with links)
- Responsive design (mobile 1 col, desktop 4 cols)
- Dark mode support throughout

✅ **Integration:**
- `/analyze/tw/2330` returns complete EquityResearch with all fields
- All fields visible in frontend component
- Output matches professional analyst report format
- Visual parity with the target TSMC sample report

---

## Implementation Timeline

| Task | Est. Time | Dependencies |
|------|-----------|--------------|
| Task 1 | 60 min | None |
| Task 2 | 60 min | None |
| Task 3 | 45 min | None |
| Task 4 | 45 min | Tasks 1-3 ✓ |
| **Total** | **~210 min (~3.5 hours)** | Sequential: 1-3 in parallel, then 4 |

---

## Notes

- All new fields are `Optional[...]` for backward compatibility with existing clients.
- Mock data generation includes realistic variance so not every stock looks identical.
- Frontend uses conditional rendering (`data.catalyst_table && ...`) to gracefully degrade for old API responses without the new fields.
- No breaking changes to existing routes or response contracts.
- Gemini upgrade (Task 4) is optional if GEMINI_API_KEY is absent — mock fallback always works.
