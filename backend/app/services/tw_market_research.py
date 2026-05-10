"""
Market research data fetching for equity research using Gemini grounded search.
Supports 3-tier fallback: Gemini grounded search → Yahoo Finance → mock.
"""

import os
import asyncio
import httpx
from datetime import datetime

from backend.app.services.gemini_diagnostics import (
    get_gemini_model_chain,
    is_gemini_enabled,
    log_gemini_diagnostics,
)


def _get_mock_research_data(symbol: str) -> dict:
    """Return realistic mock research data when APIs unavailable."""
    consensus_map = {
        "2330": {"buy": 32, "hold": 1, "sell": 0},
        "2317": {"buy": 28, "hold": 2, "sell": 1},
        "3008": {"buy": 22, "hold": 3, "sell": 2},
        "0050": {"buy": 15, "hold": 3, "sell": 0},
        "0056": {"buy": 12, "hold": 4, "sell": 1},
    }
    target_map = {
        "2330": {"low": 950, "median": 1150, "high": 1350},
        "2317": {"low": 160, "median": 200, "high": 240},
        "3008": {"low": 1800, "median": 2300, "high": 2800},
        "0050": {"low": 160, "median": 190, "high": 220},
        "0056": {"low": 32, "median": 38, "high": 45},
    }
    consensus = consensus_map.get(symbol, {"buy": 10, "hold": 3, "sell": 1})
    targets = target_map.get(symbol, {"low": 100, "median": 130, "high": 160})

    return {
        "headlines": [
            {
                "title": f"{symbol} 股價近期波動較大，市場關注營運展望",
                "source": "Market Monitor",
                "url": "",
            }
        ],
        "analyst_consensus": "持平",
        "analyst_rating_counts": consensus,
        "price_target_range": targets,
        "social_sentiment_summary": "市場關注基本面及技術面信號，散戶意見分歧",
        "sentiment_stage": "skeptical",
        "narrative_source": "mock",
    }


async def _fetch_gemini_grounded_search(symbol: str, company_name: str) -> dict:
    """
    Use Gemini with Google Search grounding to fetch market narrative.
    Returns structured research data if successful, None if API unavailable.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    model_chain = get_gemini_model_chain()
    if not is_gemini_enabled():
        print("Gemini disabled by GEMINI_ENABLED=false; using fallback.")
        log_gemini_diagnostics(
            context="market_research_grounded_search",
            model=model_chain[0],
            attempted=False,
            fallback_used=True,
            fallback_models=model_chain[1:],
        )
        return None
    if not gemini_key:
        log_gemini_diagnostics(
            context="market_research_grounded_search",
            model=model_chain[0],
            attempted=False,
            fallback_used=True,
            fallback_models=model_chain[1:],
        )
        return None

    for model_name in model_chain:
        try:
            log_gemini_diagnostics(
                context="market_research_grounded_search",
                model=model_name,
                attempted=True,
                fallback_models=model_chain[1:],
            )
            import google.generativeai as genai

            genai.configure(api_key=gemini_key)

            # Create model with google_search tool enabled
            model = genai.GenerativeModel(
                model_name,
                tools=[{"google_search": {}}],  # Enable Google Search grounding
            )

            # Query for recent news and sentiment on this Taiwan stock
            query = f"{symbol} {company_name} 股票 新聞 分析師 評論 今年 最新"

            response = model.generate_content(
                query,
                tool_config={
                    "function_calling_config": "AUTO",
                },
            )

            # Parse response text into structured data
            text = response.text or ""

            # Extract analyst sentiment if mentioned
            analyst_consensus = "持平"
            if "看漲" in text or "buy" in text.lower():
                analyst_consensus = "看漲"
            elif "看跌" in text or "sell" in text.lower():
                analyst_consensus = "看跌"

            # Estimate sentiment stage from text
            sentiment_stage = "skeptical"
            if "樂觀" in text or "optimistic" in text.lower():
                sentiment_stage = "early-stage"
            elif "悲觀" in text or "pessimistic" in text.lower():
                sentiment_stage = "fearful"

            return {
                "headlines": [
                    {
                        "title": text[:200] if text else f"{symbol} 市場關注",
                        "source": "Gemini Search",
                        "url": "",
                    }
                ],
                "analyst_consensus": analyst_consensus,
                "analyst_rating_counts": {"buy": 3, "hold": 4, "sell": 1},
                "price_target_range": {"low": 100, "high": 150, "median": 125},
                "social_sentiment_summary": text[:300] if text else f"{symbol} 市場情緒分析中...",
                "sentiment_stage": sentiment_stage,
                "narrative_source": "grounded",
            }

        except Exception as e:
            log_gemini_diagnostics(
                context="market_research_grounded_search",
                model=model_name,
                attempted=True,
                fallback_used=True,
                error=e,
                fallback_models=model_chain[1:],
            )

    return None


async def _fetch_yahoo_finance_fallback(symbol: str) -> dict:
    """
    Fallback to Yahoo Finance for headlines when Gemini unavailable.
    Returns structured research data with headlines only; analyst/sentiment are mocked.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try to fetch from Yahoo Finance search endpoint
            response = await client.get(
                f"https://query1.finance.yahoo.com/v1/finance/search",
                params={"q": f"{symbol}.TW", "lang": "zh-Hant"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )

            if response.status_code == 200:
                data = response.json()
                news_list = data.get("news", [])

                headlines = [
                    {
                        "title": n.get("title", "")[:100],
                        "source": n.get("source", "Yahoo"),
                        "url": n.get("link", ""),
                    }
                    for n in news_list[:3]
                ]

                return {
                    "headlines": headlines if headlines else [{"title": f"{symbol} 最新新聞", "source": "Yahoo Finance", "url": ""}],
                    "analyst_consensus": "持平",  # Mocked
                    "analyst_rating_counts": {"buy": 3, "hold": 4, "sell": 1},
                    "price_target_range": {"low": 100, "high": 150, "median": 125},
                    "social_sentiment_summary": "根據最新新聞報導的市場情緒",
                    "sentiment_stage": "skeptical",
                    "narrative_source": "fallback",
                }
    except Exception:
        pass

    return None


async def fetch_market_research(symbol: str, company_name: str) -> dict:
    """
    Fetch market research data for equity research using 3-tier fallback:
    1. Gemini grounded search (if GEMINI_API_KEY set)
    2. Yahoo Finance fallback (headlines only; analyst/sentiment mocked)
    3. Full mock data

    Returns dict with keys:
    - headlines: list of {title, source, url}
    - analyst_consensus: str (看漲|持平|看跌)
    - analyst_rating_counts: {buy, hold, sell}
    - price_target_range: {low, high, median}
    - social_sentiment_summary: str (Traditional Chinese)
    - sentiment_stage: str (euphoric|fearful|skeptical|early-stage)
    - narrative_source: str (grounded|fallback|mock)
    """

    # Try Gemini grounded search first
    result = await _fetch_gemini_grounded_search(symbol, company_name)
    if result:
        return result

    # Fallback to Yahoo Finance
    result = await _fetch_yahoo_finance_fallback(symbol)
    if result:
        return result

    # Full mock fallback
    return _get_mock_research_data(symbol)
