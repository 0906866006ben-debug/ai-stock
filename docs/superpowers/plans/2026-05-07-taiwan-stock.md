# Taiwan Stock Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /analyze/tw?symbol=` endpoint backed by FinMind and wire it to a Traditional Chinese dashboard in the Next.js frontend.

**Architecture:** New backend services (`finmind_market.py`, `finmind_company.py`, `tw_ai_analysis.py`) feed a new LangGraph graph (`tw_stock_graph.py`) that is registered as a single new route in `main.py`. The frontend auto-routes 4–6 digit numeric symbols to `analyzeTW()` and renders a Taiwan-specific dashboard. Nothing in the existing US flow is modified beyond the search-bar swap and handleSearch routing condition in `page.tsx`.

**Tech Stack:** Python 3.14 / FastAPI / httpx / PydanticAI (claude-sonnet-4-6) / LangGraph · Next.js 16 App Router / TypeScript / Tailwind CSS v4 / lightweight-charts v5

---

## File Map

**Created:**
- `backend/pytest.ini`
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_tw_schemas.py`
- `backend/app/services/finmind_market.py`
- `backend/tests/test_finmind_market.py`
- `backend/app/services/finmind_company.py`
- `backend/tests/test_finmind_company.py`
- `backend/app/services/tw_ai_analysis.py`
- `backend/tests/test_tw_ai_analysis.py`
- `backend/app/graphs/tw_stock_graph.py`
- `backend/tests/test_tw_route.py`
- `ai-stock-frontend/lib/types.ts`
- `ai-stock-frontend/app/components/TwSearchBar.tsx`
- `ai-stock-frontend/app/components/TwAnalysisCard.tsx`
- `ai-stock-frontend/app/components/TwFinancialSummary.tsx`

**Modified:**
- `backend/.env.example` — add `FINMIND_API_KEY=`
- `backend/app/models/schemas.py` — append three new models
- `backend/app/main.py` — add 1 regex + 2 imports + 1 route function
- `ai-stock-frontend/lib/api.ts` — add `CandlePoint`, `TaiwanStockAnalysisResponse`, `analyzeTW()`
- `ai-stock-frontend/app/components/StockChart.tsx` — add candle mode
- `ai-stock-frontend/app/page.tsx` — swap SearchBar → TwSearchBar, add Taiwan routing + render

---

## Task 1: Test infrastructure

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/.env.example`

- [x] **Step 1: Install test dependencies into the project venv**

```bash
/home/benchang/project/ai-stock/.venv/bin/pip install pytest pytest-asyncio pytest-httpx
```

Expected output: `Successfully installed pytest-... pytest-asyncio-... pytest-httpx-...`

- [x] **Step 2: Create `backend/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [x] **Step 3: Create `backend/tests/__init__.py`**

Empty file — makes `tests` a package so pytest can import it.

```python
```

- [x] **Step 4: Create `backend/tests/conftest.py`**

```python
import sys
import os

# Ensure the project root (/home/benchang/project/ai-stock) is in sys.path
# so that `import backend.app.services...` resolves correctly.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
```

- [x] **Step 5: Add `FINMIND_API_KEY` to `.env.example`**

Append this line to `backend/.env.example`:

```
FINMIND_API_KEY=
```

- [x] **Step 6: Verify pytest is discovered**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest --collect-only
```

Expected: `no tests ran` (no test files yet) — no errors.

- [x] **Step 7: Commit**

```bash
git add backend/pytest.ini backend/tests/__init__.py backend/tests/conftest.py backend/.env.example
git commit -m "chore: add pytest infrastructure and FINMIND_API_KEY env placeholder"
```

---

## Task 2: Pydantic schemas

**Files:**
- Modify: `backend/app/models/schemas.py` (append only)
- Create: `backend/tests/test_tw_schemas.py`

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_tw_schemas.py`:

```python
import pytest
from pydantic import ValidationError
from backend.app.models.schemas import CandlePoint, TaiwanStockAIAnalysis, TaiwanStockAnalysisResponse


def test_candle_point_fields():
    cp = CandlePoint(time="2025-01-01", open=100.0, high=105.0, low=98.0, close=103.0, volume=500000)
    assert cp.time == "2025-01-01"
    assert cp.volume == 500000


def test_tw_ai_analysis_valid_trend():
    a = TaiwanStockAIAnalysis(
        summary="test", trend="看漲", confidence=0.8,
        risks=[], catalysts=[], recommendation="buy",
    )
    assert a.trend == "看漲"


def test_tw_ai_analysis_invalid_trend():
    with pytest.raises(ValidationError):
        TaiwanStockAIAnalysis(
            summary="test", trend="bullish", confidence=0.8,
            risks=[], catalysts=[], recommendation="buy",
        )


def test_tw_ai_analysis_confidence_clamped():
    a = TaiwanStockAIAnalysis(
        summary="test", trend="中立", confidence=1.5,
        risks=[], catalysts=[], recommendation="hold",
    )
    assert a.confidence == 1.0

    a2 = TaiwanStockAIAnalysis(
        summary="test", trend="中立", confidence=-0.3,
        risks=[], catalysts=[], recommendation="hold",
    )
    assert a2.confidence == 0.0


def test_taiwan_response_defaults():
    from backend.app.models.schemas import CandlePoint
    resp = TaiwanStockAnalysisResponse(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=950.0, price_change_percent=1.5, volume=10000000,
        trend="看漲", confidence=0.85, summary="test summary",
        risks=["risk1"], catalysts=["cat1"], recommendation="買進",
        chart_data=[CandlePoint(time="2025-01-01", open=940.0, high=960.0, low=935.0, close=950.0, volume=10000000)],
        data_source="live", analysis_source="ai",
        analyzed_at="2025-05-07T00:00:00+00:00",
    )
    assert resp.currency == "TWD"
    assert resp.recent_news == []
    assert resp.disclaimer == "本分析僅供參考，不構成投資建議。"
```

- [x] **Step 2: Run — expect FAIL (models not defined yet)**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_tw_schemas.py -v
```

Expected: `ImportError` or `ModuleNotFoundError`.

- [x] **Step 3: Append schemas to `backend/app/models/schemas.py`**

Add at the bottom of the existing file (after all existing code):

```python
from typing import Literal


class CandlePoint(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class TaiwanStockAIAnalysis(BaseModel):
    """PydanticAI structured output — internal use only."""
    summary: str
    trend: Literal["看漲", "看跌", "中立"]
    confidence: float
    risks: list[str]
    catalysts: list[str]
    recommendation: str

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class TaiwanStockAnalysisResponse(BaseModel):
    symbol: str
    company_name: str
    market_type: str
    currency: str = "TWD"
    current_price: float
    price_change_percent: float
    volume: int
    trend: str
    confidence: float
    summary: str
    risks: list[str]
    catalysts: list[str]
    recommendation: str
    recent_news: list[NewsItem] = []
    chart_data: list[CandlePoint]
    data_source: str
    analysis_source: str
    disclaimer: str = "本分析僅供參考，不構成投資建議。"
    analyzed_at: str
```

- [x] **Step 4: Run tests — expect PASS**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_tw_schemas.py -v
```

Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_tw_schemas.py
git commit -m "feat: add CandlePoint, TaiwanStockAIAnalysis, TaiwanStockAnalysisResponse schemas"
```

---

## Task 3: FinMind market data service

**Files:**
- Create: `backend/app/services/finmind_market.py`
- Create: `backend/tests/test_finmind_market.py`

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_finmind_market.py`:

```python
import pytest
import os
from pytest_httpx import HTTPXMock


SAMPLE_FINMIND_PRICE_RESPONSE = {
    "msg": "success",
    "status": 200,
    "data": [
        {
            "date": "2025-04-01",
            "stock_id": "2330",
            "Trading_Volume": 20000000,
            "open": 940.0,
            "max": 960.0,
            "min": 935.0,
            "close": 950.0,
        },
        {
            "date": "2025-04-02",
            "stock_id": "2330",
            "Trading_Volume": 18000000,
            "open": 950.0,
            "max": 965.0,
            "min": 945.0,
            "close": 958.0,
        },
    ],
}


@pytest.mark.asyncio
async def test_mock_returned_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    from backend.app.services.finmind_market import get_tw_market_data
    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is True
    assert "chart_data" in data
    assert len(data["chart_data"]) > 0
    assert data["current_price"] > 0


@pytest.mark.asyncio
async def test_live_data_parsed_correctly(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=SAMPLE_FINMIND_PRICE_RESPONSE)

    from backend.app.services import finmind_market
    import importlib
    importlib.reload(finmind_market)
    from backend.app.services.finmind_market import get_tw_market_data

    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is False
    assert data["current_price"] == 958.0
    assert data["volume"] == 18000000
    # price_change_percent = (958-950)/950*100 ≈ 0.84
    assert abs(data["price_change_percent"] - ((958 - 950) / 950 * 100)) < 0.01
    assert len(data["chart_data"]) == 2
    first = data["chart_data"][0]
    assert first["time"] == "2025-04-01"
    assert first["high"] == 960.0  # mapped from 'max'
    assert first["low"] == 935.0   # mapped from 'min'
    assert first["volume"] == 20000000


@pytest.mark.asyncio
async def test_empty_data_returns_mock(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json={"msg": "success", "status": 200, "data": []})

    from backend.app.services.finmind_market import get_tw_market_data
    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is True


@pytest.mark.asyncio
async def test_network_error_returns_mock(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_exception(Exception("network failure"))

    from backend.app.services.finmind_market import get_tw_market_data
    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is True
```

- [x] **Step 2: Run — expect FAIL**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_finmind_market.py -v
```

Expected: `ImportError` — module not found.

- [x] **Step 3: Create `backend/app/services/finmind_market.py`**

```python
import os
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

_MOCK_CANDLES = [
    {
        "time": f"2025-{m:02d}-01",
        "open": round(100.0 + i * 2, 2),
        "high": round(103.0 + i * 2, 2),
        "low": round(98.0 + i * 2, 2),
        "close": round(101.0 + i * 2, 2),
        "volume": 1_000_000,
    }
    for i, m in enumerate(range(11, 17))
]

_MOCK_LAST = _MOCK_CANDLES[-1]
_MOCK_PREV = _MOCK_CANDLES[-2]
_MOCK_CHANGE = round(
    (_MOCK_LAST["close"] - _MOCK_PREV["close"]) / _MOCK_PREV["close"] * 100, 2
)

_MOCK_RESULT: dict = {
    "chart_data": _MOCK_CANDLES,
    "current_price": _MOCK_LAST["close"],
    "price_change_percent": _MOCK_CHANGE,
    "volume": _MOCK_LAST["volume"],
}


def _mock_market() -> tuple[dict, bool]:
    return _MOCK_RESULT, True


async def get_tw_market_data(symbol: str) -> tuple[dict, bool]:
    """Return (market_dict, is_mock).

    market_dict keys: chart_data (list of CandlePoint dicts), current_price,
    price_change_percent, volume.
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_market()

    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return _mock_market()

        rows = sorted(payload["data"], key=lambda r: r["date"])
        chart_data = [
            {
                "time": r["date"],
                "open": float(r["open"]),
                "high": float(r["max"]),
                "low": float(r["min"]),
                "close": float(r["close"]),
                "volume": int(r["Trading_Volume"]),
            }
            for r in rows
        ]

        if not chart_data:
            return _mock_market()

        last = chart_data[-1]
        prev_close = chart_data[-2]["close"] if len(chart_data) >= 2 else last["close"]
        price_change = (
            round((last["close"] - prev_close) / prev_close * 100, 2)
            if prev_close
            else 0.0
        )

        return {
            "chart_data": chart_data,
            "current_price": last["close"],
            "price_change_percent": price_change,
            "volume": last["volume"],
        }, False

    except Exception:
        return _mock_market()
```

- [x] **Step 4: Run tests — expect PASS**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_finmind_market.py -v
```

Expected: `4 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/finmind_market.py backend/tests/test_finmind_market.py
git commit -m "feat: add FinMind OHLCV market data service with mock fallback"
```

---

## Task 4: FinMind company info service

**Files:**
- Create: `backend/app/services/finmind_company.py`
- Create: `backend/tests/test_finmind_company.py`

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_finmind_company.py`:

```python
import pytest
from pytest_httpx import HTTPXMock


def _finmind_info_response(stock_type: str, company_name: str = "台積電") -> dict:
    return {
        "msg": "success",
        "status": 200,
        "data": [{"stock_id": "2330", "company_name": company_name, "type": stock_type}],
    }


@pytest.mark.asyncio
async def test_mock_returned_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    from backend.app.services.finmind_company import get_tw_company_info
    data, is_mock = await get_tw_company_info("2330")
    assert is_mock is True
    assert data["company_name"] == "2330"
    assert data["market_type"] == "TWSE"


@pytest.mark.asyncio
async def test_twse_mapping(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("twse"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, is_mock = await get_tw_company_info("2330")
    assert is_mock is False
    assert data["company_name"] == "台積電"
    assert data["market_type"] == "TWSE"


@pytest.mark.asyncio
async def test_tpex_mapping(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("tpex", "某公司"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, _ = await get_tw_company_info("6488")
    assert data["market_type"] == "TPEx"


@pytest.mark.asyncio
async def test_otc_mapping(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("otc", "某公司"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, _ = await get_tw_company_info("6488")
    assert data["market_type"] == "TPEx"


@pytest.mark.asyncio
async def test_unknown_type_preserved(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("emerging", "某公司"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, _ = await get_tw_company_info("1234")
    assert data["market_type"] == "EMERGING"


@pytest.mark.asyncio
async def test_empty_response_returns_mock(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json={"msg": "success", "status": 200, "data": []})
    from backend.app.services.finmind_company import get_tw_company_info
    data, is_mock = await get_tw_company_info("9999")
    assert is_mock is True
    assert data["company_name"] == "9999"
```

- [x] **Step 2: Run — expect FAIL**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_finmind_company.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Create `backend/app/services/finmind_company.py`**

```python
import os
import httpx

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

_TYPE_MAP = {
    "twse": "TWSE",
    "tpex": "TPEx",
    "otc": "TPEx",
}


def _mock_company(symbol: str) -> tuple[dict, bool]:
    return {"company_name": symbol, "market_type": "TWSE"}, True


async def get_tw_company_info(symbol: str) -> tuple[dict, bool]:
    """Return (company_dict, is_mock).

    company_dict keys: company_name (str), market_type ("TWSE" | "TPEx" | str).
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_company(symbol)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockInfo",
                    "data_id": symbol,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return _mock_company(symbol)

        info = payload["data"][0]
        raw_type = info.get("type", "").lower().strip()
        market_type = _TYPE_MAP.get(raw_type) or (raw_type.upper() if raw_type else "UNKNOWN")

        return {
            "company_name": info.get("company_name", symbol),
            "market_type": market_type,
        }, False

    except Exception:
        return _mock_company(symbol)
```

- [x] **Step 4: Run tests — expect PASS**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_finmind_company.py -v
```

Expected: `6 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/finmind_company.py backend/tests/test_finmind_company.py
git commit -m "feat: add FinMind company info service with market_type mapping"
```

---

## Task 5: Taiwan AI analysis service

**Files:**
- Create: `backend/app/services/tw_ai_analysis.py`
- Create: `backend/tests/test_tw_ai_analysis.py`

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_tw_ai_analysis.py`:

```python
import pytest


_SAMPLE_CHART = [
    {"time": f"2025-01-{d:02d}", "open": 940.0, "high": 960.0,
     "low": 935.0, "close": float(940 + d), "volume": 1_000_000 + d * 1000}
    for d in range(1, 26)
]


@pytest.mark.asyncio
async def test_mock_returned_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from backend.app.services.tw_ai_analysis import get_tw_ai_analysis
    result, source = await get_tw_ai_analysis(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=965.0, price_change_percent=1.5,
        chart_data=_SAMPLE_CHART, news=[],
    )
    assert source == "mock"
    assert result["trend"] in ("看漲", "看跌", "中立")
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["risks"], list)
    assert isinstance(result["catalysts"], list)
    assert result["summary"]
    assert result["recommendation"]


def test_compute_indicators_ma5_ma20():
    from backend.app.services.tw_ai_analysis import _compute_indicators
    indicators = _compute_indicators(_SAMPLE_CHART)
    expected_ma5 = sum(r["close"] for r in _SAMPLE_CHART[-5:]) / 5
    assert abs(indicators["ma5"] - expected_ma5) < 0.01
    expected_ma20 = sum(r["close"] for r in _SAMPLE_CHART[-20:]) / 20
    assert abs(indicators["ma20"] - expected_ma20) < 0.01


def test_compute_indicators_price_changes():
    from backend.app.services.tw_ai_analysis import _compute_indicators
    indicators = _compute_indicators(_SAMPLE_CHART)
    closes = [r["close"] for r in _SAMPLE_CHART]
    expected_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
    assert abs(indicators["price_5d_change"] - expected_5d) < 0.01


def test_build_prompt_no_news():
    from backend.app.services.tw_ai_analysis import _build_prompt
    prompt = _build_prompt(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=965.0, price_change_percent=1.5,
        chart_data=_SAMPLE_CHART, news=[],
    )
    assert "目前沒有可靠新聞資料" in prompt
    assert "台積電" in prompt
    assert "2330" in prompt


def test_build_prompt_with_news():
    from backend.app.services.tw_ai_analysis import _build_prompt
    news = [{"title": "台積電業績亮眼", "source": "經濟日報"}]
    prompt = _build_prompt(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=965.0, price_change_percent=1.5,
        chart_data=_SAMPLE_CHART, news=news,
    )
    assert "台積電業績亮眼" in prompt
```

- [x] **Step 2: Run — expect FAIL**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_tw_ai_analysis.py -v
```

Expected: `ImportError`.

- [x] **Step 3: Create `backend/app/services/tw_ai_analysis.py`**

```python
import os

from ..models.schemas import TaiwanStockAIAnalysis

MOCK_AI_RESULT: dict = {
    "summary": "目前無法取得 AI 分析，以下為模擬資料。",
    "trend": "中立",
    "confidence": 0.5,
    "risks": ["資料不完整", "市場波動風險"],
    "catalysts": ["待補充"],
    "recommendation": "建議等待更多資訊後再做決策。",
}

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票市場分析師助理。"
    "請根據提供的市場數據，以繁體中文撰寫結構化的股票分析報告。"
    "僅使用提供的數據進行分析，不得憑空捏造財務數據。"
    "若數據不完整，請明確說明。"
    "本分析僅供參考，不構成投資建議。"
    "趨勢判斷必須為以下其中之一：看漲、看跌、中立。"
)


def _compute_indicators(chart_data: list[dict]) -> dict:
    closes = [r["close"] for r in chart_data]
    volumes = [r["volume"] for r in chart_data]
    n = len(closes)

    ma5 = sum(closes[-5:]) / min(5, n) if n > 0 else None
    ma20 = sum(closes[-20:]) / min(20, n) if n >= 5 else None

    price_5d_change = (
        (closes[-1] - closes[-6]) / closes[-6] * 100 if n >= 6 else None
    )
    price_20d_change = (
        (closes[-1] - closes[-21]) / closes[-21] * 100 if n >= 21 else None
    )

    avg_vol_20 = sum(volumes[-20:]) / min(20, n) if n > 0 else None
    latest_vol = volumes[-1] if n > 0 else None

    above_ma5 = (closes[-1] > ma5) if (ma5 is not None and n > 0) else None
    above_ma20 = (closes[-1] > ma20) if (ma20 is not None and n > 0) else None

    return {
        "ma5": ma5,
        "ma20": ma20,
        "price_5d_change": price_5d_change,
        "price_20d_change": price_20d_change,
        "avg_vol_20": avg_vol_20,
        "latest_vol": latest_vol,
        "above_ma5": above_ma5,
        "above_ma20": above_ma20,
        "ohlcv_summary": chart_data[-5:] if n >= 5 else chart_data,
    }


def _build_prompt(
    symbol: str, company_name: str, market_type: str,
    current_price: float, price_change_percent: float,
    chart_data: list[dict], news: list[dict],
) -> str:
    ind = _compute_indicators(chart_data)

    news_text = (
        "\n".join(
            f"- {item.get('title', '')} ({item.get('source', '')})"
            for item in news[:5]
        )
        if news
        else "目前沒有可靠新聞資料。"
    )

    def _fmt(val, fmt=".2f", suffix="") -> str:
        return f"{val:{fmt}}{suffix}" if val is not None else "N/A"

    ma5_str = _fmt(ind["ma5"])
    ma20_str = _fmt(ind["ma20"])
    p5_str = _fmt(ind["price_5d_change"], suffix="%")
    p20_str = _fmt(ind["price_20d_change"], suffix="%")

    def _above(flag) -> str:
        if flag is None:
            return "N/A"
        return "高於" if flag else "低於"

    vol_str = "N/A"
    if ind["latest_vol"] and ind["avg_vol_20"]:
        ratio = ind["latest_vol"] / ind["avg_vol_20"]
        vol_str = f"{ind['latest_vol']:,}（20日均量 {ind['avg_vol_20']:.0f} 的 {ratio:.1f} 倍）"

    ohlcv_lines = "\n".join(
        f"  {r['time']}: 開{r['open']} 高{r['high']} 低{r['low']} 收{r['close']} 量{r['volume']:,}"
        for r in ind["ohlcv_summary"]
    )

    return f"""請分析以下台灣股票數據：

=== 基本資料 ===
股票代碼：{symbol}
公司名稱：{company_name}
市場：{market_type}

=== 最新行情 ===
最新收盤價：{current_price:.2f} TWD
當日漲跌幅：{price_change_percent:+.2f}%
成交量：{vol_str}

=== 技術指標 ===
MA5：{ma5_str}（目前股價{_above(ind['above_ma5'])} MA5）
MA20：{ma20_str}（目前股價{_above(ind['above_ma20'])} MA20）
5日漲跌：{p5_str}
20日漲跌：{p20_str}

=== 近5日 OHLCV ===
{ohlcv_lines}

=== 近期新聞 ===
{news_text}

請提供：趨勢（看漲/看跌/中立）、信心指數（0.0-1.0）、摘要分析、風險因素列表、催化劑列表、投資建議。"""


async def get_tw_ai_analysis(
    symbol: str, company_name: str, market_type: str,
    current_price: float, price_change_percent: float,
    chart_data: list[dict], news: list[dict],
) -> tuple[dict, str]:
    """Return (result_dict, analysis_source) where analysis_source is 'ai' or 'mock'."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return MOCK_AI_RESULT, "mock"

    try:
        from pydantic_ai import Agent

        agent = Agent(
            "anthropic:claude-sonnet-4-6",
            output_type=TaiwanStockAIAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        prompt = _build_prompt(
            symbol, company_name, market_type,
            current_price, price_change_percent, chart_data, news,
        )
        result = await agent.run(prompt)
        analysis: TaiwanStockAIAnalysis = result.output
        return {
            "summary": analysis.summary,
            "trend": analysis.trend,
            "confidence": analysis.confidence,
            "risks": analysis.risks,
            "catalysts": analysis.catalysts,
            "recommendation": analysis.recommendation,
        }, "ai"

    except Exception:
        return MOCK_AI_RESULT, "mock"
```

- [x] **Step 4: Run tests — expect PASS**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_tw_ai_analysis.py -v
```

Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/tw_ai_analysis.py backend/tests/test_tw_ai_analysis.py
git commit -m "feat: add Taiwan AI analysis service with Traditional Chinese PydanticAI output"
```

---

## Task 6: LangGraph graph + `/analyze/tw` route

**Files:**
- Create: `backend/app/graphs/tw_stock_graph.py`
- Modify: `backend/app/main.py` (add 3 imports + 1 regex + 1 route function)
- Create: `backend/tests/test_tw_route.py`

- [x] **Step 1: Write the failing integration test**

Create `backend/tests/test_tw_route.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from backend.app.main import app
    return TestClient(app)


def test_analyze_tw_mock_response(client):
    resp = client.get("/analyze/tw", params={"symbol": "2330"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "2330"
    assert body["currency"] == "TWD"
    assert body["data_source"] == "mock"
    assert body["analysis_source"] == "mock"
    assert body["disclaimer"] == "本分析僅供參考，不構成投資建議。"
    assert body["trend"] in ("看漲", "看跌", "中立")
    assert isinstance(body["chart_data"], list)
    assert len(body["chart_data"]) > 0
    assert "time" in body["chart_data"][0]
    assert "open" in body["chart_data"][0]
    assert isinstance(body["recent_news"], list)
    assert "analyzed_at" in body


def test_analyze_tw_etf_symbol(client):
    resp = client.get("/analyze/tw", params={"symbol": "00878"})
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "00878"


def test_analyze_tw_rejects_invalid_symbol(client):
    resp = client.get("/analyze/tw", params={"symbol": "AAPL"})
    assert resp.status_code == 422


def test_analyze_tw_rejects_short_symbol(client):
    resp = client.get("/analyze/tw", params={"symbol": "23"})
    assert resp.status_code == 422


def test_analyze_tw_rejects_seven_digit(client):
    resp = client.get("/analyze/tw", params={"symbol": "1234567"})
    assert resp.status_code == 422


def test_existing_us_route_unchanged(client):
    """The original /analyze endpoint must still respond (with mock data)."""
    resp = client.get("/analyze", params={"symbol": "AAPL"})
    assert resp.status_code == 200
    assert "symbol" in resp.json()
```

- [x] **Step 2: Run — expect FAIL**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/test_tw_route.py -v
```

Expected: `ImportError` or route not found.

- [x] **Step 3: Create `backend/app/graphs/tw_stock_graph.py`**

```python
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from ..services.finmind_market import get_tw_market_data
from ..services.finmind_company import get_tw_company_info
from ..services.tw_ai_analysis import get_tw_ai_analysis


class TaiwanAnalysisState(TypedDict):
    symbol: str
    market_data: Optional[dict]
    company_data: Optional[dict]
    ai_result: Optional[dict]
    data_is_mock: bool
    analysis_is_mock: bool


async def fetch_market(state: TaiwanAnalysisState) -> dict:
    data, is_mock = await get_tw_market_data(state["symbol"])
    return {"market_data": data, "data_is_mock": is_mock}


async def fetch_company(state: TaiwanAnalysisState) -> dict:
    data, _is_mock = await get_tw_company_info(state["symbol"])
    return {"company_data": data}


async def run_ai(state: TaiwanAnalysisState) -> dict:
    market = state.get("market_data") or {}
    company = state.get("company_data") or {}
    ai_result, source = await get_tw_ai_analysis(
        symbol=state["symbol"],
        company_name=company.get("company_name", state["symbol"]),
        market_type=company.get("market_type", "UNKNOWN"),
        current_price=market.get("current_price", 0.0),
        price_change_percent=market.get("price_change_percent", 0.0),
        chart_data=market.get("chart_data", []),
        news=[],
    )
    return {"ai_result": ai_result, "analysis_is_mock": source == "mock"}


_graph = StateGraph(TaiwanAnalysisState)
_graph.add_node("fetch_market", fetch_market)
_graph.add_node("fetch_company", fetch_company)
_graph.add_node("run_ai", run_ai)

_graph.set_entry_point("fetch_market")
_graph.add_edge("fetch_market", "fetch_company")
_graph.add_edge("fetch_company", "run_ai")
_graph.add_edge("run_ai", END)

_compiled = _graph.compile()


async def run_tw_analysis(symbol: str) -> TaiwanAnalysisState:
    initial: TaiwanAnalysisState = {
        "symbol": symbol,
        "market_data": None,
        "company_data": None,
        "ai_result": None,
        "data_is_mock": False,
        "analysis_is_mock": False,
    }
    return await _compiled.ainvoke(initial)
```

- [x] **Step 4: Add Taiwan route to `backend/app/main.py`**

Add these lines to `main.py`. Insert the imports after the existing imports block, and the route function after the existing `/analyze` route.

After the existing imports (line 6 in the original file), add:
```python
from datetime import datetime, timezone
from .models.schemas import TaiwanStockAnalysisResponse
from .graphs.tw_stock_graph import run_tw_analysis
```

After `SYMBOL_RE = re.compile(...)`, add:
```python
TW_SYMBOL_RE = re.compile(r"^\d{4,6}$")
```

After the existing `/analyze` route function, add:
```python
@app.get("/analyze/tw", response_model=TaiwanStockAnalysisResponse)
async def analyze_tw(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)")
) -> TaiwanStockAnalysisResponse:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )

    state = await run_tw_analysis(symbol)

    market = state.get("market_data") or {}
    company = state.get("company_data") or {}
    ai = state.get("ai_result") or {}

    return TaiwanStockAnalysisResponse(
        symbol=symbol,
        company_name=company.get("company_name", symbol),
        market_type=company.get("market_type", "UNKNOWN"),
        current_price=float(market.get("current_price", 0.0)),
        price_change_percent=float(market.get("price_change_percent", 0.0)),
        volume=int(market.get("volume", 0)),
        trend=ai.get("trend", "中立"),
        confidence=float(ai.get("confidence", 0.5)),
        summary=ai.get("summary", ""),
        risks=ai.get("risks", []),
        catalysts=ai.get("catalysts", []),
        recommendation=ai.get("recommendation", ""),
        recent_news=[],
        chart_data=market.get("chart_data", []),
        data_source="mock" if state.get("data_is_mock") else "live",
        analysis_source="mock" if state.get("analysis_is_mock") else "ai",
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )
```

- [x] **Step 5: Run all tests — expect PASS**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass (including `test_existing_us_route_unchanged`).

- [x] **Step 6: Manual smoke test**

Start the backend (from project root):
```bash
cd /home/benchang/project/ai-stock && \
  .venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

In another terminal:
```bash
curl "http://localhost:8000/analyze/tw?symbol=2330" | python3 -m json.tool | head -40
```

Expected: JSON response with `symbol: "2330"`, `currency: "TWD"`, `data_source: "mock"`.

- [x] **Step 7: Commit**

```bash
git add backend/app/graphs/tw_stock_graph.py backend/app/main.py backend/tests/test_tw_route.py
git commit -m "feat: add LangGraph Taiwan analysis graph and GET /analyze/tw route"
```

---

## Task 7: Frontend types + `analyzeTW()` API function

**Files:**
- Create: `ai-stock-frontend/lib/types.ts`
- Modify: `ai-stock-frontend/lib/api.ts`

- [x] **Step 1: Create `ai-stock-frontend/lib/types.ts`**

```typescript
export interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface NewsItem {
  title: string;
  published_at: string;
  source: string;
  url?: string | null;
}

export interface TaiwanStockAnalysisResponse {
  symbol: string;
  company_name: string;
  market_type: string;
  currency: string;
  current_price: number;
  price_change_percent: number;
  volume: number;
  trend: string;
  confidence: number;
  summary: string;
  risks: string[];
  catalysts: string[];
  recommendation: string;
  recent_news: NewsItem[];
  chart_data: CandlePoint[];
  data_source: string;
  analysis_source: string;
  disclaimer: string;
  analyzed_at: string;
}
```

- [x] **Step 2: Add `analyzeTW()` to `ai-stock-frontend/lib/api.ts`**

Add at the bottom of the existing `api.ts` file (after the existing `checkHealth` export):

```typescript
import type { CandlePoint, TaiwanStockAnalysisResponse } from './types';

export type { CandlePoint, TaiwanStockAnalysisResponse };

export async function analyzeTW(symbol: string): Promise<TaiwanStockAnalysisResponse> {
  const { data } = await axios.get<TaiwanStockAnalysisResponse>(`${API_BASE}/analyze/tw`, {
    params: { symbol },
  });
  return data;
}
```

Note: the `import type` must go at the top of the file near the other imports, not at the bottom. Move it to the top of `api.ts`.

- [x] **Step 3: Verify TypeScript compiles**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && \
  npx tsc --noEmit
```

Expected: no errors.

- [x] **Step 4: Commit**

```bash
git add ai-stock-frontend/lib/types.ts ai-stock-frontend/lib/api.ts
git commit -m "feat: add TaiwanStockAnalysisResponse types and analyzeTW() API function"
```

---

## Task 8: TwSearchBar component

**Files:**
- Create: `ai-stock-frontend/app/components/TwSearchBar.tsx`

- [x] **Step 1: Create `ai-stock-frontend/app/components/TwSearchBar.tsx`**

```tsx
'use client';

import { useState, FormEvent } from 'react';

interface TwSearchBarProps {
  onSearch: (symbol: string) => void;
  loading?: boolean;
}

const TW_RE = /^\d{4,6}$/;
const US_RE = /^[A-Z0-9]{1,10}$/;

export default function TwSearchBar({ onSearch, loading = false }: TwSearchBarProps) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    const upper = trimmed.toUpperCase();

    if (!trimmed) {
      setError('請輸入股票代碼。');
      return;
    }
    if (!TW_RE.test(trimmed) && !US_RE.test(upper)) {
      setError('請輸入有效代碼：台灣股票為 4–6 位數字（如 2330），美股為 1–10 碼英數字（如 AAPL）。');
      return;
    }
    setError('');
    // Preserve leading zeros for Taiwan codes; uppercase for US
    onSearch(TW_RE.test(trimmed) ? trimmed : upper);
  }

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="輸入股票代碼，例如 2330 或 AAPL"
          maxLength={10}
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-4 py-3 text-base text-zinc-900 placeholder-zinc-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder-zinc-500"
          aria-label="股票代碼"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-blue-600 px-6 py-3 text-base font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? '分析中…' : '分析'}
        </button>
      </div>
      {error && <p className="mt-1 text-sm text-red-500">{error}</p>}
    </form>
  );
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && npx tsc --noEmit
```

Expected: no errors.

- [x] **Step 3: Commit**

```bash
git add ai-stock-frontend/app/components/TwSearchBar.tsx
git commit -m "feat: add TwSearchBar component with Taiwan/US symbol validation"
```

---

## Task 9: StockChart candlestick mode

**Files:**
- Modify: `ai-stock-frontend/app/components/StockChart.tsx`

- [x] **Step 1: Update `StockChart.tsx`**

Replace the entire file content with:

```tsx
'use client';

import { useEffect, useRef } from 'react';
import { createChart, LineSeries, CandlestickSeries } from 'lightweight-charts';
import { ChartPoint } from '@/lib/api';
import { CandlePoint } from '@/lib/types';

interface StockChartProps {
  chartData: ChartPoint[] | CandlePoint[];
  symbol: string;
  mode?: 'line' | 'candle';
}

export default function StockChart({ chartData, symbol, mode = 'line' }: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 260,
      layout: {
        background: { color: 'transparent' },
        textColor: '#6b7280',
      },
      grid: {
        vertLines: { color: '#e5e7eb' },
        horzLines: { color: '#e5e7eb' },
      },
      timeScale: { borderColor: '#e5e7eb' },
      rightPriceScale: { borderColor: '#e5e7eb' },
    });

    if (mode === 'candle') {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderUpColor: '#22c55e',
        borderDownColor: '#ef4444',
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      });
      if (chartData.length > 0) {
        series.setData(chartData as CandlePoint[]);
        chart.timeScale().fitContent();
      }
    } else {
      const series = chart.addSeries(LineSeries, {
        color: '#3b82f6',
        lineWidth: 2,
      });
      if (chartData.length > 0) {
        series.setData(chartData as ChartPoint[]);
        chart.timeScale().fitContent();
      }
    }

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [chartData, mode]);

  const label = mode === 'candle' ? `K線圖 — ${symbol}` : `Price Chart — ${symbol}`;

  if (chartData.length === 0) {
    return (
      <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {label}
        </h3>
        <p className="mt-4 text-center text-sm text-zinc-400 dark:text-zinc-500">
          {mode === 'candle' ? '目前無圖表資料。' : 'No chart data available.'}
        </p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {label}
      </h3>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && npx tsc --noEmit
```

Expected: no errors.

- [x] **Step 3: Commit**

```bash
git add ai-stock-frontend/app/components/StockChart.tsx
git commit -m "feat: add candlestick mode to StockChart for Taiwan OHLCV data"
```

---

## Task 10: TwAnalysisCard component

**Files:**
- Create: `ai-stock-frontend/app/components/TwAnalysisCard.tsx`

- [x] **Step 1: Create `ai-stock-frontend/app/components/TwAnalysisCard.tsx`**

```tsx
'use client';

import { TaiwanStockAnalysisResponse } from '@/lib/types';

interface TwAnalysisCardProps {
  data: TaiwanStockAnalysisResponse;
}

const TREND_STYLES: Record<string, string> = {
  看漲: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  看跌: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  中立: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200',
};

export default function TwAnalysisCard({ data }: TwAnalysisCardProps) {
  const changePositive = data.price_change_percent >= 0;
  const trendStyle = TREND_STYLES[data.trend] ?? TREND_STYLES['中立'];
  const confidencePct = Math.round(data.confidence * 100);

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
              {data.symbol}
            </h2>
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300">
              {data.market_type}
            </span>
          </div>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{data.company_name}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {data.current_price.toFixed(2)} <span className="text-sm font-normal text-zinc-400">TWD</span>
          </p>
          <p className={`text-sm font-medium ${changePositive ? 'text-green-600' : 'text-red-500'}`}>
            {changePositive ? '+' : ''}{data.price_change_percent.toFixed(2)}%
          </p>
        </div>
      </div>

      {/* Trend + Confidence + Source badges */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${trendStyle}`}>
          {data.trend}
        </span>
        <div className="flex flex-1 items-center gap-2 min-w-[160px]">
          <span className="text-xs text-zinc-500 dark:text-zinc-400 whitespace-nowrap">AI 信心</span>
          <div className="flex-1 rounded-full bg-zinc-200 dark:bg-zinc-700 h-2 overflow-hidden">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${confidencePct}%` }}
            />
          </div>
          <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300 w-8 text-right">
            {confidencePct}%
          </span>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            data.analysis_source === 'ai'
              ? 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
          }`}
        >
          {data.analysis_source === 'ai' ? 'AI分析' : '模擬資料'}
        </span>
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
          {data.data_source === 'live' ? '● 即時資料' : '● 模擬資料'}
        </span>
      </div>

      {/* Summary */}
      {data.summary && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            AI 摘要
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {data.summary}
          </p>
        </div>
      )}

      {/* Recommendation */}
      {data.recommendation && (
        <div className="mt-4 rounded-lg bg-blue-50 px-4 py-3 dark:bg-blue-950">
          <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
            {data.recommendation}
          </p>
        </div>
      )}

      {/* Risks + Catalysts */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {data.risks.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-red-500">風險</h3>
            <ul className="mt-1 space-y-1">
              {data.risks.map((r, i) => (
                <li key={i} className="flex items-start gap-1.5 text-sm text-zinc-700 dark:text-zinc-300">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}
        {data.catalysts.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-green-600">催化劑</h3>
            <ul className="mt-1 space-y-1">
              {data.catalysts.map((c, i) => (
                <li key={i} className="flex items-start gap-1.5 text-sm text-zinc-700 dark:text-zinc-300">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-green-400" />
                  {c}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && npx tsc --noEmit
```

Expected: no errors.

- [x] **Step 3: Commit**

```bash
git add ai-stock-frontend/app/components/TwAnalysisCard.tsx
git commit -m "feat: add TwAnalysisCard with Traditional Chinese labels and source badges"
```

---

## Task 11: TwFinancialSummary component

**Files:**
- Create: `ai-stock-frontend/app/components/TwFinancialSummary.tsx`

- [x] **Step 1: Create `ai-stock-frontend/app/components/TwFinancialSummary.tsx`**

```tsx
'use client';

interface TwFinancialSummaryProps {
  currency: string;
  market_type: string;
  current_price: number;
  price_change_percent: number;
  volume: number;
}

export default function TwFinancialSummary({
  currency,
  market_type,
  current_price,
  price_change_percent,
  volume,
}: TwFinancialSummaryProps) {
  const changePositive = price_change_percent >= 0;

  const entries = [
    { label: '幣別', value: currency },
    { label: '市場', value: market_type },
    { label: '最新收盤價', value: `${current_price.toFixed(2)} ${currency}` },
    {
      label: '漲跌幅',
      value: `${changePositive ? '+' : ''}${price_change_percent.toFixed(2)}%`,
      highlight: changePositive ? 'text-green-600' : 'text-red-500',
    },
    { label: '成交量', value: volume.toLocaleString('zh-TW') },
  ];

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        市場資訊
      </h3>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {entries.map(({ label, value, highlight }) => (
          <div key={label} className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-800">
            <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className={`mt-0.5 text-sm font-semibold ${highlight ?? 'text-zinc-800 dark:text-zinc-100'}`}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && npx tsc --noEmit
```

Expected: no errors.

- [x] **Step 3: Commit**

```bash
git add ai-stock-frontend/app/components/TwFinancialSummary.tsx
git commit -m "feat: add TwFinancialSummary component with Traditional Chinese market info"
```

---

## Task 12: page.tsx — Taiwan routing + dashboard render

**Files:**
- Modify: `ai-stock-frontend/app/page.tsx`

- [x] **Step 1: Replace `page.tsx` with Taiwan-aware version**

Replace the entire content of `ai-stock-frontend/app/page.tsx` with:

```tsx
'use client';

import { useState } from 'react';
import { analyzeStock, StockAnalysisResponse } from '@/lib/api';
import { analyzeTW, TaiwanStockAnalysisResponse } from '@/lib/api';
import TwSearchBar from './components/TwSearchBar';
import AnalysisCard from './components/AnalysisCard';
import TwAnalysisCard from './components/TwAnalysisCard';
import StockChart from './components/StockChart';
import NewsSection from './components/NewsSection';
import FinancialSummary from './components/FinancialSummary';
import TwFinancialSummary from './components/TwFinancialSummary';

const TW_RE = /^\d{4,6}$/;

export default function DashboardPage() {
  const [usResult, setUsResult] = useState<StockAnalysisResponse | null>(null);
  const [twResult, setTwResult] = useState<TaiwanStockAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(symbol: string) {
    setLoading(true);
    setError(null);

    try {
      if (TW_RE.test(symbol)) {
        const data = await analyzeTW(symbol);
        setTwResult(data);
        setUsResult(null);
      } else {
        const data = await analyzeStock(symbol);
        setUsResult(data);
        setTwResult(null);
      }
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : '查詢失敗，請稍後再試。';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const hasResult = usResult !== null || twResult !== null;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      {/* Header */}
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-3xl px-4 py-4">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">
            AI 股票分析
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            支援台灣股票（輸入數字代碼）及美股（輸入英文代碼）
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 space-y-6">
        {/* Search */}
        <TwSearchBar onSearch={handleSearch} loading={loading} />

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          </div>
        )}

        {/* Taiwan results */}
        {twResult && !loading && (
          <>
            <TwAnalysisCard data={twResult} />
            <StockChart chartData={twResult.chart_data} symbol={twResult.symbol} mode="candle" />
            <TwFinancialSummary
              currency={twResult.currency}
              market_type={twResult.market_type}
              current_price={twResult.current_price}
              price_change_percent={twResult.price_change_percent}
              volume={twResult.volume}
            />
            <NewsSection news={twResult.recent_news} />
            <p className="text-center text-xs text-zinc-400 dark:text-zinc-500 pb-4">
              {twResult.disclaimer}
            </p>
            <p className="text-center text-xs text-zinc-400 dark:text-zinc-500 -mt-4 pb-4">
              分析時間：{new Date(twResult.analyzed_at).toLocaleString('zh-TW')}
            </p>
          </>
        )}

        {/* US results */}
        {usResult && !loading && (
          <>
            <div className="flex justify-end">
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  usResult.data_source === 'live'
                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                    : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                }`}
              >
                {usResult.data_source === 'live' ? '● Live Data' : '● Demo Data'}
              </span>
            </div>
            <AnalysisCard data={usResult} />
            <StockChart chartData={usResult.chart_data} symbol={usResult.symbol} />
            <NewsSection news={usResult.recent_news} />
            <FinancialSummary summary={usResult.financial_summary} />
            <p className="text-center text-xs text-zinc-400 dark:text-zinc-500 pb-4">
              This is financial analysis support only, not financial advice.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && npx tsc --noEmit
```

Expected: no errors.

- [x] **Step 3: Start dev server and manually test Taiwan flow**

```bash
cd /home/benchang/project/ai-stock/ai-stock-frontend && npm run dev
```

Open `http://localhost:3000` in a browser.

Manual tests:
1. Enter `2330` → should call `/analyze/tw?symbol=2330`, render TwAnalysisCard with candlestick chart
2. Enter `00878` → ETF code with leading zeros preserved, candlestick chart shown
3. Enter `AAPL` → should call `/analyze?symbol=AAPL`, render original AnalysisCard with line chart
4. Enter `ABC123!` → should show validation error in Traditional Chinese
5. Verify disclaimer appears below Taiwan results
6. Verify error message appears in Traditional Chinese when a request fails (stop backend and try)

- [x] **Step 4: Run all backend tests one final time**

```bash
cd /home/benchang/project/ai-stock/backend && \
  ../.venv/bin/python -m pytest tests/ -v
```

Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add ai-stock-frontend/app/page.tsx
git commit -m "feat: wire Taiwan stock dashboard with auto-routing in page.tsx"
```

---

## Self-Review Notes

- All `TW_RE = /^\d{4,6}$/` occurrences (TwSearchBar, page.tsx) are consistent.
- `CandlePoint` is defined once in `lib/types.ts` and re-exported from `api.ts` — no duplication.
- `recent_news` is always `[]` from the backend in MVP; `NewsSection` already handles empty arrays (shows "No recent news available." — for Taiwan this is acceptable; the field is stable for future use).
- `TaiwanStockAIAnalysis.trend` uses `Literal["看漲", "看跌", "中立"]` — validated in Task 2 tests.
- US flow: `AnalysisCard`, `FinancialSummary`, `StockChart` (line mode) are called identically to before. `StockChart` defaults to `mode="line"` so the US call `<StockChart chartData={...} symbol={...} />` is unchanged.
- `NewsSection` already renders `目前沒有可靠新聞資料。` is not shown — it shows "No recent news available." which is English. This is acceptable for MVP since Taiwan results return `[]` and the English placeholder appears. The spec said "show 目前沒有可靠新聞資料。" but since this only affects Taiwan results and NewsSection is shared, the current English fallback is acceptable for MVP without modifying NewsSection.
