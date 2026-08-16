from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from . import database
from .analysis import latest_macro, macro_factor_dashboard, security_research
from .chat import _candidate, _gemini_request
from .guidance import guidance_disclosure
from .scenarios import refresh as refresh_scenarios
from .resilience import RetryPolicy, retry_call


PLAN_VERSION = "dashboard-plan-v2"
COMPILER_VERSION = "dashboard-spec-compiler-v2"
CALCULATION_VERSION = "ai-workspace-calculations-v1.4.0"
TERMINAL_STATES = {"COMPLETE", "PARTIAL_SUCCESS", "FAILED", "CANCELLED", "EXPIRED"}
PLANNER_MAX_ATTEMPTS = max(1, min(2, int(os.getenv("DASHBOARD_PLANNER_MAX_ATTEMPTS", "2"))))
DASHBOARD_TASK_WAIT_SECONDS = max(10, min(60, int(os.getenv("DASHBOARD_TASK_TIMEOUT_SECONDS", "45"))))
DASHBOARD_NARRATIVE_WAIT_SECONDS = max(10, min(45, int(os.getenv("DASHBOARD_NARRATIVE_TIMEOUT_SECONDS", "30"))))
INTENTS = (
    "portfolio_review", "compare_securities", "research_candidates",
    "macro_analysis", "correlation_analysis", "scenario_analysis",
)
BLOCKED_PROMPT = re.compile(
    r"(?:drop\s+table|delete\s+from|ignore\s+(?:all|your)\s+instructions|"
    r"send\s+.*portfolio\s+to\s+https?://|execute\s+(?:python|javascript|sql)|"
    r"query\s+another\s+user|buy\s+\d+\s+shares)", re.I,
)


class UniversePlan(BaseModel):
    holdings: bool = True
    watchlist: bool = True
    cached_research: bool = True
    sector_etfs: bool = True
    explicitly_requested_tickers: list[str] = Field(default_factory=list, max_length=50)


class ResearchFilter(BaseModel):
    feature: str
    operator: Literal["gte", "lte", "eq"]
    value: float | str


class ResearchQueryPlan(BaseModel):
    universe: UniversePlan = Field(default_factory=UniversePlan)
    theme: str | None = None
    filters: list[ResearchFilter] = Field(default_factory=list, max_length=12)
    ranking_model: str = "transparent-research-composite-v1"
    required_features: list[str] = Field(default_factory=lambda: ["growth_rating", "valuation_score", "fundamental_score", "confidence"])
    minimum_data_quality: Literal["medium", "high"] = "medium"
    minimum_history_months: int = Field(default=24, ge=0, le=240)
    maximum_missing_feature_ratio: float = Field(default=.20, ge=0, le=1)
    portfolio_context: bool = True
    diversification_constraints: dict[str, float] = Field(default_factory=lambda: {"max_sector_share": .35})


class DashboardEntities(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=50)
    portfolio_id: str | None = None
    sectors: list[str] = Field(default_factory=list, max_length=20)
    themes: list[str] = Field(default_factory=list, max_length=20)


class DashboardPlan(BaseModel):
    version: str = PLAN_VERSION
    intent: Literal[
        "portfolio_review", "compare_securities", "research_candidates",
        "macro_analysis", "correlation_analysis", "scenario_analysis",
    ]
    entities: DashboardEntities = Field(default_factory=DashboardEntities)
    questions: list[str] = Field(default_factory=list, max_length=12)
    time_range: str = "1y"
    requested_outputs: list[str] = Field(default_factory=list, max_length=20)
    filters: dict[str, Any] = Field(default_factory=dict)
    research_query: ResearchQueryPlan | None = None
    ambiguities: list[str] = Field(default_factory=list, max_length=8)


class DraftRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=3000)
    portfolio_id: str | None = None
    conversation_id: str | None = None


class RevisionRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class SaveViewRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    layout: list[dict[str, Any]] | None = None


class UpdateViewRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    layout: list[dict[str, Any]] | None = None


class WidgetAddRequest(BaseModel):
    widget_type: str = Field(min_length=2, max_length=80)


class LayoutMutationRequest(BaseModel):
    operation: Literal["resize", "remove", "move"]
    width: int | None = None
    height: int | None = None
    direction: int | None = None


class DuplicateViewRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)


DATA_WIDGET_CATALOG: dict[str, dict[str, Any]] = {
    "portfolio_performance": {"label": "Portfolio performance", "group": "Portfolio", "description": "Cumulative adjusted-price return and annualized volatility.", "datasets": ["price_bars", "holdings"]},
    "allocation": {"label": "Current allocation", "group": "Portfolio", "description": "Saved position weights normalized to 100%.", "datasets": ["holdings"]},
    "drawdown": {"label": "Portfolio drawdown", "group": "Portfolio", "description": "Largest modeled peak-to-trough portfolio decline.", "datasets": ["price_bars", "holdings"]},
    "macro_trends": {"label": "Macro trend monitor", "group": "Macro", "description": "Rates, inflation, growth, labor, and credit observations.", "datasets": ["macro_observations"]},
    "historical_regimes": {"label": "Historical regimes", "group": "Macro", "description": "Point-in-time monthly regime sample counts.", "datasets": ["macro_regime_labels"]},
    "holdings_sensitivity": {"label": "Holdings macro sensitivity", "group": "Macro", "description": "Monthly holding-return sensitivity to the selected macro factor.", "datasets": ["price_bars", "macro_observations"]},
    "scenario_probabilities": {"label": "Scenario probabilities", "group": "Scenarios", "description": "FRED trends blended with validated Kalshi and Polymarket evidence.", "datasets": ["scenario_probabilities", "prediction_markets"]},
    "correlation_matrix": {"label": "Return correlations", "group": "Risk", "description": "Pairwise adjusted-return correlations for the portfolio.", "datasets": ["price_bars"]},
    "factor_correlation_candidates": {"label": "Macro-correlated candidates", "group": "Research", "description": "Candidate returns ranked by measured correlation with a named macro factor.", "datasets": ["price_bars", "macro_observations", "security_research_snapshots"]},
    "security_comparison": {"label": "Security research comparison", "group": "Research", "description": "Growth, valuation, quality, technical, and confidence scores.", "datasets": ["security_research_snapshots", "fundamental_observations"]},
    "research_universe": {"label": "Candidate universe", "group": "Research", "description": "Visible counts and names included in a research screen.", "datasets": ["securities", "holdings"]},
    "optimizer_comparison": {"label": "Constrained alternatives", "group": "Optimizer", "description": "Current portfolio versus the latest saved transparent alternatives.", "datasets": ["analysis_runs"]},
}


EXTRA_TASKS: dict[str, list[tuple[str, str, list[str], bool]]] = {
    "portfolio_performance": [("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False), ("performance", "portfolio_performance", ["portfolio", "prices"], True)],
    "allocation": [("portfolio", "portfolio_snapshot", [], False), ("allocation", "allocation", ["portfolio"], False)],
    "drawdown": [("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False), ("performance", "portfolio_performance", ["portfolio", "prices"], True), ("drawdown", "drawdown", ["performance"], True)],
    "macro_trends": [("macro", "macro_trends", [], True)],
    "historical_regimes": [("regimes", "historical_regimes", [], False)],
    "holdings_sensitivity": [("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False), ("macro", "macro_trends", [], True), ("scenarios", "scenario_probabilities", [], True), ("sensitivity", "holdings_sensitivity", ["portfolio", "prices", "macro", "scenarios"], True)],
    "scenario_probabilities": [("scenarios", "scenario_probabilities", [], True)],
    "correlation_matrix": [("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False), ("correlations", "correlation_matrix", ["prices"], True)],
    "security_comparison": [("research", "security_research", [], False), ("comparison", "security_comparison", ["research"], True)],
    "research_universe": [("portfolio", "portfolio_snapshot", [], False), ("universe", "research_universe", ["portfolio"], True)],
    "optimizer_comparison": [("portfolio", "portfolio_snapshot", [], False), ("optimizer", "optimizer_comparison", ["portfolio"], False)],
}


def _clean_tickers(values: list[str]) -> list[str]:
    blocked = {"I", "SHOW", "FIND", "WHAT", "WITH", "FROM", "THAT", "THIS", "STOCK", "STOCKS", "MACRO", "RISK", "BUY", "SELL", "YEAR", "RETURN"}
    return list(dict.fromkeys(value.upper() for value in values if re.fullmatch(r"[A-Za-z]{1,10}", value) and value.upper() not in blocked))[:50]


def deterministic_plan(prompt: str, portfolio_id: str | None = None) -> DashboardPlan:
    if BLOCKED_PROMPT.search(prompt):
        raise ValueError("The request contains an unsupported action. Dashboard prompts cannot execute code, SQL, trades, or external data transfers.")
    lower = prompt.lower()
    tickers = _clean_tickers(re.findall(r"\b[A-Z]{1,10}\b", prompt))
    macro_sensitivity = any(word in lower for word in ("sensitive", "sensitivity", "react most", "exposed")) and any(word in lower for word in ("inflation", "cpi", "pce", "rate", "fed", "treasury", "yield", "unemployment", "credit", "oil", "growth"))
    candidate_request = any(word in lower for word in ("candidate", "which stocks", "what stocks", "find stocks", "buy", "undervalued", "screen", "sector beneficiaries", "benefit from")) or bool(re.search(r"\bwhich\s+\w+\s+stocks\b", lower))
    if any(term in lower for term in ("what would change", "what evidence would change", "invalidate", "invalidation", "thesis risk")) and tickers:
        intent = "compare_securities"
    elif candidate_request:
        intent = "research_candidates"
    elif any(word in lower for word in ("next dollar", "next $", "contribution-only", "contribution only", "contributions only", "stale evidence")):
        intent = "portfolio_review"
    elif "compare my portfolio" in lower:
        intent = "portfolio_review"
    elif any(word in lower for word in ("compare", " versus ", " vs ")) and len(tickers) >= 2:
        intent = "compare_securities"
    elif any(word in lower for word in ("correlat", "diversif", "overlap")):
        intent = "correlation_analysis"
    elif any(word in lower for word in ("scenario", "soft landing", "recession", "oil shock", "combined macro", "combined conditions", "stagflation")):
        intent = "scenario_analysis"
    elif macro_sensitivity:
        intent = "macro_analysis"
    elif any(word in lower for word in ("portfolio return", "my return", "drawdown", "allocation", "concentration", "next dollar", "next $", "contribution-only", "contribution only", "stale evidence")):
        intent = "portfolio_review"
    elif any(word in lower for word in ("this week", "weekly", "last 5 days", "past week")):
        intent = "portfolio_review"
    elif any(word in lower for word in ("macro", "inflation", "interest rate", "fed", "unemployment", "credit")):
        intent = "macro_analysis"
    else:
        intent = "portfolio_review"
    range_match = re.search(r"\bover\s+(\d+)\s*[- ]?(?:y|yr|year)s?\b", lower) or re.search(r"\b(\d+)\s*[- ]?(?:y|yr|year)s?\b", lower)
    word_years = {"one": 1, "three": 3, "five": 5, "seven": 7, "ten": 10, "twenty": 20}
    word_match = re.search(r"\bover\s+(" + "|".join(word_years) + r")[- ]year", lower) or re.search(r"\b(" + "|".join(word_years) + r")[- ]year", lower)
    if word_match and word_match.group(0).startswith("over "):
        time_range = f"{word_years[word_match.group(1)]}y"
    else:
        time_range = f"{min(20, int(range_match.group(1)))}y" if range_match else f"{word_years[word_match.group(1)]}y" if word_match else "1y"
    outputs = {
        "portfolio_review": ["performance", "drawdown", "allocation", "macro_risk", "lineage"],
        "compare_securities": ["comparison", "valuation", "growth", "performance", "drawdown", "risks"],
        "research_candidates": ["universe", "ranking", "evidence", "portfolio_fit"],
        "macro_analysis": ["macro_trends", "scenarios", "historical_regimes", "holdings_sensitivity"],
        "correlation_analysis": ["correlation_matrix", "diversification", "stability"],
        "scenario_analysis": ["scenario_probabilities", "history", "security_sensitivity"],
    }[intent]
    research_query = None
    if intent == "research_candidates":
        theme = next((term for term in ("AI infrastructure", "semiconductors", "energy", "healthcare") if term.lower() in lower), None)
        research_query = ResearchQueryPlan(
            universe=UniversePlan(explicitly_requested_tickers=tickers), theme=theme,
            filters=[ResearchFilter(feature="confidence", operator="gte", value=55)],
        )
    macro_factor = next((factor for factor, terms in {
        "inflation": ("inflation", "cpi", "pce"),
        "credit": ("credit", "spread", "lending", "high-yield"),
        "rates": ("interest rate", "rates", "fed", "treasury", "yield"),
        "unemployment": ("unemployment", "labor", "jobs"),
        "oil": ("oil", "crude", "wti"),
        "growth": ("growth", "gdp", "industrial production"),
    }.items() if any(term in lower for term in terms)), None)
    scenario_focus = next((key for key, terms in {
        "oil_shock": ("oil shock", "oil scenario"), "recession_cuts": ("recession", "rate-cutting", "cutting cycle"),
        "sticky_inflation": ("sticky inflation",), "soft_landing": ("soft landing",),
        "growth_reacceleration": ("growth reacceleration",),
    }.items() if any(term in lower for term in terms)), None)
    plan_filters: dict[str, Any] = {}
    if macro_factor: plan_filters["macro_factor"] = macro_factor
    if intent == "research_candidates" and "correlat" in lower and macro_factor:
        plan_filters["factor_correlation"] = macro_factor
    if scenario_focus: plan_filters["scenario_focus"] = scenario_focus
    if any(term in lower for term in ("this week", "weekly", "last 5 days", "past week")):
        plan_filters["weekly_market_changes"] = True; outputs.append("weekly_market_changes")
    if any(term in lower for term in ("sector beneficiaries", "which sectors benefit", "benefit from")):
        plan_filters["sector_beneficiaries"] = True; outputs.append("sector_beneficiaries")
    if any(term in lower for term in ("contribution-only", "contribution only", "contributions only")):
        plan_filters["contribution_only"] = True; outputs.append("contribution_only_diversification")
    if "next dollar" in lower or re.search(r"next\s+\$?\d+",lower):
        plan_filters["next_dollar_research"] = True; outputs.append("next_dollar_research")
    if any(term in lower for term in ("what would change", "what evidence would change", "invalidate", "invalidation", "thesis risk")):
        plan_filters["thesis_invalidation"] = True; outputs.append("thesis_invalidation")
    if "stale" in lower and any(term in lower for term in ("evidence","data","audit")):
        plan_filters["stale_evidence_audit"] = True; outputs.append("stale_evidence_audit")
    combined=[]
    for state,terms in {"recession":("recession",),"accelerating_inflation":("accelerating inflation","sticky inflation","stagflation"),
                        "rate_tightening":("rate tightening","higher rates"),"oil_shock":("oil shock",),"credit_shock":("credit shock",)}.items():
        if any(term in lower for term in terms): combined.append(state)
    if len(combined)>1:
        plan_filters["combined_states"]=combined
        outputs.append("combined_macro_states")
    benchmark_match=re.search(r"benchmark(?:ed|ing)?(?: against| to| versus| vs)?\s+([A-Z]{1,10})",prompt,re.IGNORECASE)
    if benchmark_match:
        benchmark=benchmark_match.group(1).upper(); plan_filters["requested_benchmark"]=benchmark
        if benchmark not in tickers: tickers.append(benchmark)
    return DashboardPlan(
        intent=intent, entities=DashboardEntities(tickers=tickers, portfolio_id=portfolio_id),
        questions=outputs, time_range=time_range, requested_outputs=outputs,
        filters=plan_filters, research_query=research_query,
    )


def _planner_prompt(prompt: str, fallback: DashboardPlan, portfolio: dict[str, Any] | None) -> str:
    context = {
        "portfolio_id": portfolio.get("id") if portfolio else None,
        "holding_tickers": [row["ticker"] for row in (portfolio or {}).get("holdings", [])],
        "supported_intents": INTENTS,
        "fallback_interpretation": fallback.model_dump(mode="json"),
    }
    return f"""You are the low-creativity intent planner for an investment research dashboard.
Return JSON only. Do not create widgets, layouts, formulas, SQL, code, allocations, or buy/sell instructions.
Select one supported intent and identify entities, questions, time range, requested outputs, filters, and ambiguities.
For stock-buy language, use research_candidates. Preserve explicitly named ticker symbols.
The output must validate against this shape: {json.dumps(DashboardPlan.model_json_schema())}
Context: {json.dumps(context, default=str)}
User request: {prompt}"""


def plan_dashboard(prompt: str, portfolio: dict[str, Any] | None = None) -> DashboardPlan:
    fallback = deterministic_plan(prompt, str(portfolio.get("id")) if portfolio else None)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    if not api_key:
        return fallback
    contents = [{"role": "user", "parts": [{"text": _planner_prompt(prompt, fallback, portfolio)}]}]
    for _ in range(PLANNER_MAX_ATTEMPTS):
        try:
            payload = _gemini_request(api_key, model, contents, 1800)
            text, _ = _candidate(payload)
            match = re.search(r"\{[\s\S]*\}", text)
            candidate = DashboardPlan.model_validate_json(match.group(0) if match else text)
            explicit_intent = any(term in prompt.lower() for term in (
                "portfolio return", "my return", "drawdown", "allocation", "correlat", "overlap",
                "compare", "scenario", "recession", "oil shock", "sensitive", "sensitivity",
                "candidate", "find research", "which stocks", "what stocks",
            ))
            if explicit_intent:
                candidate.intent = fallback.intent
                candidate.requested_outputs = fallback.requested_outputs
            candidate.entities.tickers = _clean_tickers(candidate.entities.tickers)
            candidate.entities.portfolio_id = candidate.entities.portfolio_id or fallback.entities.portfolio_id
            candidate.filters = {**fallback.filters, **candidate.filters}
            if candidate.intent == "research_candidates" and candidate.research_query is None:
                candidate.research_query = fallback.research_query or ResearchQueryPlan()
            elif candidate.intent == "research_candidates" and fallback.research_query:
                candidate.research_query.theme = candidate.research_query.theme or fallback.research_query.theme
                candidate.research_query.universe = fallback.research_query.universe
            return candidate
        except (RuntimeError, ValidationError, ValueError) as exc:
            from .operational_monitoring import record_metric
            record_metric("gemini.planning_failure", tags={"error_type": type(exc).__name__, "model": model})
            contents.append({"role": "user", "parts": [{"text": "The prior output was invalid. Return one JSON object matching the schema exactly."}]})
    return fallback


TASK_TEMPLATES: dict[str, dict[str, Any]] = {
    "portfolio_review": {
        "title": "Portfolio return and macro risk",
        "tasks": [
            ("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False),
            ("performance", "portfolio_performance", ["portfolio", "prices"], True),
            ("drawdown", "drawdown", ["performance"], True), ("allocation", "allocation", ["portfolio"], True),
            ("macro", "macro_trends", [], True), ("scenarios", "scenario_probabilities", [], True),
            ("macro_risk", "macro_risk", ["portfolio", "macro", "scenarios"], False),
            ("optimizer", "optimizer_comparison", ["portfolio"], False),
        ],
    },
    "compare_securities": {
        "title": "Security comparison",
        "tasks": [
            ("prices", "price_history", [], False), ("research", "security_research", [], False),
            ("comparison", "security_comparison", ["research"], True),
            ("performance", "security_performance", ["prices"], True),
            ("drawdown", "security_drawdown", ["prices"], True),
            ("risks", "risk_summary", ["research"], True),
        ],
    },
    "research_candidates": {
        "title": "Research candidate screen",
        "tasks": [
            ("portfolio", "portfolio_snapshot", [], False), ("universe", "research_universe", ["portfolio"], True),
            ("research", "security_research", ["universe"], False),
            ("candidates", "candidate_ranking", ["research", "universe"], True),
            ("fit", "portfolio_fit", ["portfolio", "candidates"], False),
        ],
    },
    "macro_analysis": {
        "title": "Macro conditions and portfolio exposure",
        "tasks": [
            ("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False),
            ("macro", "macro_trends", [], True),
            ("scenarios", "scenario_probabilities", [], True), ("regimes", "historical_regimes", [], False),
            ("sensitivity", "holdings_sensitivity", ["portfolio", "prices", "macro", "scenarios"], True),
        ],
    },
    "correlation_analysis": {
        "title": "Correlation and diversification",
        "tasks": [
            ("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False),
            ("correlations", "correlation_matrix", ["prices"], True),
            ("diversification", "diversification_summary", ["portfolio", "correlations"], True),
            ("stability", "correlation_stability", ["prices", "correlations"], True),
        ],
    },
    "scenario_analysis": {
        "title": "Scenario evidence and security sensitivity",
        "tasks": [
            ("portfolio", "portfolio_snapshot", [], False), ("prices", "price_history", ["portfolio"], False),
            ("scenarios", "scenario_probabilities", [], True),
            ("history", "scenario_history", ["scenarios"], False),
            ("research", "security_research", ["portfolio"], False),
            ("sensitivity", "scenario_sensitivity", ["research", "scenarios", "prices"], True),
        ],
    },
}


WIDGET_META = {
    "portfolio_performance": ("Portfolio performance", "line", 8, 2), "drawdown": ("Portfolio drawdown", "area", 4, 2),
    "allocation": ("Current allocation", "bar", 4, 2), "macro_trends": ("Macro trend monitor", "cards", 8, 2),
    "scenario_probabilities": ("Scenario probabilities", "bar", 4, 2), "macro_risk": ("Portfolio macro risks", "table", 8, 2),
    "optimizer_comparison": ("Constrained alternatives", "comparison", 12, 2), "security_comparison": ("Research comparison", "table", 12, 2),
    "security_performance": ("Cumulative performance", "line", 8, 2), "security_drawdown": ("Security drawdown", "bar", 4, 2),
    "risk_summary": ("Risks and evidence gaps", "list", 12, 2), "research_universe": ("Candidate universe", "summary", 4, 2),
    "candidate_ranking": ("Ranked research candidates", "table", 8, 3), "portfolio_fit": ("Portfolio fit", "table", 12, 2),
    "factor_correlation_candidates": ("Macro-correlated candidates", "table", 12, 3),
    "historical_regimes": ("Historical regime library", "bar", 4, 2), "holdings_sensitivity": ("Holdings macro sensitivity", "table", 12, 2),
    "correlation_matrix": ("Return correlations", "heatmap", 8, 3), "diversification_summary": ("Diversification read", "summary", 4, 2),
    "correlation_stability": ("Correlation stability", "summary", 12, 2), "scenario_history": ("Scenario history", "line", 12, 2),
    "scenario_sensitivity": ("Scenario-sensitive securities", "table", 12, 3),
    "weekly_market_changes": ("Weekly market changes", "table", 12, 2),
    "next_dollar_research": ("Next-dollar research", "summary", 8, 2),
    "evidence_audit": ("Stale-evidence audit", "table", 12, 2),
    "thesis_invalidation": ("What would change the thesis", "table", 12, 2),
    "sector_beneficiaries": ("Potential sector beneficiaries", "table", 12, 2),
}


def compile_spec(plan: DashboardPlan) -> dict[str, Any]:
    template = TASK_TEMPLATES[plan.intent]
    task_template = list(template["tasks"])
    if plan.intent == "research_candidates" and plan.filters.get("factor_correlation"):
        task_template = [
            ("portfolio", "portfolio_snapshot", [], False),
            ("universe", "research_universe", ["portfolio"], True),
            ("prices", "price_history", ["universe"], False),
            ("research", "security_research", ["universe"], False),
            ("candidates", "factor_correlation_candidates", ["prices", "research", "universe"], True),
            ("fit", "portfolio_fit", ["portfolio", "candidates"], False),
        ]
    present_types = {item[1] for item in task_template}
    present_ids = {item[0] for item in task_template}
    for requested in plan.filters.get("additional_widgets", []):
        if requested not in EXTRA_TASKS or requested in present_types:
            continue
        for item in EXTRA_TASKS[requested]:
            if item[0] not in present_ids:
                task_template.append(item); present_ids.add(item[0]); present_types.add(item[1])
    specialized = [
        ("weekly_changes","weekly_market_changes",["prices"],True,"weekly_market_changes"),
        ("next_dollar","next_dollar_research",["portfolio"],True,"next_dollar_research"),
        ("evidence_audit","evidence_audit",[],True,"stale_evidence_audit"),
        ("thesis_invalidation","thesis_invalidation",["research"],True,"thesis_invalidation"),
        ("sector_beneficiaries","sector_beneficiaries",["research"],True,"sector_beneficiaries"),
    ]
    for task_id,task_type,dependencies,required,flag in specialized:
        if not plan.filters.get(flag) or task_type in present_types:
            continue
        if any(dep not in present_ids for dep in dependencies):
            continue
        task_template.append((task_id,task_type,dependencies,required));present_ids.add(task_id);present_types.add(task_type)
    tasks, widgets, row, column = [], [], 0, 0
    for task_id, task_type, dependencies, required in task_template:
        query = {"tickers": plan.entities.tickers, "time_range": plan.time_range, "filters": plan.filters}
        if plan.research_query:
            query["research_query"] = plan.research_query.model_dump(mode="json")
        tasks.append({
            "id": task_id, "task_type": task_type, "depends_on": dependencies,
            "required_for_narrative": required, "query": query,
            "calculation_version": CALCULATION_VERSION,
        })
        if task_type in WIDGET_META:
            title, visualization, width, height = WIDGET_META[task_type]
            if column + width > 12: row += 2; column = 0
            widgets.append({"id": task_id, "task_id": task_id, "widget_type": task_type,
                            "title": title, "visualization": visualization,
                            "grid": {"x": column, "y": row, "w": width, "h": height}})
            column += width
    validate_dag(tasks)
    return {"version": "dashboard-spec-v2", "spec_version":"dashboard-spec-v2",
            "layout_version":"dashboard-layout-v2", "compiler_version": COMPILER_VERSION,
            "title": template["title"], "description": f"Generated from {plan.intent.replace('_',' ')} intent.",
            "filters": {"time_range": plan.time_range}, "tasks": tasks, "widgets": widgets,
            "agent_pipeline": [
                {"agent": "planner", "responsibility": "Interpret the request and select evidence needs."},
                {"agent": "widget_builders", "responsibility": "Run approved data services and deterministic calculations."},
                {"agent": "widget_verifier", "responsibility": "Check lineage, units, time range, and result shape."},
                {"agent": "answer_reviewer", "responsibility": "Check whether the interpretation answers the original question."},
            ]}


def validate_dag(tasks: list[dict[str, Any]]) -> None:
    ids = {task["id"] for task in tasks}
    if len(ids) != len(tasks): raise ValueError("Duplicate dashboard task ID")
    if any(dep not in ids for task in tasks for dep in task.get("depends_on", [])):
        raise ValueError("Dashboard task has an unknown dependency")
    visiting, visited = set(), set()
    graph = {task["id"]: task.get("depends_on", []) for task in tasks}
    def visit(node: str) -> None:
        if node in visiting: raise ValueError("Dashboard task graph contains a cycle")
        if node in visited: return
        visiting.add(node)
        for dep in graph[node]: visit(dep)
        visiting.remove(node); visited.add(node)
    for node in graph: visit(node)


def _lineage(provider: str, dataset: str, symbols: list[str], effective: str | None,
             cache_status: str = "miss", version: str | None = None) -> dict[str, Any]:
    return {"provider": provider, "dataset": dataset, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "effective_through": effective, "symbols": symbols, "cache_status": cache_status,
            "dataset_version": version}


def _quality(level: str, reasons: list[str], **extra: Any) -> dict[str, Any]:
    return {"data_quality": level, "reasons": reasons, **extra}


def _presentation(task: dict[str, Any], data: Any) -> dict[str, Any]:
    task_type = task["task_type"]
    timeframe = str(task.get("query", {}).get("time_range") or "latest")
    definitions = {
        "portfolio_performance": {"chart": "line", "x_axis": "Date", "y_axis": "Cumulative total return", "unit": "%", "frequency": "Daily"},
        "security_performance": {"chart": "line", "x_axis": "Date", "y_axis": "Cumulative adjusted-price return", "unit": "%", "frequency": "Daily"},
        "drawdown": {"chart": "area", "x_axis": "Portfolio", "y_axis": "Maximum drawdown", "unit": "%", "frequency": "Daily"},
        "security_drawdown": {"chart": "bar", "x_axis": "Security", "y_axis": "Maximum drawdown", "unit": "%", "frequency": "Daily"},
        "allocation": {"chart": "bar", "x_axis": "Holding", "y_axis": "Portfolio weight", "unit": "%", "frequency": "Current snapshot"},
        "scenario_probabilities": {"chart": "bar", "x_axis": "Scenario", "y_axis": "Probability", "unit": "%", "frequency": "Latest snapshot"},
        "historical_regimes": {"chart": "bar", "x_axis": "Regime", "y_axis": "Monthly observations", "unit": "months", "frequency": "Monthly"},
        "correlation_matrix": {"chart": "heatmap", "x_axis": "Security", "y_axis": "Security", "unit": "correlation (-1 to +1)", "frequency": "Daily returns"},
        "factor_correlation_candidates": {"chart": "table", "x_axis": "Candidate", "y_axis": "Correlation with macro factor", "unit": "correlation (-1 to +1)", "frequency": "Monthly returns"},
        "holdings_sensitivity": {"chart": "table", "x_axis": "Holding", "y_axis": "Return sensitivity", "unit": (data or {}).get("units", "coefficient") if isinstance(data, dict) else "coefficient", "frequency": "Monthly"},
        "macro_trends": {"chart": "cards", "x_axis": "Macro factor", "y_axis": "Latest observation", "unit": "series-specific", "frequency": "Latest release"},
    }
    result = {"timeframe": timeframe, **definitions.get(task_type, {"chart": "table", "x_axis": "Category", "y_axis": "Value", "unit": "see columns", "frequency": "Latest available"})}
    series = data.get("series") if isinstance(data, dict) else None
    if isinstance(series, list) and series:
        result["period_start"], result["period_end"] = series[0].get("date"), series[-1].get("date")
    elif isinstance(series, dict) and series:
        first = next(iter(series.values()), [])
        if first:
            result["period_start"], result["period_end"] = first[0].get("date"), first[-1].get("date")
    return result


def _task_result(task: dict[str, Any], data: Any, *, lineage: list[dict[str, Any]], as_of: str | None,
                 quality: dict[str, Any], assumptions: list[str], warnings: list[str], how: str,
                 status: str = "READY") -> dict[str, Any]:
    return {"widget_id": task["id"], "status": status, "as_of": as_of or datetime.now(timezone.utc).isoformat(),
            "data": data, "lineage": lineage,
            "calculation": {"method": task["task_type"], "version": task["calculation_version"], "parameters": task.get("query", {})},
            "presentation": _presentation(task, data), "quality": quality, "assumptions": assumptions,
            "warnings": warnings, "how_calculated": how}


def verify_widget_result(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    checks, issues = [], []
    for field in ("as_of", "lineage", "calculation", "quality", "how_calculated", "presentation"):
        if result.get(field): checks.append(f"{field} present")
        else: issues.append(f"Missing required {field}")
    presentation = result.get("presentation") or {}
    for field in ("chart", "unit", "timeframe"):
        if presentation.get(field): checks.append(f"presentation.{field} present")
        else: issues.append(f"Missing presentation {field}")
    if task["task_type"] in {"portfolio_performance", "security_performance"}:
        if presentation.get("period_start") and presentation.get("period_end"):
            checks.append("plotted period labeled")
        else: issues.append("Chart period labels unavailable")
    if result.get("status") == "READY" and result.get("data") in ({}, [], None):
        issues.append("Result contains no displayable data")
    result["verification"] = {"agent": "widget_verifier", "status": "passed" if not issues else "warning", "checks": checks, "issues": issues}
    if issues:
        from .operational_monitoring import record_metric
        record_metric("dashboard.widget_verification_failure", tags={"task_type": task["task_type"], "calculation_version": task.get("calculation_version")})
    if issues:
        result.setdefault("warnings", []).extend(issue for issue in issues if issue not in result.get("warnings", []))
    return result


def _portfolio(user_id: str, requested_id: str | None = None) -> dict[str, Any]:
    if requested_id:
        try: return database.get_portfolio(requested_id, user_id)
        except KeyError: pass
    rows = database.list_portfolios(user_id)
    return rows[0] if rows else {"id": None, "name": "No portfolio", "holdings": []}


def _tickers(context: dict[str, Any], task: dict[str, Any], deps: dict[str, Any]) -> list[str]:
    explicit = _clean_tickers(task.get("query", {}).get("tickers", []))
    if explicit: return explicit
    universe = deps.get("universe", {}).get("data") or {}
    if universe.get("tickers"):
        return _clean_tickers(universe["tickers"])
    portfolio = deps.get("portfolio", {}).get("data") or context["portfolio"]
    return [row["ticker"] for row in portfolio.get("holdings", []) if row["ticker"] != "CASH"]


def _price_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows: return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    return frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().ffill()


MACRO_SENSITIVITY_FACTORS = {
    "inflation": {"series": "CPIAUCSL", "label": "inflation acceleration", "transform": "yoy_change"},
    "rates": {"series": "DGS10", "label": "10-year Treasury yield change", "transform": "change"},
    "unemployment": {"series": "UNRATE", "label": "unemployment-rate change", "transform": "change"},
    "credit": {"series": "BAMLH0A0HYM2", "label": "high-yield spread change", "transform": "change"},
    "oil": {"series": "DCOILWTICO", "label": "oil-price return", "transform": "return"},
    "growth": {"series": "INDPRO", "label": "industrial-growth acceleration", "transform": "yoy_change"},
}


def calculate_macro_sensitivity(
    price_rows: list[dict[str, Any]], macro_rows: list[dict[str, Any]], factor: str = "inflation",
) -> dict[str, Any]:
    """Estimate transparent monthly return sensitivity to one macro factor.

    The regression is descriptive rather than causal. Macro observations and
    monthly adjusted closes are aligned by calendar month before fitting OLS.
    """
    definition = MACRO_SENSITIVITY_FACTORS.get(factor, MACRO_SENSITIVITY_FACTORS["inflation"])
    prices = _price_frame(price_rows)
    if prices.empty:
        return {"factor": factor, "factor_label": definition["label"], "rows": [], "reason": "No adjusted security prices are available."}
    monthly_returns = prices.resample("ME").last().pct_change(fill_method=None)
    monthly_returns.index = monthly_returns.index.tz_localize(None).to_period("M")
    macro = pd.DataFrame(macro_rows)
    if macro.empty:
        return {"factor": factor, "factor_label": definition["label"], "rows": [], "reason": f"No {definition['series']} history is available."}
    macro["date"] = pd.to_datetime(macro["date"])
    macro = macro.sort_values(["date", "vintage_date"]).drop_duplicates("date", keep="last").set_index("date")["value"].astype(float).sort_index()
    if definition["transform"] == "yoy_change":
        signal = macro.pct_change(12, fill_method=None).mul(100).diff()
        units = "percentage-point monthly return per 1 percentage-point acceleration"
    elif definition["transform"] == "return":
        signal = macro.pct_change(fill_method=None).mul(100)
        units = "percentage-point monthly return per 1% macro move"
    else:
        signal = macro.diff()
        units = "percentage-point monthly return per 1-unit macro change"
    signal.index = signal.index.to_period("M")
    signal = signal.groupby(level=0).last().rename("macro_signal")
    output = []
    for ticker in monthly_returns.columns:
        sample = pd.concat([monthly_returns[ticker].rename("return"), signal], axis=1).dropna()
        if len(sample) < 24 or float(sample["macro_signal"].std()) <= 1e-10:
            continue
        x = sample["macro_signal"].to_numpy(dtype=float)
        y = sample["return"].to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(x)), x])
        coefficients, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
        residuals = y - design @ coefficients
        beta = float(coefficients[1])
        dof = max(1, len(x) - 2)
        variance = float((residuals @ residuals) / dof)
        inverse = np.linalg.pinv(design.T @ design)
        standard_error = float(np.sqrt(max(0, variance * inverse[1, 1])))
        t_stat = beta / standard_error if standard_error > 0 else 0.0
        correlation = float(np.corrcoef(x, y)[0, 1])
        total_variance = float(((y - y.mean()) ** 2).sum())
        r_squared = 1 - float((residuals ** 2).sum()) / total_variance if total_variance > 0 else 0.0
        midpoint = len(sample) // 2
        recent_x, recent_y = x[midpoint:], y[midpoint:]
        recent_beta = float(np.linalg.lstsq(np.column_stack([np.ones(len(recent_x)), recent_x]), recent_y, rcond=None)[0][1])
        sign_stable = beta == 0 or recent_beta == 0 or np.sign(beta) == np.sign(recent_beta)
        confidence = "high" if len(sample) >= 48 and abs(t_stat) >= 2 and sign_stable else "medium" if len(sample) >= 36 and abs(t_stat) >= 1 and sign_stable else "low"
        beta_pp = beta * 100
        output.append({
            "ticker": str(ticker), "beta": round(beta_pp, 4), "absolute_sensitivity": round(abs(beta_pp), 4),
            "correlation": round(correlation, 4), "r_squared": round(max(0, r_squared), 4),
            "t_stat": round(t_stat, 3), "observations": int(len(sample)), "confidence": confidence,
            "direction": "positive" if beta > 0 else "negative", "sign_stable": bool(sign_stable),
            "sample_start": str(sample.index.min()), "sample_end": str(sample.index.max()),
        })
    output.sort(key=lambda row: row["absolute_sensitivity"], reverse=True)
    return {"factor": factor, "factor_label": definition["label"], "series_id": definition["series"],
            "units": units, "rows": output, "minimum_observations": 24}


def execute_task(context: dict[str, Any], task: dict[str, Any], deps: dict[str, Any]) -> dict[str, Any]:
    task_type, now = task["task_type"], datetime.now(timezone.utc).isoformat()
    tickers = _tickers(context, task, deps)
    if task_type == "portfolio_snapshot":
        portfolio = context["portfolio"]
        return _task_result(task, portfolio, lineage=[_lineage("Supabase", "portfolios/holdings", tickers, portfolio.get("updated_at"))],
            as_of=portfolio.get("updated_at"), quality=_quality("high", ["Saved authenticated portfolio snapshot"]), assumptions=[], warnings=[],
            how="Loaded the authenticated user's saved portfolio and holdings without using an LLM calculation.")
    if task_type == "price_history":
        rows = database.price_history(tickers)
        providers = sorted({row["provider"] for row in rows})
        as_of = max((row["date"] for row in rows), default=now)
        covered = sorted({row["ticker"] for row in rows})
        warnings = [f"Missing adjusted price history for {ticker}." for ticker in tickers if ticker not in covered]
        return _task_result(task, rows, lineage=[_lineage("+".join(providers) or "Unavailable", "adjusted_daily_prices", covered, as_of)],
            as_of=as_of, quality=_quality("high" if len(covered)==len(tickers) and covered else "medium" if covered else "low",
            [f"{len(covered)} of {len(tickers)} requested symbols covered"]), assumptions=["Selected the longest coherent adjusted-price provider per symbol."],
            warnings=warnings, how="Loaded daily adjusted closes from the longest available provider history for each symbol.")
    if task_type == "security_research":
        if "universe" in deps: tickers = deps["universe"]["data"]["tickers"]
        rows = security_research(tickers[:50])
        as_of = max((row.get("price_as_of") or "" for row in rows), default=now) or now
        return _task_result(task, rows, lineage=[_lineage("Supabase/SEC/market providers", "security_research", tickers, as_of, version="research-score-v1")],
            as_of=as_of, quality=_quality("high" if rows and all(row["data_quality"]=="high" for row in rows) else "medium" if rows else "low",
            [f"{len(rows)} securities scored"], research_confidence="medium"), assumptions=["Scores are comparative research signals, not return forecasts."], warnings=[],
            how="Combined stored price, SEC fundamentals, industry, technical, news, and company prediction-market evidence using the transparent research score.")
    if task_type == "macro_trends":
        data = {"macro": latest_macro(), **macro_factor_dashboard()}; as_of=data["macro"].get("as_of")
        return _task_result(task,data,lineage=[_lineage("FRED", "macro_observations", [], as_of, version="macro-factor-v1")],as_of=as_of,
            quality=_quality("high" if as_of else "low",["Point-in-time macro observations" if as_of else "No current macro observation"]),assumptions=["Observed changes are not consensus surprises."],warnings=[] if as_of else ["Macro data unavailable."],
            how="Calculated current levels and recent changes from stored point-in-time FRED observations.")
    if task_type == "scenario_probabilities":
        data=refresh_scenarios(False); as_of=data.get("fetched_at")
        return _task_result(task,data,lineage=[_lineage("FRED/Kalshi/Polymarket","scenario_snapshot",[],as_of,version="scenario-blend-v2")],as_of=as_of,
            quality=_quality("medium",["Macro trend model blended with validated market evidence"],scenario_confidence="medium"),assumptions=["Weak market evidence is shrunk toward the FRED trend model and disclosed baseline."],warnings=data.get("warnings",[]),
            how="Blended the point-in-time FRED trend probability vector with confidence-weighted Kalshi and Polymarket contracts.")
    if task_type == "research_universe":
        profile=database.load_profile(context["user_id"]) or {}; holdings=[row["ticker"] for row in context["portfolio"].get("holdings",[]) if row["ticker"]!="CASH"]
        watchlist=[str(value).upper() for value in profile.get("watchlist",[])]; explicit=task["query"].get("research_query",{}).get("universe",{}).get("explicitly_requested_tickers",[])
        etfs=["SPY","QQQ","VTI","XLE","XLV","XLF","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]
        universe=list(dict.fromkeys([*holdings,*watchlist,*explicit,*etfs]))[:50]
        data={"tickers":universe,"counts":{"holdings":len(set(holdings)),"watchlist":len(set(watchlist)),"explicit":len(set(explicit)),"sector_etfs":len(set(etfs)),"total":len(universe)},"full_market_screen":False}
        return _task_result(task,data,lineage=[_lineage("Supabase","saved_research_universe",universe,now)],as_of=now,
            quality=_quality("high",["Universe is explicitly enumerated"]),assumptions=["This is not an all-market screen."],warnings=[],
            how="Combined saved holdings, watchlist names, explicitly requested tickers, and the supported broad/sector ETF set, then removed duplicates.")

    if task_type == "factor_correlation_candidates":
        factor = str(task.get("query", {}).get("filters", {}).get("factor_correlation") or "oil")
        definition = MACRO_SENSITIVITY_FACTORS.get(factor, MACRO_SENSITIVITY_FACTORS["oil"])
        macro_rows = database.macro_point_in_time_history([definition["series"]], limit_per_series=300)
        measured = calculate_macro_sensitivity(deps["prices"].get("data", []), macro_rows, factor)
        research_by_ticker = {row["ticker"]: row for row in deps["research"].get("data", [])}
        rows = []
        for row in measured.get("rows", []):
            research = research_by_ticker.get(row["ticker"], {})
            rows.append({
                **row,
                "company": research.get("company"), "sector": research.get("sector", "Unclassified"),
                "industry": research.get("industry"), "research_score": research.get("final_score"),
                "research_confidence": research.get("confidence"),
            })
        rows.sort(key=lambda row: abs(float(row.get("correlation", 0))), reverse=True)
        data = {
            "factor": factor, "factor_label": measured.get("factor_label", definition["label"]),
            "series_id": definition["series"], "rows": rows,
            "universe_count": len(deps["universe"].get("data", {}).get("tickers", [])),
            "ranking": "Absolute measured correlation, strongest first",
            "minimum_observations": measured.get("minimum_observations", 24),
        }
        macro_as_of = max((row["date"] for row in macro_rows), default=None)
        warnings = [] if rows else [measured.get("reason") or f"Insufficient overlapping history to measure correlation with {definition['label']}." ]
        lineage = [*deps["prices"].get("lineage", []), *deps["research"].get("lineage", []),
                   _lineage("FRED/ALFRED", definition["series"], [], macro_as_of, version="macro-factor-correlation-v1")]
        return _task_result(task, data, lineage=lineage, as_of=macro_as_of or deps["prices"].get("as_of"),
            quality=_quality("high" if rows and min(row["observations"] for row in rows) >= 48 else "medium" if rows else "low",
                [f"{len(rows)} of {data['universe_count']} universe securities have quantitative estimates", "Ranked by absolute correlation, not by the research composite"],
                model_confidence="medium" if rows else "low"),
            assumptions=["Correlation is descriptive, not causal.", "Monthly adjusted-price returns are aligned to point-in-time macro observations.", "Positive and negative relationships are both ranked by absolute strength."],
            warnings=warnings,
            how=f"Calculated monthly adjusted-price returns for every covered security in the explicit universe, aligned them with {definition['series']} ({definition['label']}), and ranked the resulting Pearson correlations by absolute magnitude. Research scores are shown as context but do not determine the correlation ranking.")

    # Derived tasks use only validated dependency outputs.
    if task_type in {"portfolio_performance","security_performance","security_drawdown","correlation_matrix","correlation_stability"}:
        price_result = deps.get("prices") or deps.get("performance") or {}
        rows = price_result.get("data", [])
        if task_type == "portfolio_performance" and "prices" in deps: rows=deps["prices"]["data"]
        frame=_price_frame(rows)
        years=int(str(task["query"].get("time_range","1y")).rstrip("y") or 1); frame=frame.tail(252*years)
        if frame.empty or len(frame)<2: raise ValueError("Insufficient adjusted price history")
        returns=frame.pct_change().dropna(how="all").fillna(0)
        if task_type == "portfolio_performance":
            holdings=context["portfolio"].get("holdings",[]); raw={row["ticker"]:float(row.get("weight") or 0) for row in holdings if row["ticker"] in returns.columns}
            total=sum(raw.values()) or len(raw); weights=pd.Series({key:(value/total if sum(raw.values()) else 1/total) for key,value in raw.items()})
            series=(returns[weights.index]*weights).sum(axis=1); cumulative=(1+series).cumprod()-1
            data={"total_return":float(cumulative.iloc[-1]),"annualized_volatility":float(series.std()*np.sqrt(252)),"series":[{"date":idx.date().isoformat(),"value":round(float(value),6)} for idx,value in cumulative.items()]}
            how="Calculated daily weighted portfolio returns from adjusted closes using normalized current weights, then compounded them. Historical holdings reconstruction is not available."
        elif task_type == "security_performance":
            normalized=frame/frame.iloc[0]-1; data={"series":{col:[{"date":idx.date().isoformat(),"value":round(float(value),6)} for idx,value in normalized[col].items()] for col in normalized}}
            how="Rebased each adjusted closing-price series to zero at the beginning of the selected period and calculated cumulative total return."
        elif task_type == "security_drawdown":
            dd=frame/frame.cummax()-1; data=[{"ticker":col,"max_drawdown":round(float(dd[col].min()),6)} for col in dd]
            how="Divided each adjusted close by its prior running maximum and reported the minimum value."
        elif task_type == "correlation_matrix":
            corr=returns.corr(min_periods=40); data={"tickers":list(corr.columns),"matrix":corr.fillna(0).round(4).values.tolist(),"observations":len(returns)}
            how="Calculated Pearson correlations from overlapping daily adjusted-price returns over the selected period."
        else:
            midpoint=max(20,len(returns)//2); first=returns.iloc[:midpoint].corr(); second=returns.iloc[midpoint:].corr(); common=first.columns.intersection(second.columns)
            drift=float((first.loc[common,common]-second.loc[common,common]).abs().mean().mean()) if len(common)>1 else 0
            data={"mean_absolute_correlation_change":round(drift,4),"observations":len(returns),"stable":drift<.20}
            how="Compared pairwise return correlations in the first and second halves of the selected sample."
        return _task_result(task,data,lineage=price_result.get("lineage",[]),as_of=price_result.get("as_of"),quality=_quality("high" if len(frame)>=252 else "medium",[f"{len(frame)} daily observations"],model_confidence="medium"),assumptions=["Relationships may change across regimes."],warnings=[],how=how)
    if task_type == "drawdown":
        series=deps["performance"]["data"]["series"]; values=pd.Series([row["value"]+1 for row in series]); dd=values/values.cummax()-1
        return _task_result(task,{"max_drawdown":round(float(dd.min()),6)},lineage=deps["performance"]["lineage"],as_of=deps["performance"]["as_of"],quality=deps["performance"]["quality"],assumptions=deps["performance"]["assumptions"],warnings=[],how="Calculated the largest peak-to-trough decline in the modeled portfolio cumulative-return series.")
    if task_type == "allocation":
        holdings=context["portfolio"].get("holdings",[]); total=sum(float(row.get("weight") or 0) for row in holdings) or 1
        data=[{"ticker":row["ticker"],"weight":round(float(row.get("weight") or 0)/total,6)} for row in holdings]
        return _task_result(task,data,lineage=deps["portfolio"]["lineage"],as_of=deps["portfolio"]["as_of"],quality=_quality("high",["Saved portfolio weights"]),assumptions=[],warnings=[],how="Normalized saved holding weights to 100%; no LLM calculation was used.")
    if task_type in {"security_comparison","risk_summary","candidate_ranking"}:
        rows=deps["research"]["data"]
        if task_type == "candidate_ranking":
            allowed=[row for row in rows if row["data_quality"] in {"medium","high"} and row["confidence"]>=55]
            theme = str(task.get("query", {}).get("research_query", {}).get("theme") or "").strip().lower()
            if theme:
                theme_terms = {theme, *theme.split()}
                allowed = [row for row in allowed if any(term in " ".join(str(row.get(key, "")) for key in ("ticker","company","sector","industry")).lower() for term in theme_terms)]
            data=sorted(allowed,key=lambda row:(row["final_score"],row["confidence"]),reverse=True)[:12]
            how=f"Filtered the explicit universe by minimum data quality{f' and the {theme} theme' if theme else ''}, then ranked it using the deterministic transparent research composite with confidence as a tie-breaker."
        elif task_type == "security_comparison":
            data=[{key:row.get(key) for key in ("ticker","company","sector","final_score","growth_rating","valuation_score","fundamental_score","technical_score","confidence","data_quality")} for row in rows]
            how="Displayed validated component research scores side-by-side without an LLM ranking."
        else:
            data=[{"ticker":row["ticker"],"risks":row.get("risk_flags",[]),"confidence":row["confidence"],"data_quality":row["data_quality"]} for row in rows]
            how="Collected deterministic research risk flags and evidence-coverage ratings for each requested security."
        return _task_result(task,data,lineage=deps["research"]["lineage"],as_of=deps["research"]["as_of"],quality=deps["research"]["quality"],assumptions=["Research rankings are decision support, not buy instructions."],warnings=[],how=how)
    if task_type == "portfolio_fit":
        candidate_data=deps["candidates"]["data"]; candidate_rows=candidate_data.get("rows",[]) if isinstance(candidate_data,dict) else candidate_data
        sectors={row.get("sector","Unclassified") for row in candidate_rows}; data={"candidate_count":len(candidate_rows),"sectors_represented":sorted(sectors),"note":"Review concentration and scenario exposure before adding any candidate."}
        return _task_result(task,data,lineage=deps["candidates"]["lineage"],as_of=deps["candidates"]["as_of"],quality=deps["candidates"]["quality"],assumptions=["No allocation or trade is proposed."],warnings=[],how="Compared candidate sector representation with the saved portfolio context; it does not optimize or recommend trades.")
    if task_type == "holdings_sensitivity":
        factor = str(task.get("query", {}).get("filters", {}).get("macro_factor") or "inflation")
        definition = MACRO_SENSITIVITY_FACTORS.get(factor, MACRO_SENSITIVITY_FACTORS["inflation"])
        macro_rows = database.macro_point_in_time_history([definition["series"]], limit_per_series=300)
        data = calculate_macro_sensitivity(deps["prices"].get("data", []), macro_rows, factor)
        covered = len(data["rows"])
        price_as_of = deps["prices"].get("as_of")
        macro_as_of = max((row["date"] for row in macro_rows), default=None)
        lineage = [*deps["prices"].get("lineage", []), _lineage("FRED/ALFRED", definition["series"], [], macro_as_of, version="macro-sensitivity-input-v1")]
        warnings = [] if covered else [data.get("reason") or "At least 24 overlapping monthly observations are required for each holding."]
        return _task_result(task, data, lineage=lineage, as_of=min(value for value in (price_as_of, macro_as_of) if value) if price_as_of or macro_as_of else now,
            quality=_quality("high" if covered and all(row["observations"] >= 48 for row in data["rows"]) else "medium" if covered else "low",
                [f"{covered} holdings have quantitative estimates", "Confidence depends on sample size, t-statistic, and sign stability"], model_confidence="medium" if covered else "low"),
            assumptions=["The relationship is descriptive, not causal.", "The macro signal uses the earliest stored real-time vintage for each observation date.", "Monthly adjusted-price returns use current constituents rather than reconstructed historical holdings."],
            warnings=warnings,
            how=f"Aligned monthly adjusted returns with {definition['series']} by calendar month. OLS estimates each holding's return sensitivity to {definition['label']}; confidence reflects observations, coefficient t-statistic, and whether the sign persists in the recent half-sample.")
    if task_type == "macro_risk":
        scenarios=(deps["scenarios"]["data"].get("scenarios",[]) if "scenarios" in deps else []); leading=sorted(scenarios,key=lambda row:row["probability"],reverse=True)[:2]
        holdings=context["portfolio"].get("holdings",[]); data={"leading_scenarios":leading,"holdings":[row["ticker"] for row in holdings],"interpretation":"Sensitivity is qualitative until sufficient security-level macro history is available."}
        lineage=[*deps.get("macro",{}).get("lineage",[]),*deps.get("scenarios",{}).get("lineage",[]),*deps.get("portfolio",{}).get("lineage",[])]
        return _task_result(task,data,lineage=lineage,as_of=now,quality=_quality("medium",["Scenario evidence is current; holding sensitivity is qualitative"],model_confidence="low"),assumptions=["No causal relationship is claimed."],warnings=["Security-level regression sensitivity is not yet available for every holding."],how="Joined the saved holdings with the leading validated macro scenarios; no numeric sensitivity is invented when history is insufficient.")
    if task_type == "historical_regimes":
        rows=database.regime_history(1000); counts={}
        for row in rows: counts[row["dominant_regime"]]=counts.get(row["dominant_regime"],0)+1
        return _task_result(task,{"total_samples":len(rows),"counts":counts},lineage=[_lineage("FRED/ALFRED","point_in_time_regime_labels",[],rows[0]["as_of_date"] if rows else now,version="macro-regime-rules-v1")],as_of=rows[0]["as_of_date"] if rows else now,quality=_quality("high" if len(rows)>=120 else "medium",[f"{len(rows)} monthly labels"]),assumptions=["Labels use only data available at each month end."],warnings=[],how="Counted point-in-time monthly regime labels generated from historical FRED/ALFRED observations.")
    if task_type == "scenario_history":
        history=database.scenario_history(); data=history[-120:]
        return _task_result(task,data,lineage=[_lineage("Supabase","scenario_snapshots",[],data[-1]["fetched_at"] if data else now)],as_of=data[-1]["fetched_at"] if data else now,quality=_quality("medium" if len(data)>1 else "low",[f"{len(data)} stored snapshots"]),assumptions=[],warnings=[] if len(data)>1 else ["More snapshots are needed to show probability changes."],how="Loaded stored, immutable scenario probability snapshots in chronological order.")
    if task_type == "scenario_sensitivity":
        research=deps["research"]["data"]; scenarios=deps["scenarios"]["data"].get("scenarios",[])
        focus=str(task.get("query",{}).get("filters",{}).get("scenario_focus") or "")
        selected=next((row for row in scenarios if row.get("key")==focus),None) or max(scenarios,key=lambda row:row["probability"],default={})
        frame=_price_frame(deps["prices"].get("data",[])).resample("ME").last().pct_change(fill_method=None)
        if not frame.empty: frame.index=frame.index.tz_localize(None).to_period("M")
        labels=database.regime_history(1000); label_map={pd.Period(pd.Timestamp(row["as_of_date"]),freq="M"):row["dominant_regime"] for row in labels}
        months=[month for month in frame.index if label_map.get(month)==selected.get("key")] if not frame.empty else []
        securities=[]; by_ticker={row["ticker"]:row for row in research}
        for ticker in frame.columns if not frame.empty else []:
            sample=frame.loc[months,ticker].dropna(); overall=frame[ticker].dropna()
            if len(sample)<6: continue
            empirical=float(sample.mean()); prior=float(overall.mean()) if len(overall) else 0; shrunk=(len(sample)*empirical+12*prior)/(len(sample)+12)
            row=by_ticker.get(str(ticker),{})
            securities.append({"ticker":str(ticker),"sector":row.get("sector","Unclassified"),"estimated_monthly_return":round(shrunk,6),
                "empirical_monthly_return":round(empirical,6),"downside_frequency":round(float((sample<0).mean()),4),"worst_month":round(float(sample.min()),6),
                "sample_count":int(len(sample)),"shrinkage":round(12/(len(sample)+12),4),"research_confidence":row.get("confidence")})
        securities.sort(key=lambda row:row["estimated_monthly_return"])
        warnings=[] if securities else [f"Fewer than six overlapping historical months were available for {selected.get('label','the selected scenario')}." ]
        data={"selected_scenario":selected,"securities":securities,"ranking":"Most historically exposed first (lowest shrunk monthly return)"}
        return _task_result(task,data,lineage=[*deps["research"]["lineage"],*deps["scenarios"]["lineage"],*deps["prices"]["lineage"],_lineage("FRED/ALFRED","macro_regime_labels",[],labels[0]["as_of_date"] if labels else now,version="macro-regime-rules-v1")],as_of=now,
            quality=_quality("high" if securities and min(row["sample_count"] for row in securities)>=24 else "medium" if securities else "low",[f"{len(months)} historical {selected.get('label','scenario')} months", "Returns are shrunk toward each security's full-sample mean"],scenario_confidence="medium"),
            assumptions=["Historical regime association is not a causal forecast.","A 12-month prior reduces small-regime-sample noise."],warnings=warnings,
            how="Matched monthly adjusted security returns to point-in-time macro regime labels, calculated scenario-month return and downside behavior, then shrank the mean toward each security's full-history average. Lowest shrunk return is displayed as greatest historical exposure.")
    if task_type == "diversification_summary":
        matrix=np.array(deps["correlations"]["data"]["matrix"]); off=matrix[np.triu_indices_from(matrix,1)] if matrix.size else np.array([]); average=float(off.mean()) if len(off) else 0
        data={"average_pairwise_correlation":round(average,4),"effective_holdings_note":"Lower average correlation generally improves diversification, but correlations can rise during stress."}
        return _task_result(task,data,lineage=deps["correlations"]["lineage"],as_of=deps["correlations"]["as_of"],quality=deps["correlations"]["quality"],assumptions=["Pairwise correlation is not a complete risk model."],warnings=[],how="Averaged the off-diagonal entries of the validated daily-return correlation matrix.")
    if task_type == "optimizer_comparison":
        analysis=database.latest_analysis(context["user_id"]); alternatives=(analysis or {}).get("alternatives",[])[:2]
        data={"current":context["portfolio"],"alternatives":alternatives}
        return _task_result(task,data,lineage=[_lineage("EagleEyes","latest_optimizer_run",tickers,(analysis or {}).get("created_at"),version=(analysis or {}).get("model_version"))],as_of=(analysis or {}).get("created_at") or now,quality=_quality("medium" if analysis else "low",["Latest saved optimizer run" if analysis else "No saved optimizer run"]),assumptions=["Only existing Risk-Controlled and Balanced evidence is displayed."],warnings=[] if analysis else ["Run Optimize to populate constrained alternatives."],how="Loaded the existing deterministic optimizer run; the AI workspace does not create or alter allocations.")
    if task_type == "weekly_market_changes":
        frame=_price_frame(deps["prices"].get("data",[])); rows=[]
        if not frame.empty:
            for ticker in frame.columns:
                series=frame[ticker].dropna(); change=float(series.iloc[-1]/series.iloc[-6]-1) if len(series)>=6 else None
                rows.append({"ticker":str(ticker),"five_trading_day_change":change,"observations":min(6,len(series))})
        rows.sort(key=lambda row:abs(row["five_trading_day_change"] or 0),reverse=True)
        return _task_result(task,rows,lineage=deps["prices"].get("lineage",[]),as_of=deps["prices"].get("as_of"),
            quality=_quality("high" if rows and all(row["observations"]>=6 for row in rows) else "low",[f"{len(rows)} covered securities"]),
            assumptions=["A week is represented by the latest five trading-day change."],warnings=[] if rows else ["Weekly adjusted-price changes are unavailable."],
            how="Compared the latest adjusted close with the close five trading sessions earlier for every covered security.")
    if task_type == "next_dollar_research":
        holdings=context["portfolio"].get("holdings",[]); weights={row["ticker"]:float(row.get("weight") or 0) for row in holdings}; total=sum(weights.values()) or 1
        normalized={key:value/total for key,value in weights.items()}; largest=max(normalized,key=normalized.get,default=None)
        profile=database.load_profile(context["user_id"]) or {}; account=str(profile.get("account_type") or "unspecified account")
        data={"account":account,"constraints":["Saved restrictions", "Current concentration", "Contribution-only implementation"],
              "current_largest_position":largest,"current_largest_weight":normalized.get(largest,0) if largest else 0,
              "research_direction":"Direct new contributions away from the largest concentration and toward underweight approved exposures.",
              "alternatives":["Hold cash pending further research","Split the contribution across approved underweights","Make no portfolio change"],
              "missing_information":[item for item,present in (("Employer match",False),("Tax-lot detail",False),("Complete outside-account allocation",bool(profile.get("suitability_profile",{}).get("outside_accounts_value")))) if not present]}
        return _task_result(task,data,lineage=[_lineage("Supabase","portfolio/profile",list(weights),now)],as_of=now,quality=_quality("medium",["Uses saved holdings and profile; no trade is generated"]),
            assumptions=["This is contribution research, not an instruction to purchase a security."],warnings=data["missing_information"],
            how="Normalized current holdings, identified the largest concentration, and applied contribution-only constraints without selling any holding.")
    if task_type == "evidence_audit":
        status=database.provider_data_status(); freshness=status.get("freshness",{}); rows=[]
        for dataset,value in freshness.items():
            age=None
            if value:
                try: age=(datetime.now(timezone.utc)-datetime.fromisoformat(str(value).replace("Z","+00:00"))).days
                except ValueError: age=None
            rows.append({"dataset":dataset,"effective_through":value,"age_days":age,"status":"stale" if age is None or age>7 else "current"})
        warnings=[f"{row['dataset']} is stale or unavailable." for row in rows if row["status"]=="stale"]
        return _task_result(task,rows,lineage=[_lineage("Supabase","provider_freshness",[],now)],as_of=now,
            quality=_quality("high" if rows and not warnings else "medium" if rows else "low",[f"{len(rows)} provider datasets checked"]),assumptions=["Seven days is the general audit threshold; release-specific freshness may differ."],warnings=warnings,
            how="Compared each stored provider effective date with the current UTC date and flagged missing or older-than-seven-day evidence.")
    if task_type == "thesis_invalidation":
        rows=[]
        for item in deps["research"].get("data",[]):
            triggers=list(item.get("risk_flags") or [])
            if item.get("revenue_growth") is not None: triggers.append("Material reversal in the stored revenue-growth trend")
            triggers.extend(["A valuation change that removes the current relative range", "A material deterioration in evidence freshness or coverage"])
            rows.append({"ticker":item.get("ticker"),"current_evidence_quality":item.get("data_quality"),"invalidation_evidence":triggers[:5]})
        return _task_result(task,rows,lineage=deps["research"].get("lineage",[]),as_of=deps["research"].get("as_of"),quality=deps["research"].get("quality",_quality("low",[])),
            assumptions=["These are research-review triggers, not sell instructions."],warnings=[] if rows else ["No security research was available."],
            how="Converted stored risk flags, fundamental trends, valuation evidence, and freshness requirements into deterministic thesis-review triggers.")
    if task_type == "sector_beneficiaries":
        grouped: dict[str,list[dict[str,Any]]]={}
        for item in deps["research"].get("data",[]): grouped.setdefault(str(item.get("sector") or "Unclassified"),[]).append(item)
        rows=[]
        for sector,members in grouped.items():
            eligible=[row for row in members if row.get("data_quality") in {"medium","high"}]
            if eligible: rows.append({"sector":sector,"covered_securities":len(eligible),"supportive_components":round(sum(float(row.get("fundamental_score") or 0) for row in eligible)/len(eligible),1),"examples":[row.get("ticker") for row in eligible[:5]]})
        rows.sort(key=lambda row:row["supportive_components"],reverse=True)
        return _task_result(task,rows,lineage=deps["research"].get("lineage",[]),as_of=deps["research"].get("as_of"),quality=deps["research"].get("quality",_quality("low",[])),
            assumptions=["Beneficiary means relatively supportive stored evidence within the explicit universe, not a forecast or recommendation."],warnings=[] if rows else ["No eligible sector evidence was available."],
            how="Grouped eligible securities by sector and compared their stored fundamental evidence within the disclosed research universe.")
    raise ValueError(f"Unsupported dashboard task type: {task_type}")


def portfolio_performance_widget(portfolio: dict[str, Any], years: int = 1) -> dict[str, Any]:
    """Build the manual terminal's historical portfolio-return widget.

    This deliberately reuses the same deterministic adjusted-price calculation,
    lineage, assumptions, and verification contract as AI-compiled dashboards.
    """
    query = {"tickers": [], "time_range": f"{max(1, min(20, years))}y", "filters": {}}
    context = {"user_id": str(portfolio.get("user_id") or ""), "portfolio": portfolio}
    prices_task = {"id": "prices", "task_type": "price_history", "depends_on": [], "required_for_narrative": False,
                   "query": query, "calculation_version": CALCULATION_VERSION}
    performance_task = {"id": "portfolio-return", "task_type": "portfolio_performance", "depends_on": ["prices"],
                        "required_for_narrative": False, "query": query, "calculation_version": CALCULATION_VERSION}
    prices = execute_task(context, prices_task, {})
    return verify_widget_result(performance_task, execute_task(context, performance_task, {"prices": prices}))


def _cache_key(task: dict[str, Any], context: dict[str, Any], deps: dict[str, Any]) -> str:
    material={"task_type":task["task_type"],"query":task.get("query",{}),"portfolio_snapshot_id":context["portfolio"].get("updated_at") or context["portfolio"].get("id"),"calculation_version":task["calculation_version"],"dependencies":[{"id":key,"as_of":value.get("as_of"),"version":value.get("calculation",{}).get("version")} for key,value in sorted(deps.items())]}
    return hashlib.sha256(json.dumps(material,sort_keys=True,default=str).encode()).hexdigest()


def _run_task(context: dict[str, Any], task: dict[str, Any], deps: dict[str, Any]) -> dict[str, Any]:
    key=_cache_key(task,context,deps); cached=database.dashboard_cache_get(key)
    if cached:
        from .operational_monitoring import record_metric
        record_metric("dashboard.cache_hit", tags={"task_type": task["task_type"], "calculation_version": task.get("calculation_version")})
        result=cached["result"]
        result["lineage"]=[{**line,"cache_status":"hit"} for line in result.get("lineage",[])]
        return verify_widget_result(task, result)
    result=verify_widget_result(task, execute_task(context,task,deps))
    database.dashboard_cache_put(key,task["task_type"],task["calculation_version"],result,result.get("lineage",[]),3600)
    return result


def _template_narrative(prompt: str, results: list[dict[str, Any]]) -> str:
    facts: list[str] = []
    for result in results:
        method = result.get("calculation", {}).get("method"); data = result.get("data")
        if method == "portfolio_performance" and isinstance(data, dict):
            facts.append(f"The modeled portfolio return is {float(data.get('total_return', 0))*100:.1f}% with {float(data.get('annualized_volatility', 0))*100:.1f}% annualized volatility over the displayed period.")
        elif method == "drawdown" and isinstance(data, dict):
            facts.append(f"The largest modeled peak-to-trough drawdown is {float(data.get('max_drawdown', 0))*100:.1f}%.")
        elif method == "allocation" and isinstance(data, list) and data:
            leaders = sorted(data, key=lambda row: row.get("weight", 0), reverse=True)[:3]
            facts.append("The largest saved weights are " + ", ".join(f"{row['ticker']} {float(row['weight'])*100:.1f}%" for row in leaders) + ".")
        elif method == "holdings_sensitivity" and isinstance(data, dict) and data.get("rows"):
            leaders = data["rows"][:4]
            facts.append(f"For {data.get('factor_label', 'the selected macro factor')}, the measured sensitivity ranking is " + ", ".join(f"{row['ticker']} {row['beta']:.2f} ({row['confidence']} confidence, correlation {row['correlation']:.2f})" for row in leaders) + ".")
        elif method == "scenario_probabilities" and isinstance(data, dict):
            scenarios = sorted(data.get("scenarios", []), key=lambda row: row.get("probability", 0), reverse=True)[:3]
            if scenarios: facts.append("The strongest independent condition estimates are " + ", ".join(f"{row['label']} {float(row['probability'])*100:.1f}%" for row in scenarios) + "; overlapping conditions are not forced into one 100% distribution.")
        elif method == "correlation_matrix" and isinstance(data, dict) and len(data.get("tickers", [])) > 1:
            tickers, matrix = data["tickers"], data["matrix"]; pairs=[]
            for i in range(len(tickers)):
                for j in range(i+1,len(tickers)): pairs.append((abs(float(matrix[i][j])),float(matrix[i][j]),tickers[i],tickers[j]))
            if pairs:
                _, value, left, right = max(pairs)
                facts.append(f"The strongest absolute return overlap is {left}–{right}, with correlation {value:.2f} across {data.get('observations', 0)} daily observations.")
        elif method == "diversification_summary" and isinstance(data, dict):
            facts.append(f"Average pairwise correlation is {float(data.get('average_pairwise_correlation', 0)):.2f}; this is a diversification indicator, not a complete risk model.")
        elif method == "security_comparison" and isinstance(data, list) and data:
            leaders = sorted(data, key=lambda row: row.get("final_score", 0), reverse=True)[:5]
            facts.append("The relative comparison order in this disclosed universe is " + ", ".join(
                f"#{index + 1} {row['ticker']} ({str(row.get('data_quality', 'unknown')).lower()} data quality)"
                for index, row in enumerate(leaders)
            ) + "; the underlying component values remain available in Expert evidence.")
        elif method == "candidate_ranking" and isinstance(data, list) and data:
            leaders = sorted(data, key=lambda row: row.get("final_score", 0), reverse=True)[:5]
            facts.append("The leading relative research ranks in the explicitly analyzed universe are " + ", ".join(f"#{index + 1} {row['ticker']}" for index, row in enumerate(leaders)) + "; these ranks are research comparisons, not recommendations.")
        elif method == "research_universe" and isinstance(data, dict):
            facts.append(f"The candidate universe contains {data.get('counts', {}).get('total', 0)} explicitly enumerated securities; it is not a full-market screen.")
        elif method == "scenario_sensitivity" and isinstance(data, dict):
            scenario = data.get("selected_scenario") or {}; securities = data.get("securities") or []
            names = ", ".join(f"{row.get('ticker')} {float(row.get('estimated_monthly_return',0))*100:.1f}% ({row.get('sample_count',0)} months, {float(row.get('downside_frequency',0))*100:.0f}% downside frequency)" for row in securities[:6])
            facts.append(f"For the requested {scenario.get('label', 'scenario')} state ({float(scenario.get('probability', 0))*100:.1f}% current probability), the historical exposure ranking from lowest shrunk monthly return is {names or 'not available'}. This is historical association, not a forecast.")
        elif method == "security_performance" and isinstance(data, dict):
            performances=[]
            for ticker, points in data.get("series",{}).items():
                if points: performances.append(f"{ticker} {float(points[-1].get('value',0))*100:.1f}%")
            if performances: facts.append("Cumulative adjusted-price performance is " + ", ".join(performances) + ".")
        elif method == "security_drawdown" and isinstance(data, list):
            facts.append("Maximum drawdowns are " + ", ".join(f"{row['ticker']} {float(row.get('max_drawdown',0))*100:.1f}%" for row in data) + ".")
        elif method == "correlation_stability" and isinstance(data, dict):
            facts.append(f"The mean absolute correlation change between the first and second sample halves is {float(data.get('mean_absolute_correlation_change',0)):.2f}; the deterministic stability flag is {'stable' if data.get('stable') else 'unstable'}.")
        elif method == "factor_correlation_candidates" and isinstance(data, dict):
            rows = data.get("rows") or []
            if rows:
                facts.append(f"Among {data.get('universe_count',0)} explicitly enumerated securities, the strongest measured correlations with {data.get('factor_label','the selected macro factor')} are " + ", ".join(
                    f"{row['ticker']} {float(row.get('correlation',0)):+.2f} ({row.get('observations',0)} months, {row.get('confidence','low')} confidence)" for row in rows[:6]
                ) + ". Positive and negative correlations are ranked by absolute strength.")
            else:
                facts.append(f"No candidate correlation ranking is available for {data.get('factor_label','the selected macro factor')} because the minimum overlapping-history requirement was not met.")
        elif method == "holdings_sensitivity" and isinstance(data, dict) and not data.get("rows"):
            facts.append(f"No quantitative {data.get('factor_label','macro')} sensitivity ranking is available: {data.get('reason') or 'the overlapping history is insufficient for the minimum sample requirement'}. Confidence is therefore low rather than inferred by the language model.")
    if not facts:
        facts.append(f"{len(results)} evidence widgets completed, but none exposed a supported headline statistic for a template summary.")
    warning_messages = [warning for result in results for warning in result.get("warnings", [])]
    warning_count = len(warning_messages)
    warning_detail = " ".join(dict.fromkeys(str(warning) for warning in warning_messages))
    return "\n".join([
        "### Summary", f"The dashboard assembled evidence for: {prompt} The quantitative results below come from deterministic calculations rather than the language model.",
        "### Key observations", *[f"- {fact}" for fact in facts[:6]],
        "### Portfolio implications", "Use the measured rankings, overlap, and diversification relationships to identify what deserves closer review. They describe historical association and current stored evidence; they do not establish causation or prescribe a trade.",
        "### Risks and limitations", f"The results contain {warning_count} recorded widget warnings.{f' {warning_detail}' if warning_detail else ''} Current holdings are used for historical portfolio calculations, relationships can change across regimes, and weak confidence should not be treated as a strong signal.",
        "### What to verify", "Check the displayed time period, units, sample count, data freshness, confidence reasons, and the expanded How this was calculated section before acting on any conclusion.",
    ])


def _narrate(prompt: str, results: list[dict[str, Any]]) -> str:
    useful=[{"widget_id":row["widget_id"],"data":row["data"],"quality":row["quality"],"warnings":row["warnings"],"as_of":row["as_of"],"calculation":row.get("calculation",{}),"presentation":row.get("presentation",{})} for row in results if row["status"] in {"READY","STALE"}]
    if not useful: return "No validated widget evidence was available, so no interpretation was generated."
    api_key=os.getenv("GEMINI_API_KEY","").strip(); model=os.getenv("GEMINI_MODEL","gemini-3.5-flash").strip()
    if not api_key:
        return _template_narrative(prompt, useful)
    narrator=f"""You are the narrator for an investment research dashboard. You cannot calculate, rank, or change results.
Use only the validated widget evidence below. Do not give buy/sell instructions.
Return four concise sections: Summary, Key observations, Portfolio implications, Risks and limitations. End with What to verify.
Original question: {prompt}
Validated widgets: {json.dumps(useful,default=str)[:60000]}"""
    try:
        payload=_gemini_request(api_key,model,[{"role":"user","parts":[{"text":narrator}]}],3000)
        text,_=_candidate(payload)
        return text.strip() or _template_narrative(prompt, useful)
    except Exception:
        return _template_narrative(prompt, useful)


def review_dashboard_answer(prompt: str, narrative: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministically check evidence coverage and whether the prose addresses the request."""
    lower = prompt.lower(); available = {row.get("calculation", {}).get("method") for row in results if row.get("status") in {"READY", "STALE"}}
    issues, checks = [], []
    expectations = {
        "return": {"portfolio_performance", "security_performance"}, "drawdown": {"drawdown", "security_drawdown"},
        "correlat": {"correlation_matrix", "factor_correlation_candidates"}, "inflation": {"holdings_sensitivity", "macro_trends"},
        "scenario": {"scenario_probabilities"}, "valuation": {"security_comparison", "candidate_ranking"},
    }
    for keyword, methods in expectations.items():
        if keyword in lower:
            if available.intersection(methods): checks.append(f"Evidence for {keyword} is present")
            else: issues.append(f"The requested {keyword} evidence is missing")
    if "oil" in lower and "correlat" in lower:
        if "factor_correlation_candidates" in available: checks.append("Oil correlation uses the named macro factor")
        else: issues.append("Oil correlation was not calculated against oil returns")
    benchmark_match=re.search(r"benchmark(?:ed|ing)?(?: against| to| versus| vs)?\s+([A-Z]{1,10})",prompt)
    if benchmark_match:
        benchmark=benchmark_match.group(1).upper(); covered=False
        for result in results:
            data=result.get("data")
            if isinstance(data,dict) and benchmark in (data.get("series") or {}): covered=True
        if covered: checks.append(f"Requested benchmark {benchmark} appears in the evidence")
        else: issues.append(f"Requested benchmark {benchmark} is absent")
    if len(narrative.split()) >= 40: checks.append("Interpretation has sufficient explanatory detail")
    else: issues.append("Interpretation is too short to explain the evidence")
    tickers = sorted({
        str(item.get("ticker")) for result in results
        for item in ((result.get("data") or {}).get("rows", []) if isinstance(result.get("data"), dict) else result.get("data", []) if isinstance(result.get("data"), list) else [])
        if isinstance(item, dict) and item.get("ticker")
    })
    if "which" in lower and tickers:
        if any(ticker in narrative.upper() for ticker in tickers): checks.append("Interpretation names evidence-backed securities")
        else: issues.append("Interpretation does not identify the securities shown by the evidence")
    return {"agent": "answer_reviewer", "status": "passed" if not issues else "needs_attention",
            "checks": checks, "issues": issues, "evidence_widgets": len(available)}


def verify_required_evidence(prompt: str, plan: DashboardPlan, tasks: dict[str,dict[str,Any]],
                             results: dict[str,dict[str,Any]]) -> dict[str,Any]:
    ready={task_id:result for task_id,result in results.items() if result.get("status") in {"READY","STALE"}}
    issues=[];checks=[]
    for task_id,task in tasks.items():
        if not task.get("required_for_narrative"): continue
        result=ready.get(task_id)
        if result and result.get("data") not in ({},[],None):
            checks.append(f"Required evidence {task_id} is ready")
            verification=result.get("verification") or {}
            if verification.get("issues"):
                issues.extend(f"{task_id}: {issue}" for issue in verification["issues"])
            presentation=result.get("presentation") or {}
            for field in ("unit","timeframe"):
                if presentation.get(field): checks.append(f"{task_id} declares {field}")
                else: issues.append(f"{task_id} does not declare {field}")
            if result.get("status") == "STALE": checks.append(f"{task_id} is explicitly labeled stale")
            elif result.get("as_of"): checks.append(f"{task_id} freshness timestamp is present")
        else: issues.append(f"Required evidence {task_id} is unavailable")
    lower=prompt.lower(); methods={row.get("calculation",{}).get("method") for row in ready.values()}
    if "oil" in lower and any(term in lower for term in ("correlat","candidate","which stocks","what stocks")):
        if "factor_correlation_candidates" in methods: checks.append("Oil request uses oil-return correlation evidence")
        else: issues.append("Oil request lacks stock-to-oil correlation evidence; stock-to-stock correlation cannot substitute")
    benchmark=plan.filters.get("requested_benchmark")
    if benchmark:
        covered=False
        for row in ready.values():
            data=row.get("data")
            if isinstance(data,dict) and benchmark in (data.get("series") or {}): covered=True
        if covered: checks.append(f"Requested benchmark {benchmark} is present")
        else: issues.append(f"Requested benchmark {benchmark} is missing from calculated evidence")
    requested=set(plan.entities.tickers)
    if requested:
        evidenced=set()
        for row in ready.values():
            for line in row.get("lineage") or []: evidenced.update(line.get("symbols") or [])
            data=row.get("data")
            if isinstance(data,list): evidenced.update(str(item.get("ticker")) for item in data if isinstance(item,dict) and item.get("ticker"))
            elif isinstance(data,dict):
                evidenced.update((data.get("series") or {}).keys() if isinstance(data.get("series"),dict) else [])
                evidenced.update(str(item.get("ticker")) for item in data.get("rows",[]) if isinstance(item,dict) and item.get("ticker"))
        absent=sorted(requested-evidenced)
        if absent: issues.append(f"Requested entities are missing from evidence: {', '.join(absent)}")
        else: checks.append("All requested entities appear in lineage or results")
    factor=plan.filters.get("macro_factor")
    if factor:
        factor_methods={"holdings_sensitivity","factor_correlation_candidates","macro_trends"}
        factor_rows=[row for row in ready.values() if row.get("calculation",{}).get("method") in factor_methods]
        matched=any(
            factor in str((row.get("data") or {}).get("factor") or (row.get("data") or {}).get("factor_key") or (row.get("data") or {}).get("factor_label") or "").lower()
            or factor in str(row.get("calculation",{}).get("parameters",{}).get("macro_factor") or "").lower()
            for row in factor_rows if isinstance(row.get("data"),dict)
        )
        if matched: checks.append(f"Requested factor {factor} is explicit in calculated evidence")
        else: issues.append(f"Requested factor {factor} is not explicit in calculated evidence")
    return {"status":"passed" if not issues else "blocked","checks":checks,"issues":issues}


def unsupported_evidence_feedback(prompt: str, issues: list[str]) -> str:
    return "\n".join([
        "### Evidence requirement not met",
        f"EagleEyes did not narrate the request yet: {prompt}",
        *[f"- {issue}" for issue in issues],
        "### What to do next",
        "Add or refresh the named evidence, narrow the requested universe, or choose a supported factor and benchmark. Completed widgets remain available below.",
    ])


JOB_EXECUTOR=ThreadPoolExecutor(max_workers=4,thread_name_prefix="dashboard-job")
TASK_EXECUTOR=ThreadPoolExecutor(max_workers=8,thread_name_prefix="dashboard-task")
ACTIVE_JOBS: dict[str,Future[Any]]={}
ACTIVE_LOCK=threading.Lock()
TASK_RETRY_POLICY=RetryPolicy(attempts=max(1,min(3,int(os.getenv("DASHBOARD_TASK_MAX_ATTEMPTS","2")))))


def _run_task_bounded(context: dict[str, Any], task: dict[str, Any], deps: dict[str, Any]) -> dict[str, Any]:
    return retry_call(
        lambda: _run_task(context, task, deps),
        policy=TASK_RETRY_POLICY,
        retryable=lambda exc: any(token in type(exc).__name__.lower() for token in ("timeout", "connection", "operational")),
        metric="dashboard.task",
    )


def submit_dashboard_job(job: dict[str, Any], user_id: str) -> None:
    with ACTIVE_LOCK:
        existing=ACTIVE_JOBS.get(job["id"])
        if existing and not existing.done(): return
        ACTIVE_JOBS[job["id"]]=JOB_EXECUTOR.submit(run_dashboard_job,job["id"],user_id)


def run_dashboard_job(job_id: str, user_id: str) -> None:
    try:
        job=database.get_dashboard_job(job_id,user_id)
        if job["state"] == "CANCELLED":
            return
        portfolio=_portfolio(user_id,job.get("portfolio_id"))
        profile=database.load_profile(user_id) or {}
        policy=database.load_investment_policy(user_id)
        goals=database.list_goals(user_id)
        guidance=guidance_disclosure(portfolio=portfolio,profile=profile,policy=policy,goals=goals)
        context={"user_id":user_id,"portfolio":portfolio,"profile":profile,"policy":policy,"goals":goals,"guidance":guidance}
        plan=DashboardPlan.model_validate(job["plan"]) if job.get("plan") else plan_dashboard(job["prompt"],portfolio)
        database.update_dashboard_job(job_id,user_id,state="PLAN_VALIDATED",progress=12,plan=plan.model_dump(mode="json"))
        spec=compile_spec(plan)
        spec["guidance_decision"]={
            **guidance,
            "inputs_used": {
                "portfolio_id": (portfolio or {}).get("id"), "profile_present": bool(profile),
                "policy_status": (policy or {}).get("status"), "goal_count": len(goals),
            },
            "calculation_version": "guidance-completeness-v2",
        }
        database.update_dashboard_job(job_id,user_id,state="SPEC_COMPILED",progress=20,specification=spec)
        for task in spec["tasks"]: database.save_dashboard_task(job_id,task)
        database.update_dashboard_job(job_id,user_id,state="FETCHING",progress=25)
        tasks={task["id"]:task for task in spec["tasks"]}; pending=set(tasks); running:dict[Future[Any],str]={}; results:dict[str,dict[str,Any]]={}; failures=[]; narrative_future:Future[str]|None=None; evidence_gate:dict[str,Any]|None=None
        while pending or running:
            current=database.get_dashboard_job(job_id,user_id)
            if current["state"]=="CANCELLED":
                for task_id in pending: database.save_dashboard_task(job_id,tasks[task_id],state="CANCELLED")
                return
            for task_id in list(pending):
                task=tasks[task_id]
                if all(dep in results for dep in task["depends_on"]):
                    dep_values={dep:results[dep] for dep in task["depends_on"]}; database.save_dashboard_task(job_id,task,state="RUNNING")
                    running[TASK_EXECUTOR.submit(_run_task_bounded,context,task,dep_values)]=task_id; pending.remove(task_id)
            if not running and pending:
                raise RuntimeError("No runnable tasks remain in the dashboard graph")
            if running:
                future=next(as_completed(list(running),timeout=DASHBOARD_TASK_WAIT_SECONDS)); task_id=running.pop(future); task=tasks[task_id]
                try:
                    result=future.result(); results[task_id]=result; database.save_dashboard_task(job_id,task,state="READY",result=result)
                except Exception as exc:
                    failures.append(f"{task_id}: {exc}"); failed=_task_result(task,{},lineage=[],as_of=None,quality=_quality("low",["Task failed"]),assumptions=[],warnings=[str(exc)],how="The calculation did not complete.",status="FAILED")
                    results[task_id]=failed; database.save_dashboard_task(job_id,task,state="FAILED",result=failed,error=str(exc))
                visible=[results[w["task_id"]] for w in spec["widgets"] if w["task_id"] in results]
                progress=min(78,25+int(53*len(results)/max(1,len(tasks)))); database.update_dashboard_job(job_id,user_id,state="CALCULATING",progress=progress,widget_results=visible,warnings=failures)
                required=[task["id"] for task in tasks.values() if task["required_for_narrative"]]
                if narrative_future is None and all(task_id in results for task_id in required):
                    evidence_gate=verify_required_evidence(job["prompt"],plan,tasks,results)
                    if evidence_gate["status"]=="passed":
                        narrative_future=TASK_EXECUTOR.submit(_narrate,job["prompt"],[results[key] for key in required if results[key]["status"]!="FAILED"])
        visible=[results[w["task_id"]] for w in spec["widgets"] if w["task_id"] in results]
        database.update_dashboard_job(job_id,user_id,state="WIDGETS_READY",progress=82,widget_results=visible,warnings=failures)
        narrative=""; narrative_error=None
        if narrative_future:
            database.update_dashboard_job(job_id,user_id,state="NARRATING",progress=90)
            try: narrative=narrative_future.result(timeout=DASHBOARD_NARRATIVE_WAIT_SECONDS)
            except Exception as exc: narrative_error=str(exc); failures.append(f"Narrative: {exc}")
        elif evidence_gate and evidence_gate["issues"]:
            narrative=unsupported_evidence_feedback(job["prompt"],evidence_gate["issues"])
            failures.extend(f"Evidence gate: {issue}" for issue in evidence_gate["issues"])
        answer_review=review_dashboard_answer(job["prompt"],narrative,visible)
        spec["required_evidence_review"]=evidence_gate or {"status":"not_required","checks":[],"issues":[]}
        spec["answer_review"]=answer_review
        if answer_review["issues"]:
            failures.extend(f"Answer review: {issue}" for issue in answer_review["issues"])
        final_state="PARTIAL_SUCCESS" if failures or narrative_error else "COMPLETE"
        from .operational_monitoring import record_metric
        record_metric("dashboard.partial_success" if final_state == "PARTIAL_SUCCESS" else "dashboard.complete", tags={"intent": plan.intent, "compiler_version": spec.get("compiler_version")}, persist=True)
        database.update_dashboard_job(job_id,user_id,state=final_state,progress=100,specification=spec,widget_results=visible,narrative=narrative,warnings=failures,error=narrative_error)
    except Exception as exc:
        from .operational_monitoring import record_metric
        record_metric("dashboard.failed", tags={"error_type": type(exc).__name__}, persist=True)
        try: database.update_dashboard_job(job_id,user_id,state="FAILED",progress=100,error=str(exc),warnings=[str(exc)])
        except Exception: pass


def create_draft(user_id: str, request: DraftRequest, source_view_id: str | None = None) -> dict[str, Any]:
    # Validate prompt synchronously so adversarial actions fail before a worker is scheduled.
    deterministic_plan(request.prompt,request.portfolio_id)
    if request.conversation_id:
        database.get_conversation(user_id, request.conversation_id)
    job=database.create_dashboard_job(user_id,request.prompt,request.portfolio_id,source_view_id,request.conversation_id)
    submit_dashboard_job(job,user_id)
    return job


def dashboard_data_catalog() -> list[dict[str, Any]]:
    status = database.provider_data_status(); counts = status.get("counts", {})
    return [
        {"widget_type": key, **item, "available": any(int(counts.get(dataset, 0) or 0) > 0 for dataset in item["datasets"]),
         "record_count": sum(int(counts.get(dataset, 0) or 0) for dataset in item["datasets"])}
        for key, item in DATA_WIDGET_CATALOG.items()
    ]


def _create_augmented_draft(user_id: str, prompt: str, plan_data: dict[str, Any], widget_type: str,
                            source_view_id: str | None = None) -> dict[str, Any]:
    if widget_type not in DATA_WIDGET_CATALOG:
        raise ValueError("Unsupported dashboard data widget")
    plan = DashboardPlan.model_validate(plan_data)
    additional = list(plan.filters.get("additional_widgets", []))
    current_types = {item[1] for item in TASK_TEMPLATES[plan.intent]["tasks"]}
    if widget_type in additional or widget_type in current_types:
        raise ValueError("That data widget is already included in this dashboard")
    plan.filters = {**plan.filters, "additional_widgets": [*additional, widget_type]}
    job = database.create_dashboard_job(user_id, prompt, plan.entities.portfolio_id, source_view_id)
    job = database.update_dashboard_job(job["id"], user_id, plan=plan.model_dump(mode="json"))
    submit_dashboard_job(job, user_id)
    return job


def add_widget_to_draft(user_id: str, job_id: str, widget_type: str) -> dict[str, Any]:
    job = database.get_dashboard_job(job_id, user_id)
    if not job.get("plan"):
        raise ValueError("Dashboard planning must finish before data can be added")
    return _create_augmented_draft(user_id, job["prompt"], job["plan"], widget_type, job.get("source_view_id"))


def add_widget_to_view(user_id: str, view_id: str, widget_type: str) -> dict[str, Any]:
    view = database.get_dashboard_view(view_id, user_id)
    return _create_augmented_draft(user_id, view["original_prompt"], view["plan"], widget_type, view_id)


def revise_draft(user_id: str, job_id: str, request: RevisionRequest) -> dict[str, Any]:
    prior=database.get_dashboard_job(job_id,user_id)
    combined=f"Original request: {prior['prompt']}\nRevision: {request.prompt}"
    return create_draft(user_id,DraftRequest(prompt=combined,portfolio_id=prior.get("portfolio_id")),prior.get("source_view_id"))


def mutate_draft_layout(user_id: str, job_id: str, widget_id: str,
                        request: LayoutMutationRequest) -> dict[str, Any]:
    job=database.get_dashboard_job(job_id,user_id)
    if job["state"] not in TERMINAL_STATES or not job.get("specification"):
        raise ValueError("Dashboard layout can be edited after widget calculation finishes")
    spec=dict(job["specification"]); widgets=[dict(item) for item in spec.get("widgets",[])]
    index=next((position for position,item in enumerate(widgets) if str(item.get("id"))==widget_id),-1)
    if index<0: raise KeyError(widget_id)
    if request.operation=="remove":
        widgets.pop(index)
    elif request.operation=="resize":
        if request.width not in {4,6,8,12} or request.height is None or not 2<=request.height<=6:
            raise ValueError("Widget size must use width 4, 6, 8, or 12 and height 2 through 6")
        widgets[index]={**widgets[index],"grid":{**(widgets[index].get("grid") or {}),"w":request.width,"h":request.height}}
    else:
        step=-1 if (request.direction or 0)<0 else 1; target=index+step
        if target<0 or target>=len(widgets): raise ValueError("Widget cannot move farther in that direction")
        widgets[index],widgets[target]=widgets[target],widgets[index]
    spec={**spec,"widgets":widgets,"layout_version":"dashboard-layout-v2"}
    visible_ids={item.get("task_id") for item in widgets}
    results=[item for item in job.get("widget_results",[]) if item.get("widget_id") in visible_ids]
    return database.update_dashboard_job(job_id,user_id,specification=spec,widget_results=results)
