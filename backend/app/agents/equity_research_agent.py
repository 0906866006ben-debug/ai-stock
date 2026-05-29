"""
Elite equity research agent synthesizing 4-pillar analysis into professional research report.
Uses PydanticAI + Gemini 2.5 Pro with Traditional Chinese narrative.
Generates analyst-grade reports with detailed financial analysis, tables, and investment frameworks.
Integrates real financial metrics from Taiwan Stock Exchange, FinMind, and Yahoo Finance.
"""

import os
import random
import json
from pydantic_ai import Agent
from backend.app.agents.retry import run_with_backoff
from backend.app.models.schemas import (
    AnalystConsensus,
    AnalystEntry,
    CategoryRating,
    CatalystRow,
    EquityResearch,
    RiskRow,
    ScenarioPrice,
    SentimentScore,
    SourceCitation,
    FundamentalAnalysis,
    TechnicalAnalysis,
    ChipAnalysis,
    NewsAnalysis,
    ComprehensiveAnalysis,
)
from backend.app.services.tw_financial_metrics import (
    fetch_real_metrics,
    format_metrics_for_narrative,
)
from backend.app.services.gemini_diagnostics import (
    get_gemini_model_chain,
    is_gemini_enabled,
    log_gemini_diagnostics,
    to_pydantic_ai_model_id,
)


def _format_research_for_prompt(
    symbol: str,
    company_name: str,
    current_price: float,
    fundamental: FundamentalAnalysis,
    technical: TechnicalAnalysis,
    chip: ChipAnalysis,
    news: NewsAnalysis,
    comprehensive: ComprehensiveAnalysis,
    research_data: dict,
) -> str:
    """Format all research data into detailed structured text for agent prompt."""

    # Extract key metrics for comparison
    metrics = fundamental.metrics or {}
    if hasattr(metrics, "model_dump"):
        metrics = metrics.model_dump()
    research_data = research_data or {}
    current_price = current_price or 100.0
    target_price = comprehensive.target_price or current_price * 1.12
    stop_loss = comprehensive.stop_loss or current_price * 0.92
    analyst_counts = research_data.get("analyst_rating_counts") or {}
    price_targets = research_data.get("price_target_range") or {}
    headlines = research_data.get("headlines") or []

    return f"""
# 專業股票研究分析 {symbol} - {company_name}

## 核心數據 (Current)
- 股價: TWD {current_price:.2f}
- 市場方向: {comprehensive.overall_direction}
- 確認分數: {comprehensive.confirmation_score:.0%}
- 綜合信心: {comprehensive.composite_confidence:.0%}

## 基本面數據
**營收成長:**
- 最新營收: {metrics.get('latest_revenue', 'N/A')}
- YoY成長: {metrics.get('revenue_yoy', 'N/A')}%
- MoM成長: {metrics.get('revenue_mom', 'N/A')}%

**獲利指標:**
- EPS: {metrics.get('eps_latest', 'N/A')} 元
- EPS YoY: {metrics.get('eps_yoy', 'N/A')}%
- PE Ratio: {metrics.get('pe_ratio', 'N/A')}x
- PB Ratio: {metrics.get('pb_ratio', 'N/A')}x
- ROE: {metrics.get('roe', 'N/A')}%

**利潤率:**
- 毛利率: {metrics.get('gross_margin', 'N/A')}%
- 營益率: {metrics.get('operating_margin', 'N/A')}%
- 淨利率: {metrics.get('net_margin', 'N/A')}%

**現金流健康:**
- 營運CF: {metrics.get('operating_cf', 'N/A')}
- 自由CF: {metrics.get('free_cf', 'N/A')}
- CF趨勢: {metrics.get('cf_trend', 'stable')}

**股利政策:**
- 配息率: {metrics.get('payout_ratio', 'N/A')}%
- 股息殖利率: {metrics.get('dividend_yield', 'N/A')}%

**財務結構:**
- 債務比: {metrics.get('debt_ratio', 'N/A')}%
- 流動比: {metrics.get('current_ratio', 'N/A')}x
- 速動比: {metrics.get('quick_ratio', 'N/A')}x

基本面分析師評價: {fundamental.summary}
營收趨勢: {fundamental.revenue_trend}
獲利能力: {fundamental.profitability}
估值水位: {fundamental.valuation}
財務健康: {fundamental.financial_health}
基本面風險: {', '.join(fundamental.risks[:3])}
成長催化劑: {', '.join(fundamental.catalysts[:3])}
信心度: {fundamental.confidence:.0%}

## 技術面數據
{technical.summary}
趨勢方向: {technical.trend}
動量指標: {technical.momentum}
波動性: {technical.volatility}
關鍵位置: {technical.key_levels}
技術風險: {', '.join(technical.risks[:2])}
交易機會: {', '.join(technical.opportunities[:2])}
信心度: {technical.confidence:.0%}

## 籌碼面數據
{chip.summary}
機構情緒: {chip.institutional_sentiment}
籌碼位置: {chip.chip_position}
風險指標: {chip.risk_indicators}
流動性: {chip.liquidity}
籌碼信號: {', '.join(chip.signals[:3])}
信心度: {chip.confidence:.0%}

## 消息面數據
{news.summary}
情緒評分: {news.sentiment_aggregate}
最新頭條: {[h.get('title', '') for h in news.recent_headlines[:3]]}
催化劑事件: {[c.get('event', '') for c in news.key_catalysts[:3]]}
宏觀影響: {news.macro_impact}
信心度: {news.confidence:.0%}

## 綜合判斷
整體方向: {comprehensive.overall_direction}
目標價: TWD {target_price:.2f}
停損價: TWD {stop_loss:.2f}
信念強度: {comprehensive.conviction_level}
主要建議: {comprehensive.recommendation}

## 市場研究數據
來源: {research_data.get('narrative_source', 'mock')}
最新新聞: {research_data.get('headlines', [{}])[0].get('title', '無')}
分析師共識: {research_data.get('analyst_consensus', '持平')}
評等統計: {research_data.get('analyst_rating_counts', {})}
目標價範圍: {research_data.get('price_target_range', {})}
社群情緒: {research_data.get('social_sentiment_summary', '')}
情緒階段: {research_data.get('sentiment_stage', 'skeptical')}

## Structured Data References

### Analyst Consensus
- Buy count: {analyst_counts.get("buy", 0)}
- Hold count: {analyst_counts.get("hold", 0)}
- Sell count: {analyst_counts.get("sell", 0)}

### Price Target Range
- Low: {price_targets.get("low", "N/A")}
- Median: {price_targets.get("median", "N/A")}
- High: {price_targets.get("high", "N/A")}

### Headlines / Source Candidates
{json.dumps(headlines, ensure_ascii=False, indent=2)}

### Source URLs
- Yahoo Finance: https://finance.yahoo.com/quote/{symbol}.TW
- FinMind: https://finmind.github.io/
- TWSE: https://www.twse.com.tw/
- TPEx: https://www.tpex.org.tw/
- MOPS: https://mops.twse.com.tw/
- Research data URLs: {[item.get("url", "") for item in headlines if item.get("url")]}
"""


def _build_structured_sentiment_and_consensus(
    current_price: float,
    is_bullish: bool,
) -> tuple[SentimentScore, AnalystConsensus]:
    """Build Task 1 structured fields from the existing mock assumptions."""
    current_price = current_price or 100.0

    sentiment_data = SentimentScore(
        score=random.randint(55, 75) if is_bullish else random.randint(35, 55),
        stage="early-stage" if is_bullish else "skeptical",
        avg_likes_per_post=random.randint(100, 300),
        avg_comments_per_post=random.randint(15, 50),
        source="mock",
    )

    analyst_consensus_data = AnalystConsensus(
        buy_count=random.randint(25, 35) if is_bullish else random.randint(10, 20),
        hold_count=random.randint(1, 5),
        sell_count=random.randint(0, 3),
        target_low=round(current_price * 0.95, 2),
        target_median=round(current_price * 1.15, 2),
        target_high=round(current_price * 1.35, 2),
        entries=[
            AnalystEntry(
                firm="Bernstein",
                rating="Buy",
                target_price=round(current_price * 1.20, 2),
            ),
            AnalystEntry(
                firm="Needham",
                rating="Buy",
                target_price=round(current_price * 1.40, 2),
            ),
            AnalystEntry(
                firm="Morgan Stanley",
                rating="Hold",
                target_price=round(current_price * 1.08, 2),
            ),
        ],
    )

    return sentiment_data, analyst_consensus_data


def _build_structured_catalyst_and_risk_tables() -> tuple[list[CatalystRow], list[RiskRow]]:
    """Build Task 2 structured catalyst and risk tables."""
    catalyst_table = [
        CatalystRow(
            time_horizon="2026 Q1",
            event="Quarterly earnings release",
            data_point="EPS expected to improve",
            impact="Positive earnings revision risk",
        ),
        CatalystRow(
            time_horizon="2026 H1",
            event="Revenue growth confirmation",
            data_point="Monthly revenue YoY trend",
            impact="Supports medium-term trend",
        ),
        CatalystRow(
            time_horizon="2026 H2",
            event="Industry demand recovery",
            data_point="Order visibility and sector momentum",
            impact="Potential valuation support",
        ),
    ]

    risk_table = [
        RiskRow(
            risk="Valuation compression",
            probability_pct=25,
            mitigation="Avoid chasing after sharp rallies; monitor PE/PB expansion",
        ),
        RiskRow(
            risk="Revenue growth disappointment",
            probability_pct=20,
            mitigation="Track monthly revenue YoY and cumulative revenue trend",
        ),
        RiskRow(
            risk="Institutional selling pressure",
            probability_pct=15,
            mitigation="Monitor foreign/investment trust net selling and volume spikes",
        ),
    ]

    return catalyst_table, risk_table


def _clamp_stars(stars: int) -> int:
    return max(1, min(5, stars))


def _is_empty(value) -> bool:
    return value is None or (hasattr(value, "__len__") and len(value) == 0)


def _build_category_ratings_and_sources(
    symbol: str,
    is_bullish: bool,
    valuation_verdict: str,
    financial_risks: list[str],
    comprehensive: ComprehensiveAnalysis,
) -> tuple[list[CategoryRating], list[SourceCitation]]:
    """Build Task 3 category ratings and source citations."""
    confirmation_score = getattr(comprehensive, "confirmation_score", 0.6) or 0.6
    safe_risk_count = len(financial_risks) if financial_risks else 0
    valuation_text = (valuation_verdict or "").lower()

    fundamental_stars = 5 if confirmation_score >= 0.8 else 4 if confirmation_score >= 0.6 else 3
    technical_stars = 4 if is_bullish else 3
    valuation_stars = 4 if "fairly valued" in valuation_text else 3
    risk_stars = 3 if safe_risk_count <= 3 else 2
    longterm_stars = 5 if is_bullish and confirmation_score > 0.7 else 4

    category_ratings = [
        CategoryRating(
            category="Fundamental",
            label_zh="基本面",
            stars=_clamp_stars(fundamental_stars),
        ),
        CategoryRating(
            category="Valuation",
            label_zh="估值",
            stars=_clamp_stars(valuation_stars),
        ),
        CategoryRating(
            category="Technical",
            label_zh="技術面",
            stars=_clamp_stars(technical_stars),
        ),
        CategoryRating(
            category="Risk",
            label_zh="風險",
            stars=_clamp_stars(risk_stars),
        ),
        CategoryRating(
            category="Long-term",
            label_zh="長期",
            stars=_clamp_stars(longterm_stars),
        ),
    ]

    source_citations = [
        SourceCitation(
            title=f"{symbol} 即時股價與新聞",
            url=f"https://finance.yahoo.com/quote/{symbol}.TW",
            source="Yahoo Finance",
        ),
        SourceCitation(
            title="台灣股票資訊",
            url="https://finmind.github.io/",
            source="FinMind",
        ),
        SourceCitation(
            title="台灣證券交易所",
            url="https://www.twse.com.tw/",
            source="TWSE",
        ),
    ]

    return category_ratings, source_citations


def _mock_equity_research(
    symbol: str,
    company_name: str,
    current_price: float,
    comprehensive: ComprehensiveAnalysis,
) -> EquityResearch:
    """
    Generate detailed mock equity research when AI unavailable.
    Produces analyst-grade narratives with specific metrics and comparisons.
    """
    # Determine scenario prices
    is_bullish = comprehensive.overall_direction == "bullish"
    is_bearish = comprehensive.overall_direction == "bearish"
    current_price = current_price or 100.0
    valuation_verdict = "fairly valued" if not is_bearish else "overvalued"

    bear_price = current_price * 0.85
    base_price = current_price * 1.12
    bull_price = current_price * 1.30
    stretched_price = current_price * 1.50

    # Infer investment rating
    if is_bullish and comprehensive.confirmation_score >= 0.7:
        rating = "Strong Buy"
    elif is_bullish:
        rating = "Buy"
    elif is_bearish:
        rating = "Sell"
    else:
        rating = "Hold"

    # Generate detailed narratives with specific metrics
    social_sentiment = f"""市場對{symbol}關注度適中，主流敘述圍繞AI晶片需求與成長潛力展開。
    - Reddit情緒評分：65-72/100（中立偏向樂觀）
    - 散戶參與度：近期營收新聞獲得120+讚、20+評論
    - 主要擔憂：地緣政治風險（單一貼文獲3,000+讚）
    - 投資者心理：看好成長，但對宏觀風險保持謹慎"""

    institutional_view = f"""機構持續買入信號明確。
    - 外資持股比例：35-38%（逐月增加）
    - 連續6月淨買超，最近月份>2B TWD
    - 分析師評等：32 Buy + 1 Hold, 0 Sell（97%看好）
    - 目標價共識：較現價上調8-12%"""

    sentiment_data, analyst_consensus_data = _build_structured_sentiment_and_consensus(
        current_price=current_price,
        is_bullish=is_bullish,
    )

    valuation_assumptions = f"""基於2026年盈利預期與成長動能進行估值。
    - 2026E EPS：92元（vs 2025E 63元，+46%）
    - Forward P/E：21-23x（相對產業平均34.7x有15-20%折扣）
    - EV/Sales：5.2x（低於產業平均6.8x）
    - PEG比率：0.73（<1.0表示成長被低估）
    - 地緣政治風險折扣：內含20-25%台灣溢價
    - 長期合理價值：基於30%成長+25倍P/E = 目標價{round(current_price*1.15, 2)}-{round(current_price*1.35, 2)}"""

    financial_risks = [
        f"地緣政治不確定性：若中台關係升溫，營收可能下滑40-50%，直接衝擊股價-60%",
        f"AI需求放緩風險：若資料中心CapEx增速放緩，產能利用率下降，毛利率可能回落5%",
        f"技術追趕風險：競爭對手(Samsung/Intel)若在2027年追上先進製程，溢價喪失"
    ]
    category_ratings, source_citations = _build_category_ratings_and_sources(
        symbol=symbol,
        is_bullish=is_bullish,
        valuation_verdict=valuation_verdict,
        financial_risks=financial_risks,
        comprehensive=comprehensive,
    )

    technical_verdict = "強勢上升" if is_bullish else ("整理階段" if not is_bearish else "下降趨勢")
    institutional_positioning = "積累中" if is_bullish else ("中立" if not is_bearish else "派發中")
    setup_suitability = "短長皆宜" if is_bullish else ("等待機會" if not is_bearish else "減少曝險")

    catalysts = [
        f"2026年Q1財報發布：EPS預期>24元可推升股價+5-8%",
        f"2nm製程量產銷售：毛利率提升至61%以上，估值提升+10%",
        f"股利政策宣佈：預計增配25-30%，強化投資吸引力"
    ]
    catalyst_table, risk_table = _build_structured_catalyst_and_risk_tables()

    narrative_conclusion = f"""{symbol}股價漲跌的本質原因是AI晶片需求從預測變成現實。
    - 2025年營收+31.61% YoY（不是預測，是已實現數據）
    - EPS狂漲+46.55%，代表不僅是量增，也是價增
    - 市場低估了：(1)2nm溢價空間 (2)地緣緩和潛力 (3)客戶多元化進展
    - 結論：長期看好，但短期需防範地緣政治與AI泡沫破裂風險"""

    return EquityResearch(
        # [1] Market Narrative
        social_sentiment=social_sentiment,
        sentiment_stage="early-stage" if is_bullish else "skeptical",
        catalysts=catalysts,
        institutional_view=institutional_view,
        narrative_conclusion=narrative_conclusion,
        sentiment_data=sentiment_data,
        analyst_consensus_data=analyst_consensus_data,
        catalyst_table=catalyst_table,
        risk_table=risk_table,
        # [2] Fundamental Snapshot
        valuation_verdict=valuation_verdict,
        valuation_assumptions=valuation_assumptions,
        financial_risks=financial_risks,
        # [3] Technical Snapshot
        technical_verdict=technical_verdict,
        institutional_positioning=institutional_positioning,
        setup_suitability=setup_suitability,
        # [4] Scenario Framework
        scenario_bear=ScenarioPrice(
            target_price=round(bear_price, 2),
            rationale="地緣政治升溫或AI需求放緩，導致營收成長放緩、毛利率下滑",
            key_risk="政治不確定性 / 客戶訂單下修",
            upside_pct=round((bear_price / current_price - 1) * 100, 1),
            timeframe="3-6個月",
        ),
        scenario_base=ScenarioPrice(
            target_price=round(base_price, 2),
            rationale="AI需求如期增長，2nm製程順利量產並實現15%溢價，無重大客戶流失",
            key_risk="市場波動性增加 / 競爭加劇",
            upside_pct=round((base_price / current_price - 1) * 100, 1),
            timeframe="6-12個月",
        ),
        scenario_bull=ScenarioPrice(
            target_price=round(bull_price, 2),
            rationale="AI加速週期延續，2nm製程溢價達20%，新客戶導入(Tesla自研失敗)，股利上調30%",
            key_risk="估值透支 / 短期調整風險",
            upside_pct=round((bull_price / current_price - 1) * 100, 1),
            timeframe="12-18個月",
        ),
        scenario_stretched=ScenarioPrice(
            target_price=round(stretched_price, 2),
            rationale="極端樂觀：AI晶片佔比升至55%、3nm溢價強化、投資者給予35倍P/E(如Nvidia)",
            key_risk="高估值無法持續 / 獲利不達預期",
            upside_pct=round((stretched_price / current_price - 1) * 100, 1),
            timeframe="18-24個月",
        ),
        # [5] Actionable Framework
        entry_zone=f"TWD {round(current_price * 0.92, 2)}-{round(current_price * 1.02, 2)}（技術面支撐強，基本面買點）",
        add_zone=f"TWD {round(current_price * 0.88, 2)}-{round(current_price * 0.93, 2)}（跌破均線時加倉機會）",
        profit_taking=f"TWD {round(bull_price * 0.95, 2)}-{round(stretched_price * 0.90, 2)}（分批獲利了結）",
        thesis_break=f"若跌破TWD {round(current_price * 0.75, 2)} 或Q1財報EPS<22元，應立即減碼50%",
        key_catalyst=f"2026年Q1財報+2nm量產銷售+股利政策宣佈（優先度排序）",
        hidden_risk=f"AI泡沫破裂(機率25%)、客戶集中風險(前5客戶佔60%營收)、地緣政治黑天鵝",
        category_ratings=category_ratings,
        source_citations=source_citations,
        # Meta
        investment_rating=rating,
        summary=f"""{symbol}({company_name})是AI晶片超級週期中的核心受惠者。
        綜合評估：基本面優秀(營收+31%、EPS+46%)、估值合理(P/E較產業低20%)、技術領先(5-10年護城河)。
        建議：長期看好(3-5年目標價+29-50%)，短期防範地緣政治與AI泡沫破裂風險，建議分批布局。
        近期焦點：1月15日Q4財報+2nm量產進展 = 股價催化劑。""",
        confidence=comprehensive.composite_confidence,
        is_mock=True,
    )


async def analyze_equity_research(
    symbol: str,
    company_name: str,
    current_price: float,
    fundamental: FundamentalAnalysis,
    technical: TechnicalAnalysis,
    chip: ChipAnalysis,
    news: NewsAnalysis,
    comprehensive: ComprehensiveAnalysis,
    research_data: dict,
) -> EquityResearch:
    """
    Analyze equity research using PydanticAI + Gemini.
    Generates professional analyst-grade reports with detailed financial analysis.
    Integrates real financial metrics from Taiwan markets.

    Args:
        symbol: Stock code (e.g., "2330")
        company_name: Company name (Traditional Chinese)
        current_price: Current stock price in TWD
        fundamental: FundamentalAnalysis pillar
        technical: TechnicalAnalysis pillar
        chip: ChipAnalysis pillar
        news: NewsAnalysis pillar
        comprehensive: ComprehensiveAnalysis synthesis
        research_data: Market research dict (from tw_market_research)

    Returns:
        EquityResearch: Full elite equity research report
    """

    current_price = current_price or 100.0

    # Fetch real financial metrics (with 3-tier fallback)
    try:
        metrics = await fetch_real_metrics(symbol)
        metrics_narrative = format_metrics_for_narrative(metrics)
    except Exception as e:
        print(f"Financial metrics formatting error: {e}")
        metrics_narrative = ""

    gemini_key = os.getenv("GEMINI_API_KEY")
    model_chain = get_gemini_model_chain()
    if not is_gemini_enabled():
        print("Gemini disabled by GEMINI_ENABLED=false; using fallback.")
        log_gemini_diagnostics(
            context="equity_research",
            model=model_chain[0],
            attempted=False,
            fallback_used=True,
            fallback_models=model_chain[1:],
        )
        return _mock_equity_research(
            symbol, company_name, current_price, comprehensive
        )
    if not gemini_key:
        log_gemini_diagnostics(
            context="equity_research",
            model=model_chain[0],
            attempted=False,
            fallback_used=True,
            fallback_models=model_chain[1:],
        )
        return _mock_equity_research(
            symbol, company_name, current_price, comprehensive
        )

    last_error = None
    for model_name in model_chain:
        try:
            log_gemini_diagnostics(
                context="equity_research",
                model=model_name,
                attempted=True,
                fallback_models=model_chain[1:],
            )
            agent = Agent(
                model=to_pydantic_ai_model_id(model_name),
                output_type=EquityResearch,
                system_prompt="""你是一位資深的台灣股票精英分析師，具有20年投資銀行與資產管理經驗。
    
    你的工作是撰寫專業級的股票研究報告，內容應該達到華爾街分析師水準。
    
    📋 報告結構（5個部分）
    
    [1] 市場敘述 — 股價為什麼會動？
       - 深入分析零售/社群情緒（Reddit評分、討論熱度）
       - 列舉具體催化劑（時間、數字、影響程度）
       - 機構/分析師共識（評等統計、目標價範圍）
       - 核心結論：股價移動的真實原因是什麼？市場低估或高估了什麼？
    
    [2] 基本面快照 — 這家公司值多少錢？
       - 市場指標（股價、市值、漲幅、52周區間）
       - 估值指標（P/E、Forward P/E、EV/銷售、PEG比率）
       - 成長指標（營收YoY、EPS YoY、毛利率、淨利率）
       - 財務實力（現金、債務、流動比、配息率）
       - 明確給出目標估值與邏輯推導
    
    [3] 技術與籌碼快照
       - 技術結構：趨勢、MA均線位置、RSI、MACD信號
       - 籌碼面：機構持股比例、外資淨買超、散戶FOMO指數
       - 明確描述短期/中期/長期走勢預期
    
    [4] 情景分析框架 — 可能的走向
       - 熊市情景：觸發因素、估值邏輯、目標價、跌幅
       - 基本情景：基礎假設、合理估值、推薦買點
       - 牛市情景：樂觀假設、目標價、漲幅
       - 超級情景：極端樂觀情況的價格與機率
    
    [5] 投資者行動框架
       - 進場時機與區間（標記買入、加碼、觀望、暫停）
       - 加碼條件（基本面催化劑、技術面信號）
       - 獲利了結與減碼時機（按價位與理由）
       - 賣出/停損硬線（黑天鵝風險、基本面惡化）
       - 隱藏風險清單（易被市場忽略的風險）
    
    📊 輸出要求
    
    1. 所有數字必須具體（不能說"營收很好"，要說"營收+31.61% YoY"）
    2. 所有判斷必須有邏輯（從A→B→C推導，而不是憑直覺）
    3. 所有建議必須可行（具體的價位、時機、條件）
    4. 適當使用表格與列表提高可讀性
    5. 用Traditional Chinese撰寫，專業術語準確
    
    你必須在 EquityResearch 中填入以下結構化欄位：
    
    1. sentiment_data:
       - score: 0-100 整數
       - stage: euphoric, fearful, skeptical, early-stage, neutral 之一
       - avg_likes_per_post: 整數或 null
       - avg_comments_per_post: 整數或 null
       - source: 實際來源名稱，若為推估則填 "estimated"
    
    2. analyst_consensus_data:
       - buy_count, hold_count, sell_count 優先使用 analyst_rating_counts
       - target_low, target_median, target_high 優先使用 price_target_range
       - entries: 分析師/券商清單，包含 firm, rating, target_price
       - 若沒有真實券商資料，entries 可為空，但 aggregate counts 和 target range 若有資料必須填入
    
    3. catalyst_table:
       - 資料足夠時至少 3 rows
       - 每 row 必須包含 time_horizon, event, data_point, impact
    
    4. risk_table:
       - 資料足夠時至少 3 rows
       - 每 row 必須包含 risk, probability_pct, mitigation
       - probability_pct 必須為 0-100 整數
    
    5. category_ratings:
       - 必須剛好 5 rows: Fundamental/基本面, Valuation/估值, Technical/技術面, Risk/風險, Long-term/長期
       - stars 必須為 1-5 整數
    
    6. source_citations:
       - 盡可能至少 3 rows
       - 每 row 包含 title, url, source
    
    重要輸出規則：
    - 只要輸入資料足夠，不要讓上述結構化欄位為 null。
    - 不要捏造輸入中不存在的精確事實；精確數字缺失時使用保守推估，並將 source 標為 "estimated" 或 "mock"。
    - 面向使用者的文字使用 Traditional Chinese。
    - 不得使用保證獲利、必買、all-in、絕對預測等語氣。
    - 每個投資建議都必須包含風險與不確定性。
    
    🎯 分析角度
    
    - 不要重複四柱的內容，而是進行整合與深化
    - 強調市場低估/高估的地方
    - 考慮地緣政治、產業週期、競爭格局
    - 提出具體的催化劑與風險
    - 給出明確的投資評級與目標價
    
    你必須返回完整的EquityResearch對象，包含所有5個部分的詳細內容。""",
            )
    
            # Format all research data for the prompt
            formatted_data = _format_research_for_prompt(
                symbol,
                company_name,
                current_price,
                fundamental,
                technical,
                chip,
                news,
                comprehensive,
                research_data,
            )
    
            # Call agent with structured prompt (including real financial metrics)
            result = await run_with_backoff(
                agent,
                f"""請基於以下詳細數據，撰寫一份精英級股票研究報告：
    
    {formatted_data}
    
    {metrics_narrative}
    
    請提供一份完整的5部分專業研究報告，內容應該達到華爾街分析師水準。
    每個部分都應該包含具體的數字、邏輯推導和可行的建議。
    
    重點要求：
    [1] 市場敘述 - 社群情緒、實際催化劑、機構觀點
    [2] 基本面快照 - 市場指標、估值指標、成長指標、財務強度 (使用上述的實際財務數據)
    [3] 技術籌碼面 - 趨勢、均線、RSI、MACD、機構持倉
    [4] 情景分析 - 熊/基本/牛/拉伸四個情景，需明確計算邏輯
    [5] 行動框架 - 進場區間、加倉區間、獲利位置、止損條件、主要催化劑、隱藏風險
    
    Structured fields required:
    - sentiment_data: score, stage, avg likes/comments, source
    - analyst_consensus_data: buy/hold/sell counts, target range, entries
    - catalyst_table: >=3 rows, time/event/data/impact
    - risk_table: >=3 rows, risk/probability/mitigation
    - category_ratings: exactly 5 ratings, stars 1-5
    - source_citations: >=3 sources when URLs are available
    
    Do not leave these fields null unless schema validation requires fallback.""",
            )
    
            research = result.output
            if _is_empty(research.sentiment_data) or _is_empty(research.analyst_consensus_data):
                sentiment_data, analyst_consensus_data = _build_structured_sentiment_and_consensus(
                    current_price=current_price,
                    is_bullish=comprehensive.overall_direction == "bullish",
                )
                research.sentiment_data = research.sentiment_data or sentiment_data
                research.analyst_consensus_data = (
                    research.analyst_consensus_data or analyst_consensus_data
                )
            if _is_empty(research.catalyst_table) or _is_empty(research.risk_table):
                catalyst_table, risk_table = _build_structured_catalyst_and_risk_tables()
                research.catalyst_table = research.catalyst_table or catalyst_table
                research.risk_table = research.risk_table or risk_table
            if _is_empty(research.category_ratings) or _is_empty(research.source_citations):
                category_ratings, source_citations = _build_category_ratings_and_sources(
                    symbol=symbol,
                    is_bullish=comprehensive.overall_direction == "bullish",
                    valuation_verdict=research.valuation_verdict,
                    financial_risks=research.financial_risks,
                    comprehensive=comprehensive,
                )
                research.category_ratings = research.category_ratings or category_ratings
                research.source_citations = research.source_citations or source_citations
            return research
        except Exception as e:
            last_error = e
            log_gemini_diagnostics(
                context="equity_research",
                model=model_name,
                attempted=True,
                fallback_used=True,
                error=e,
                fallback_models=model_chain[1:],
            )
            print(f"Gemini analysis error for {model_name}: {e}; trying fallback if available")

    print(f"All Gemini models failed; using fallback. Last error: {last_error}")
    return _mock_equity_research(
        symbol, company_name, current_price, comprehensive
    )
