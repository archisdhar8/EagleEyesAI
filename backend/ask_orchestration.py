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
    rationale: str
    limits: dict[str, int]

    def payload(self) -> dict[str, Any]:
        return {**asdict(self), "tools": list(self.tools), "tickers": list(self.tickers)}


_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("RETROSPECTIVE", ("why did i", "original decision", "decision journal", "retrospective", "mistakes repeat", "forecast calibration")),
    ("EARNINGS", ("earnings", "guidance", "estimate revision", "reported quarter", "beat estimates", "missed estimates")),
    ("CHANGE", ("what changed", "since last review", "different since", "new evidence", "material change")),
    ("THESIS", ("my thesis", "thesis breaker", "thesis status", "assumption status", "weakened a thesis")),
    ("SCENARIO", ("simulate", "what if", "stress test", "higher-for-longer", "oil shock", "recession scenario", "rate scenario")),
    ("RESEARCH_RANKING", ("strongest and weakest research", "strongest research evidence", "weakest research evidence", "rank my holdings", "rank the holdings", "best and worst research evidence", "worst stock holding", "worst holding", "weakest stock holding", "weakest holding")),
    ("PORTFOLIO_ANALYSIS", ("balanced alternative", "risk-controlled alternative", "goal-tilted alternative", "rebalance", "rebalancing", "optimizer", "target weight", "allocation change", "improve diversification", "without silently changing my constraints")),
    ("PORTFOLIO_RISK", ("biggest risks", "saved portfolio risk", "portfolio risks", "portfolio concentrated", "portfolio concentration", "hidden exposure", "same macro risk", "shared macro", "risk contribution", "fragile")),
    ("COMPARISON", ("compare ", " versus ", " vs ", "stronger business", "which is better")),
    ("FORECAST", ("prediction market", "market pricing", "probability", "odds", "forecast", "fed cut", "export restriction")),
    ("TODAY", ("attention today", "what matters today", "review today", "requires my attention")),
    ("ADD_RESEARCH", ("add to my portfolio", "fit my portfolio", "portfolio fit", "consider owning", "research next")),
)


def _intent(question: str) -> str:
    lowered = " ".join(question.lower().split())
    for intent, phrases in _INTENTS:
        if any(phrase in lowered for phrase in phrases):
            return intent
    return "COMPANY_RESEARCH" if re.search(r"\b[A-Z]{1,5}\b", question) else "GENERAL"


def _tickers(question: str, page_context: dict[str, Any] | None, previous: dict[str, Any] | None) -> tuple[str, ...]:
    stop = {"AI", "ETF", "SEC", "CPI", "GDP", "FED", "USD", "CEO", "WHAT", "WHEN", "WHY", "HOW"}
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
        "RETROSPECTIVE": ("decision_journal",),
        "EARNINGS": ("earnings_intelligence", "thesis_monitor"),
        "CHANGE": ("evidence_changes", "thesis_monitor"),
        "THESIS": ("thesis_monitor", "evidence_changes"),
        "SCENARIO": ("portfolio_scenario",),
        "RESEARCH_RANKING": ("security_ranking",),
        "PORTFOLIO_ANALYSIS": ("portfolio_analysis",),
        "PORTFOLIO_RISK": ("portfolio_risk",),
        "COMPARISON": ("company_comparison", "portfolio_intelligence"),
        "FORECAST": ("forecasting", "thesis_monitor"),
        "TODAY": ("today_attention",),
        "ADD_RESEARCH": ("company_research", "portfolio_intelligence", "thesis_monitor", "forecasting"),
        "COMPANY_RESEARCH": ("company_research",),
        "GENERAL": ("stored_evidence",),
    }
    enabled = set((page_context or {}).get("enabled_context") or ("evidence", "thesis", "portfolio"))
    tools = list(mappings[intent])
    if intent == "SCENARIO" and any(phrase in question.lower() for phrase in (
        "which holding", "holdings affected", "portfolio exposure", "risk contribution",
    )):
        tools.append("portfolio_intelligence")
    if intent in {"CHANGE", "THESIS", "EARNINGS", "COMPARISON", "COMPANY_RESEARCH"} and not tickers:
        tools = ["stored_evidence"]
    if "portfolio" not in enabled:
        tools = [tool for tool in tools if tool not in {"portfolio_analysis", "portfolio_intelligence", "portfolio_scenario"}]
    if "thesis" not in enabled:
        tools = [tool for tool in tools if tool != "thesis_monitor"]
    if "evidence" not in enabled:
        tools = [tool for tool in tools if tool not in {"stored_evidence", "evidence_changes", "company_research", "company_comparison", "earnings_intelligence", "forecasting"}]
    tools = list(dict.fromkeys(tools))[:MAX_TOOL_CALLS]
    return AskPlan(
        intent=intent,
        tools=tuple(tools),
        tickers=tickers,
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
    if ticker:
        actions.extend([
            {"label": f"Open {ticker} research", "href": f"/research?view=stocks&ticker={ticker}", "kind": "research"},
            {"label": "Review thesis or record decision", "href": f"/decisions?ticker={ticker}", "kind": "decision"},
        ])
    if plan.intent in {"SCENARIO", "PORTFOLIO_ANALYSIS", "PORTFOLIO_RISK", "ADD_RESEARCH", "COMPARISON"}:
        actions.append({"label": "Open portfolio intelligence", "href": "/portfolio?view=analysis", "kind": "portfolio"})
    if plan.intent == "RETROSPECTIVE":
        actions.append({"label": "Open decision journal", "href": "/decisions?view=journal", "kind": "journal"})
    return actions[:3]


def previous_analysis_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(messages):
        structured = item.get("structured_content") or {}
        context = structured.get("analysis_context") if isinstance(structured, dict) else None
        if isinstance(context, dict):
            return context
    return {}
