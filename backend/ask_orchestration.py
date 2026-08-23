from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any


MAX_TOOL_CALLS = 3
MAX_RETRIES = 0
MAX_REPLANS = 0
OVERALL_BUDGET_SECONDS = max(4, min(20, int(os.getenv("ASK_TOOL_BUDGET_SECONDS", "10"))))


@dataclass(frozen=True)
class AskPlan:
    intent: str
    tools: tuple[str, ...]
    tickers: tuple[str, ...]
    confidence: float
    requires_portfolio: bool
    rationale: str
    limits: dict[str, int]

    def payload(self) -> dict[str, Any]:
        return {**asdict(self), "tools": list(self.tools), "tickers": list(self.tickers)}


_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MACRO_STATE", ("macro environment", "economic conditions", "recession risks", "rates and inflation", "macro risks", "macro factors")),
    ("MARKET_STATE", ("kind of market", "market risk-on", "market risk off", "risk-on or risk-off", "sectors are leading", "sector leadership", "market environment", "current market regime", "market regime")),
    ("PREDICTION_MARKETS", ("prediction markets matter", "probabilities changed", "market-implied risks", "prediction-market risks", "prediction market odds")),
    ("HISTORICAL_CHANGE", ("changed for", "since i last looked", "changed in macro since", "company score change")),
    ("DEEP_RESEARCH", ("deep research", "broad research", "research dossier", "full company research")),
    ("OPPORTUNITY_RANKING", ("strongest opportunities", "opportunities in my portfolio", "best opportunities in my portfolio")),
    ("THESIS_REPLACEMENT", ("weakest investment thesis", "weakest thesis", "replace it with", "replacement for")),
    ("PORTFOLIO_CHANGE", ("materially changed in my portfolio", "portfolio since my last review", "portfolio changed since")),
    ("VALUATION_RANKING", ("most overvalued", "overvalued relative to", "valuation relative to growth")),
    ("HIDDEN_RISK", (
        "hidden concentration risk", "across sectors", "correlated companies", "theme concentration",
        "where is my portfolio actually concentrated", "where is my portfolio concentrated",
        "actually concentrated", "concentration by sector", "concentration by theme",
    )),
    ("MULTI_SCENARIO", ("what would happen to my portfolio", "interest rates rose", "ai spending slowed", "economy entered a recession")),
    ("WATCHLIST_COMPARISON", ("watchlist stocks", "watchlist names", "stronger risk-adjusted case")),
    ("PORTFOLIO_EVENTS", ("upcoming earnings reports", "economic events", "company catalysts", "upcoming catalysts")),
    ("DATA_QUALITY", ("missing reliable data", "trust their rankings", "data coverage", "missing data")),
    ("SCORE_ATTRIBUTION", ("score change", "score changed", "inputs contributed", "why did this company")),
    ("THESIS_INVALIDATION", ("invalidate the thesis", "would invalidate", "largest positions")),
    ("MULTIFACTOR_SCREEN", ("improving fundamentals", "reasonable valuation", "positive momentum")),
    ("RECOMMENDATION_COUNTERCASE", ("arguments against", "top recommendation", "bear case against")),
    ("CASH_ALLOCATION", ("invested new cash", "new cash today", "better than holding cash", "where should it go")),
    ("BACKTEST", ("backtest", "historical test against", "five-year test against")),
    ("RETROSPECTIVE", ("why did i", "original decision", "decision journal", "retrospective", "mistakes repeat", "forecast calibration", "my decisions", "saved decisions", "decision history")),
    ("EARNINGS", ("earnings", "guidance", "estimate revision", "reported quarter", "beat estimates", "missed estimates")),
    ("CHANGE", ("what changed", "since last review", "different since", "new evidence", "material change")),
    ("THESIS", ("my thesis", "my theses", "saved thesis", "saved theses", "thesis breaker", "thesis status", "assumption status", "weakened a thesis")),
    ("SCENARIO", ("simulate", "what if", "stress test", "higher-for-longer", "oil shock", "recession scenario", "rate scenario")),
    ("RESEARCH_RANKING", ("strongest and weakest research", "strongest research evidence", "weakest research evidence", "rank my holdings", "rank the holdings", "best and worst research evidence", "worst stock holding", "worst holding", "weakest stock holding", "weakest holding")),
    ("BENCHMARK_OUTLOOK", ("outperform spy", "underperform spy", "beat spy", "lag spy", "relative to spy", "versus spy", "vs spy")),
    ("PORTFOLIO_ANALYSIS", ("balanced alternative", "risk-controlled alternative", "goal-tilted alternative", "rebalance", "rebalancing", "optimizer", "target weight", "allocation change", "improve diversification", "without silently changing my constraints", "move out", "exit candidates", "stocks to remove", "holdings to remove")),
    ("PORTFOLIO_RISK", ("biggest risks", "saved portfolio risk", "portfolio risks", "portfolio concentrated", "portfolio concentration", "where am i most concentrated", "most concentrated", "hidden exposure", "same macro risk", "shared macro", "risk contribution", "risk contributors", "fragile")),
    ("COMPARISON", ("compare ", " versus ", " vs ", "stronger business", "which is better")),
    ("FORECAST", ("prediction market", "market pricing", "probability", "odds", "forecast", "fed cut", "export restriction")),
    ("TODAY", ("attention today", "what matters today", "review today", "requires my attention")),
    ("ADD_RESEARCH", ("add to my portfolio", "fit my portfolio", "portfolio fit", "consider owning", "research next")),
)


def _intent(question: str) -> str:
    lowered = " ".join(question.lower().split())
    scored: list[tuple[int, int, str]] = []
    for order, (intent, phrases) in enumerate(_INTENTS):
        matched = [phrase for phrase in phrases if phrase in lowered]
        if matched:
            scored.append((sum(max(1, len(phrase.split()) - 1) for phrase in matched), -order, intent))
    if scored:
        return max(scored)[2]
    return "COMPANY_RESEARCH" if re.search(r"\b[A-Z]{1,5}\b", question) else "GENERAL"


def _tickers(question: str, page_context: dict[str, Any] | None, previous: dict[str, Any] | None) -> tuple[str, ...]:
    stop = {"I", "A", "AN", "AI", "ETF", "ETFS", "SEC", "CPI", "GDP", "FED", "USD", "CEO", "THE", "WHAT", "WHEN", "WHY", "HOW"}
    found = [value for value in re.findall(r"\b[A-Z]{1,5}\b", question) if value not in stop]
    context_ticker = str((page_context or {}).get("ticker") or "").upper().strip()
    if context_ticker and context_ticker not in found:
        found.append(context_ticker)
    if not found:
        found.extend(str(value).upper() for value in (previous or {}).get("tickers", [])[:3])
    return tuple(dict.fromkeys(value for value in found if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", value)))[:3]


def build_plan(question: str, workspace: str, page_context: dict[str, Any] | None = None,
               previous_analysis: dict[str, Any] | None = None) -> AskPlan:
    intent = _intent(question)
    tickers = _tickers(question, page_context, previous_analysis)
    mappings = {
        "OPPORTUNITY_RANKING": ("portfolio_overview",),
        "THESIS_REPLACEMENT": ("thesis_replacement",),
        "PORTFOLIO_CHANGE": ("portfolio_change",),
        "VALUATION_RANKING": ("valuation_ranking",),
        "HIDDEN_RISK": ("portfolio_intelligence",),
        "MULTI_SCENARIO": ("portfolio_scenario",),
        "WATCHLIST_COMPARISON": ("watchlist_comparison",),
        "PORTFOLIO_EVENTS": ("portfolio_events",),
        "DATA_QUALITY": ("data_quality",),
        "SCORE_ATTRIBUTION": ("score_attribution",),
        "THESIS_INVALIDATION": ("thesis_invalidation",),
        "MULTIFACTOR_SCREEN": ("multifactor_screen",),
        "RECOMMENDATION_COUNTERCASE": ("recommendation_countercase",),
        "CASH_ALLOCATION": ("cash_allocation",),
        "BACKTEST": ("portfolio_backtest",),
        "RETROSPECTIVE": ("decision_journal",),
        # Earnings intelligence already joins the latest saved thesis-monitor
        # result for the requested ticker. Running thesis_monitor again only
        # repeats owner-scoped database work and lengthens the answer path.
        "EARNINGS": ("company_analysis",),
        "CHANGE": ("historical_change",),
        "THESIS": ("thesis_monitor",),
        "SCENARIO": ("portfolio_scenario",),
        "RESEARCH_RANKING": ("security_ranking",),
        "BENCHMARK_OUTLOOK": ("benchmark_outlook",),
        "PORTFOLIO_ANALYSIS": ("portfolio_analysis",),
        "PORTFOLIO_RISK": ("portfolio_risk",),
        "COMPARISON": ("company_comparison",),
        "FORECAST": ("prediction_markets",),
        "MACRO_STATE": ("macro_state",),
        "MARKET_STATE": ("market_state",),
        "PREDICTION_MARKETS": ("prediction_markets",),
        "HISTORICAL_CHANGE": ("historical_change",),
        "DEEP_RESEARCH": ("company_research",),
        "TODAY": ("today_attention",),
        "ADD_RESEARCH": ("company_research", "portfolio_intelligence", "thesis_monitor", "prediction_markets"),
        "COMPANY_RESEARCH": ("company_analysis",),
        "GENERAL": ("stored_evidence",),
    }
    enabled = set((page_context or {}).get("enabled_context") or ("evidence", "thesis", "portfolio"))
    tools = list(mappings[intent])
    previous_structured = (previous_analysis or {}).get("analytical_context") if isinstance((previous_analysis or {}).get("analytical_context"), dict) else (previous_analysis or {})
    if intent == "GENERAL" and re.search(r"\b(?:visualize|visualise|plot|graph|chart)\b(?:\s+that|\s+this|\s+it)?|\brefresh\b.*\b(?:analysis|data|view|dashboard|verified)\b", question, re.I):
        prior_capabilities = [str(value) for value in previous_structured.get("active_capabilities", [])]
        registered = [value for value in prior_capabilities if value in {
            "company_analysis", "company_comparison", "portfolio_risk", "portfolio_intelligence",
            "macro_state", "market_state", "prediction_markets", "portfolio_scenario", "portfolio_backtest",
        }]
        if registered:
            tools = registered[:MAX_TOOL_CALLS]
            intent = str((previous_analysis or {}).get("intent") or "COMPOSED_ANALYSIS")
    if intent == "SCENARIO" and any(phrase in question.lower() for phrase in (
        "which holding", "holdings affected", "portfolio exposure", "risk contribution",
    )):
        tools.append("portfolio_intelligence")
    if intent in {"CHANGE", "HISTORICAL_CHANGE", "EARNINGS", "COMPARISON", "COMPANY_RESEARCH", "DEEP_RESEARCH"} and not tickers:
        tools = ["stored_evidence"]
    portfolio_tools = {
        "portfolio_overview", "thesis_replacement", "portfolio_change", "valuation_ranking",
        "portfolio_intelligence", "portfolio_scenario", "watchlist_comparison", "portfolio_events",
        "data_quality", "score_attribution", "multifactor_screen", "recommendation_countercase",
        "cash_allocation", "thesis_invalidation", "portfolio_analysis", "portfolio_risk", "security_ranking", "benchmark_outlook", "portfolio_backtest",
    }
    if "portfolio" not in enabled:
        tools = [tool for tool in tools if tool not in portfolio_tools]
    if "thesis" not in enabled:
        tools = [tool for tool in tools if tool != "thesis_monitor"]
    if "evidence" not in enabled:
        tools = [tool for tool in tools if tool not in {"stored_evidence", "evidence_changes", "company_research", "company_analysis", "company_comparison", "earnings_intelligence", "forecasting", "macro_state", "market_state", "prediction_markets", "historical_change"}]
    tools = list(dict.fromkeys(tools))[:MAX_TOOL_CALLS]
    requires_portfolio = bool(set(tools) & portfolio_tools) or (
        intent in {"MACRO_STATE", "MARKET_STATE", "PREDICTION_MARKETS", "FORECAST", "COMPARISON"}
        and any(phrase in question.lower() for phrase in ("my portfolio", "portfolio fit", "portfolio exposure", "portfolio risk"))
    )
    confidence = 0.98 if intent != "GENERAL" else 0.35
    return AskPlan(
        intent=intent,
        tools=tuple(tools),
        tickers=tickers,
        confidence=confidence,
        requires_portfolio=requires_portfolio,
        rationale=f"Selected the smallest approved tool set for {intent.lower().replace('_', ' ')}.",
        limits={"max_tool_calls": MAX_TOOL_CALLS, "max_retries": MAX_RETRIES,
                "max_replans": MAX_REPLANS, "overall_seconds": OVERALL_BUDGET_SECONDS},
    )


def execution_state(status: str) -> str:
    return {
        "complete": "SUCCESS", "success": "SUCCESS", "partial": "PARTIAL",
        "failed": "FAILED", "unavailable": "UNAVAILABLE",
    }.get(str(status).lower(), "PARTIAL")


def actions_for(plan: AskPlan, page_context: dict[str, Any] | None = None) -> list[dict[str, str]]:
    ticker = plan.tickers[0] if plan.tickers else str((page_context or {}).get("ticker") or "").upper()
    actions: list[dict[str, str]] = []
    research_tickers = list(plan.tickers[:2]) or ([ticker] if ticker else [])
    actions.extend(
        {"label": f"Open {symbol} research", "href": f"/research?view=stocks&ticker={symbol}", "kind": "research"}
        for symbol in research_tickers
    )
    if plan.intent in {"SCENARIO", "PORTFOLIO_ANALYSIS", "PORTFOLIO_RISK", "BENCHMARK_OUTLOOK", "ADD_RESEARCH", "COMPARISON"}:
        actions.append({"label": "Open portfolio intelligence", "href": "/portfolio?view=analysis", "kind": "portfolio"})
    if plan.intent == "THESIS" and not ticker:
        actions.append({"label": "Open company research", "href": "/research?view=stocks", "kind": "research"})
    if plan.intent == "RETROSPECTIVE":
        actions.append({"label": "Open research workspace", "href": "/research", "kind": "research"})
    return actions[:3]


def previous_analysis_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(messages):
        structured = item.get("structured_content") or {}
        context = structured.get("analysis_context") if isinstance(structured, dict) else None
        if isinstance(context, dict):
            return context
    return {}
