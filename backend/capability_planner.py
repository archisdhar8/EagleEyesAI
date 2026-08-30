from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .analytical_contract import (
    AnalysisResult, AnalysisStatus, Coverage, DependencyResult, Freshness,
    JobReference, VerificationCheck, VerificationResult, VerificationSeverity,
    stable_fingerprint,
)


CAPABILITY_REGISTRY_VERSION = "capability-registry-v1"
PLANNER_PROMPT_VERSION = "capability-planner-v1"
COMPOSER_VERSION = "composed-analysis-v1"
MAX_SYNCHRONOUS_CAPABILITIES = 4
MAX_HEAVY_JOBS = 1
MAX_ENTITIES = 8
MAX_COMPARISON_ENTITIES = 5
MAX_PLAN_DEPTH = 3
MAX_DEPENDENCIES_PER_STEP = 3
MAX_PLANNER_REPAIRS = 1


class LatencyClass(StrEnum):
    MEMORY = "MEMORY"
    DATABASE = "DATABASE"
    LIGHT_IO = "LIGHT_IO"
    DURABLE_JOB = "DURABLE_JOB"


class EntityKind(StrEnum):
    SECURITY = "SECURITY"
    PORTFOLIO = "PORTFOLIO"
    WATCHLIST = "WATCHLIST"
    BENCHMARK = "BENCHMARK"
    MACRO_FACTOR = "MACRO_FACTOR"
    PREDICTION_EVENT = "PREDICTION_EVENT"
    SCENARIO_FACTOR = "SCENARIO_FACTOR"


class ReasonCode(StrEnum):
    PRIMARY_QUESTION = "PRIMARY_QUESTION"
    SUPPORTING_CONTEXT = "SUPPORTING_CONTEXT"
    PORTFOLIO_FIT = "PORTFOLIO_FIT"
    CHANGE_CONTEXT = "CHANGE_CONTEXT"
    SCENARIO_INPUT = "SCENARIO_INPUT"
    COMPARISON_CONTEXT = "COMPARISON_CONTEXT"


class ResponseMode(StrEnum):
    DIRECT = "DIRECT"
    COMPOSED = "COMPOSED"
    CLARIFICATION = "CLARIFICATION"


class SourceCategory(StrEnum):
    VERIFIED_FACT = "VERIFIED_FACT"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    MARKET_IMPLIED_EVIDENCE = "MARKET_IMPLIED_EVIDENCE"
    USER_BELIEF = "USER_BELIEF"
    AI_INTERPRETATION = "AI_INTERPRETATION"


class ResolvedEntity(BaseModel):
    kind: EntityKind
    canonical_id: str
    display_name: str | None = None
    source_text: str | None = None
    resolution: str = "DETERMINISTIC"


class TimeContext(BaseModel):
    selection: str
    start: date | None = None
    end: date | None = None
    baseline: str | None = None


class ConversationAnalyticalContext(BaseModel):
    active_entities: list[ResolvedEntity] = Field(default_factory=list)
    active_portfolio: str | None = None
    active_comparison: list[str] = Field(default_factory=list)
    active_capabilities: list[str] = Field(default_factory=list)
    recent_result_ids: list[str] = Field(default_factory=list)
    active_scenario: list[str] = Field(default_factory=list)


class CapabilityDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    supported_intents: tuple[str, ...]
    supported_entities: tuple[EntityKind, ...]
    input_schema: dict[str, Any]
    output_schema: str
    synchronous: bool
    heavy_job: bool
    expected_latency_class: LatencyClass
    required_context: tuple[str, ...] = ()
    optional_context: tuple[str, ...] = ()
    internal_dependencies: tuple[str, ...] = ()
    can_compose_with: tuple[str, ...] = ()
    safety_constraints: tuple[str, ...] = ()
    min_entities: int = 0
    max_entities: int = MAX_ENTITIES
    source_category: SourceCategory = SourceCategory.MODEL_OUTPUT


def _descriptor(name: str, description: str, intents: tuple[str, ...], entities: tuple[EntityKind, ...],
                output: str, *, portfolio: bool = False, heavy: bool = False,
                min_entities: int = 0, max_entities: int = MAX_ENTITIES,
                source: SourceCategory = SourceCategory.MODEL_OUTPUT,
                optional: tuple[str, ...] = ()) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name, description=description, supported_intents=intents, supported_entities=entities,
        input_schema={"entities": "ResolvedEntity[]", "time_context": "TimeContext?"}, output_schema=output,
        synchronous=not heavy, heavy_job=heavy,
        expected_latency_class=LatencyClass.DURABLE_JOB if heavy else LatencyClass.DATABASE,
        required_context=("portfolio",) if portfolio else (), optional_context=optional,
        can_compose_with=(), min_entities=min_entities, max_entities=max_entities,
        source_category=source,
        safety_constraints=(
            "read_only", "registered_execution_only", "no_trade_execution",
            "no_unverified_calculation", "preserve_analysis_status",
        ),
    )


# Names are the existing Ask/read-model/job capability names. Descriptors do not
# create planner-only aliases and never expose a Python callable.
CAPABILITY_REGISTRY: dict[str, CapabilityDescriptor] = {
    "company_analysis": _descriptor("company_analysis", "Bounded shared research intelligence for company overview, financial health, valuation, earnings, catalysts, risks, technicals, ownership/sentiment, and decision evidence.", ("company", "earnings", "research_intelligence"), (EntityKind.SECURITY,), "CompanyAnalysisResult", min_entities=1, max_entities=1, source=SourceCategory.VERIFIED_FACT),
    "company_comparison": _descriptor("company_comparison", "Compare supported companies and optionally enrich portfolio fit.", ("comparison",), (EntityKind.SECURITY,), "CompanyComparisonResult", min_entities=2, max_entities=MAX_COMPARISON_ENTITIES, optional=("portfolio",)),
    "valuation_ranking": _descriptor("valuation_ranking", "Compare valuation relative to supported growth evidence.", ("valuation",), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", portfolio=True),
    "multifactor_screen": _descriptor("multifactor_screen", "Screen valuation, fundamentals, and momentum together.", ("fundamental_trend", "screen"), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", portfolio=True),
    "score_attribution": _descriptor("score_attribution", "Explain supported score inputs and changes.", ("score", "attribution"), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", portfolio=True),
    "historical_change": _descriptor("historical_change", "Compare a company or macro state with a genuine compatible baseline.", ("change", "history"), (EntityKind.SECURITY, EntityKind.MACRO_FACTOR), "HistoricalComparison", min_entities=0, max_entities=1),
    "portfolio_overview": _descriptor("portfolio_overview", "Rank current portfolio opportunities.", ("opportunity",), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "portfolio_risk": _descriptor("portfolio_risk", "Measure saved portfolio position-size risk and concentration.", ("risk", "concentration"), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "portfolio_intelligence": _descriptor("portfolio_intelligence", "Analyze portfolio dependencies, themes, and hidden exposures.", ("risk", "concentration", "macro_exposure"), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "watchlist_comparison": _descriptor("watchlist_comparison", "Compare supported watchlist candidates with holdings.", ("watchlist",), (EntityKind.PORTFOLIO, EntityKind.WATCHLIST), "AnalysisResult", portfolio=True),
    "thesis_replacement": _descriptor("thesis_replacement", "Evaluate a supported thesis replacement candidate.", ("replacement",), (EntityKind.PORTFOLIO, EntityKind.SECURITY), "AnalysisResult", portfolio=True),
    "portfolio_change": _descriptor("portfolio_change", "Compare portfolio state with a compatible baseline.", ("change", "history"), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "data_quality": _descriptor("data_quality", "Report analytical coverage and missing portfolio data.", ("data_quality",), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "portfolio_events": _descriptor("portfolio_events", "Report supported portfolio events and catalysts.", ("events",), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True, source=SourceCategory.VERIFIED_FACT),
    "thesis_monitor": _descriptor("thesis_monitor", "Evaluate saved thesis status or qualitative monitoring.", ("thesis", "countercase"), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", heavy=True, min_entities=0),
    "thesis_invalidation": _descriptor("thesis_invalidation", "Evaluate supported thesis invalidation conditions.", ("thesis", "invalidation"), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", portfolio=True),
    "recommendation_countercase": _descriptor("recommendation_countercase", "Return the strongest supported countercase to an opportunity.", ("countercase",), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", portfolio=True),
    "cash_allocation": _descriptor("cash_allocation", "Evaluate supported new-cash allocation alternatives.", ("cash",), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "portfolio_analysis": _descriptor("portfolio_analysis", "Produce or queue constrained portfolio optimization/rebalance analysis.", ("rebalance", "optimization"), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True, heavy=True),
    "macro_state": _descriptor("macro_state", "Return the canonical macro state and supported portfolio exposures.", ("macro",), (EntityKind.MACRO_FACTOR, EntityKind.PORTFOLIO), "MacroStateResult", optional=("portfolio",), source=SourceCategory.VERIFIED_FACT),
    "market_state": _descriptor("market_state", "Return the canonical market regime and portfolio fit.", ("market",), (EntityKind.PORTFOLIO,), "MarketStateResult", optional=("portfolio",), source=SourceCategory.VERIFIED_FACT),
    "prediction_markets": _descriptor("prediction_markets", "Return market-implied probabilities, changes, and mapped relevance.", ("prediction",), (EntityKind.PREDICTION_EVENT, EntityKind.PORTFOLIO), "PredictionMarketResult", optional=("portfolio",), source=SourceCategory.MARKET_IMPLIED_EVIDENCE),
    "portfolio_scenario": _descriptor("portfolio_scenario", "Compose supported portfolio scenario factors or queue simulation.", ("scenario",), (EntityKind.PORTFOLIO, EntityKind.SCENARIO_FACTOR), "AnalysisResult", portfolio=True, heavy=True),
    "portfolio_backtest": _descriptor("portfolio_backtest", "Queue or reuse a durable portfolio benchmark backtest.", ("backtest",), (EntityKind.PORTFOLIO, EntityKind.BENCHMARK), "BacktestResult", portfolio=True, heavy=True),
    "company_research": _descriptor("company_research", "Queue or reuse durable deep company research.", ("deep_research",), (EntityKind.SECURITY,), "AnalysisResult", heavy=True, min_entities=1, max_entities=3),
    "security_ranking": _descriptor("security_ranking", "Rank supported holdings using stored opportunity evidence.", ("ranking",), (EntityKind.PORTFOLIO,), "AnalysisResult", portfolio=True),
    "benchmark_outlook": _descriptor("benchmark_outlook", "Return supported benchmark-relative evidence without inventing forecasts.", ("benchmark",), (EntityKind.PORTFOLIO, EntityKind.BENCHMARK), "AnalysisResult", portfolio=True),
    "today_attention": _descriptor("today_attention", "Return the stored deterministic Today attention composition.", ("today",), (EntityKind.PORTFOLIO,), "AnalysisResult", optional=("portfolio",)),
    "decision_journal": _descriptor("decision_journal", "Return saved decision and retrospective evidence.", ("retrospective", "history"), (EntityKind.SECURITY, EntityKind.PORTFOLIO), "AnalysisResult", optional=("portfolio",), source=SourceCategory.USER_BELIEF),
}

_DESCRIPTOR_RELATIONSHIPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "company_analysis": (("company_analysis read model",), ("historical_change", "company_comparison", "portfolio_risk")),
    "company_comparison": (("company_analysis",), ("portfolio_risk", "portfolio_intelligence")),
    "valuation_ranking": (("portfolio_factor_state read model",), ("multifactor_screen", "portfolio_risk")),
    "multifactor_screen": (("portfolio_factor_state read model",), ("valuation_ranking", "portfolio_risk")),
    "score_attribution": (("score_attribution read model",), ("historical_change", "thesis_monitor")),
    "historical_change": (("compatible append-only read-model baseline",), ("company_analysis", "macro_state", "portfolio_change")),
    "portfolio_overview": (("portfolio_opportunity read model",), ("recommendation_countercase", "portfolio_risk")),
    "portfolio_risk": (("portfolio_risk read model",), ("company_comparison", "macro_state", "market_state", "prediction_markets")),
    "portfolio_intelligence": (("portfolio_risk read model",), ("macro_state", "market_state", "prediction_markets", "watchlist_comparison")),
    "watchlist_comparison": (("watchlist_comparison read model",), ("portfolio_risk", "cash_allocation")),
    "thesis_replacement": (("watchlist_comparison read model", "thesis_status read model"), ("portfolio_risk", "recommendation_countercase")),
    "portfolio_change": (("portfolio_change read model",), ("historical_change", "macro_state")),
    "data_quality": (("portfolio_data_quality read model",), ("portfolio_overview", "valuation_ranking", "multifactor_screen")),
    "portfolio_events": (("portfolio_events read model",), ("thesis_monitor", "portfolio_risk")),
    "thesis_monitor": (("durable THESIS_MONITOR job",), ("company_analysis", "portfolio_events", "recommendation_countercase")),
    "thesis_invalidation": (("thesis_status read model",), ("portfolio_risk", "company_analysis")),
    "recommendation_countercase": (("portfolio_opportunity read model", "portfolio_risk read model"), ("portfolio_overview", "thesis_monitor")),
    "cash_allocation": (("watchlist_comparison read model",), ("portfolio_risk", "data_quality")),
    "portfolio_analysis": (("durable OPTIMIZATION job", "optimizer_compatibility read model"), ("portfolio_risk", "data_quality")),
    "macro_state": (("macro_state read model",), ("portfolio_intelligence", "prediction_markets", "historical_change")),
    "market_state": (("market_state read model",), ("portfolio_risk", "prediction_markets", "historical_change")),
    "prediction_markets": (("prediction_market_state read model",), ("macro_state", "market_state", "portfolio_risk")),
    "portfolio_scenario": (("portfolio_scenario read model or durable SIMULATION job",), ("portfolio_risk",)),
    "portfolio_backtest": (("durable BACKTEST job",), ("portfolio_risk", "benchmark_outlook")),
    "company_research": (("durable COMPANY_RESEARCH_BUILD job",), ("company_analysis", "thesis_monitor")),
    "security_ranking": (("portfolio_opportunity read model",), ("portfolio_risk", "data_quality")),
    "benchmark_outlook": (("compatible benchmark model",), ("portfolio_risk", "portfolio_backtest")),
    "today_attention": (("today briefing snapshot",), ("portfolio_events", "data_quality")),
    "decision_journal": (("append-only decisions and reviews",), ("historical_change", "company_analysis")),
}
CAPABILITY_REGISTRY = {
    name: descriptor.model_copy(update={"internal_dependencies": relationships[0], "can_compose_with": relationships[1]})
    for name, descriptor in CAPABILITY_REGISTRY.items()
    if (relationships := _DESCRIPTOR_RELATIONSHIPS[name])
}


class CapabilityPlanStep(BaseModel):
    step_id: str
    capability: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    depends_on: list[str] = Field(default_factory=list)
    reason_code: ReasonCode
    expected_output: str


class CapabilityPlan(BaseModel):
    goal: str
    entities: list[ResolvedEntity] = Field(default_factory=list)
    time_context: TimeContext | None = None
    portfolio_context_required: bool = False
    steps: list[CapabilityPlanStep]
    response_mode: ResponseMode = ResponseMode.COMPOSED
    registry_version: str = CAPABILITY_REGISTRY_VERSION
    planner_model: str = "deterministic-capability-planner-v1"
    planner_prompt_version: str = PLANNER_PROMPT_VERSION


class PlanValidationError(ValueError):
    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class PlannerTelemetry:
    invoked: bool
    model: str
    latency_ms: float
    validation_latency_ms: float
    repair_attempted: bool
    plan_node_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_hit: bool = False


def _plan_depth(steps: list[CapabilityPlanStep]) -> int:
    parents = {step.step_id: step.depends_on for step in steps}
    memo: dict[str, int] = {}
    def depth(node: str, visiting: set[str]) -> int:
        if node in visiting:
            return MAX_PLAN_DEPTH + 1
        if node in memo:
            return memo[node]
        value = 1 + max((depth(parent, {*visiting, node}) for parent in parents.get(node, [])), default=0)
        memo[node] = value
        return value
    return max((depth(step.step_id, set()) for step in steps), default=0)


def validate_capability_plan(plan: CapabilityPlan, request_context: dict[str, Any] | None = None,
                             registry: dict[str, CapabilityDescriptor] = CAPABILITY_REGISTRY) -> CapabilityPlan:
    context = request_context or {}
    errors: list[str] = []
    if plan.registry_version != CAPABILITY_REGISTRY_VERSION:
        errors.append("registry_version_mismatch")
    if len(plan.entities) > MAX_ENTITIES:
        errors.append("too_many_entities")
    resolved_ids = set(context.get("resolved_entity_ids") or [])
    if resolved_ids and not {entity.canonical_id for entity in plan.entities} <= resolved_ids:
        errors.append("planner_invented_entity")
    if plan.time_context and plan.time_context.start and plan.time_context.end and plan.time_context.start >= plan.time_context.end:
        errors.append("invalid_time_context")
    if context.get("permissions") not in {None, "owner_scoped_read_only"}:
        errors.append("unsupported_permission_scope")
    ids = [step.step_id for step in plan.steps]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", value) for value in ids):
        errors.append("invalid_or_duplicate_step_id")
    if len(plan.steps) > MAX_SYNCHRONOUS_CAPABILITIES + MAX_HEAVY_JOBS:
        errors.append("too_many_plan_nodes")
    heavy_count = 0; synchronous_count = 0
    entity_kinds = {entity.kind for entity in plan.entities}
    for step in plan.steps:
        descriptor = registry.get(step.capability)
        if descriptor is None:
            errors.append(f"unknown_capability:{step.capability}")
            continue
        heavy_count += int(descriptor.heavy_job); synchronous_count += int(descriptor.synchronous)
        if step.expected_output != descriptor.output_schema:
            errors.append(f"output_schema_mismatch:{step.step_id}")
        if len(step.depends_on) > MAX_DEPENDENCIES_PER_STEP:
            errors.append(f"too_many_dependencies:{step.step_id}")
        if any(parent not in ids or parent == step.step_id for parent in step.depends_on):
            errors.append(f"invalid_dependency:{step.step_id}")
        if "portfolio" in descriptor.required_context and not context.get("portfolio_id"):
            errors.append(f"portfolio_required:{step.capability}")
        step_entities = list(step.inputs.get("entity_ids") or [])
        count = len(step_entities)
        if count < descriptor.min_entities or count > descriptor.max_entities:
            errors.append(f"entity_count:{step.capability}")
        if step_entities and not set(step_entities) <= {entity.canonical_id for entity in plan.entities}:
            errors.append(f"unresolved_entity:{step.capability}")
        if step_entities and descriptor.supported_entities and not entity_kinds.intersection(descriptor.supported_entities):
            errors.append(f"entity_type:{step.capability}")
        if step.capability == "portfolio_scenario":
            allowed = {"rates_up", "rates_down", "recession", "ai_spending_up", "ai_spending_down", "oil_up", "inflation_up"}
            if not set(step.inputs.get("scenario_factors") or []) <= allowed:
                errors.append("unsupported_scenario_factor")
        if any(key in step.inputs for key in ("python", "sql", "function", "api_url", "code")):
            errors.append(f"arbitrary_execution_input:{step.step_id}")
    if synchronous_count > MAX_SYNCHRONOUS_CAPABILITIES:
        errors.append("too_many_synchronous_capabilities")
    if heavy_count > MAX_HEAVY_JOBS:
        errors.append("too_many_heavy_jobs")
    if _plan_depth(plan.steps) > MAX_PLAN_DEPTH:
        errors.append("cycle_or_excessive_depth")
    if plan.portfolio_context_required and not context.get("portfolio_id"):
        errors.append("portfolio_context_missing")
    if errors:
        raise PlanValidationError(sorted(set(errors)))
    return plan


def score_capability_plan(plan: CapabilityPlan) -> float:
    """Lower is better; heavy, optional, and dependency nodes carry explicit cost."""
    return round(sum(
        (4.0 if CAPABILITY_REGISTRY[step.capability].heavy_job else 1.0)
        + (0.5 if not step.required else 0.0) + 0.25 * len(step.depends_on)
        for step in plan.steps if step.capability in CAPABILITY_REGISTRY
    ), 2)


_PLAN_CACHE: dict[str, CapabilityPlan] = {}


def normalized_plan_cache_key(question: str, entities: list[ResolvedEntity]) -> str:
    normalized = re.sub(r"\b[A-Z][A-Z0-9.-]{0,9}\b", "<SECURITY>", " ".join(question.split()).upper())
    return stable_fingerprint({"query": normalized, "entities": [(e.kind, e.canonical_id) for e in entities],
                               "registry": CAPABILITY_REGISTRY_VERSION})


def _step(capability: str, entities: list[ResolvedEntity], reason: ReasonCode, *, required: bool = True,
          factors: list[str] | None = None, suffix: str = "") -> CapabilityPlanStep:
    descriptor = CAPABILITY_REGISTRY[capability]
    entity_ids = [entity.canonical_id for entity in entities if entity.kind in descriptor.supported_entities]
    inputs: dict[str, Any] = {"entity_ids": entity_ids}
    if factors:
        inputs["scenario_factors"] = factors
    return CapabilityPlanStep(step_id=f"{capability}{suffix}", capability=capability, inputs=inputs,
                              required=required, reason_code=reason, expected_output=descriptor.output_schema)


def deterministic_capability_plan(question: str, entities: list[ResolvedEntity], *, portfolio_id: str | None,
                                  conversation: ConversationAnalyticalContext | None = None) -> CapabilityPlan:
    lower = " ".join(question.lower().split())
    securities = [entity for entity in entities if entity.kind == EntityKind.SECURITY]
    has_portfolio = bool(portfolio_id or re.search(r"\b(my|the|current) portfolio\b|\bholdings\b", lower))
    factors: list[str] = []
    for phrases, factor in ((('rates rise', 'rates increase', 'rates stay high', 'higher rates'), 'rates_up'), (('rates fall', 'rates decline', 'lower rates'), 'rates_down'),
                            (('recession',), 'recession'), (('ai spending slows', 'ai capex slows'), 'ai_spending_down'),
                            (('oil rises', 'oil shock'), 'oil_up'), (('inflation rises',), 'inflation_up')):
        if any(phrase in lower for phrase in phrases): factors.append(factor)
    steps: list[CapabilityPlanStep] = []
    if any(word in lower for word in ("backtest", "extra return", "drawdown justified")):
        steps.append(_step("portfolio_backtest", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("risk", "drawdown", "current")):
            steps.insert(0, _step("portfolio_risk", entities, ReasonCode.SUPPORTING_CONTEXT))
    elif factors and has_portfolio and any(word in lower for word in ("what if", "happens", "benefit", "suffer", "affect")):
        steps.append(_step("portfolio_scenario", entities, ReasonCode.SCENARIO_INPUT, factors=factors))
    else:
        if len(securities) >= 2 and any(word in lower for word in ("compare", " versus ", " vs ", "which one")):
            steps.append(_step("company_comparison", securities, ReasonCode.COMPARISON_CONTEXT))
        elif securities and any(word in lower for word in (
            "fundamental", "valuation", "expensive", "earnings", "make money", "business", "revenue segment",
            "margin", "cash flow", "catalyst", "company risk", "technical", "moving average", "rsi", "support",
            "resistance", "ownership", "insider", "short interest", "sentiment", "bull case", "bear case",
            "investment case", "decision summary", "research source", "data freshness",
        )):
            steps.append(_step("company_analysis", securities[:1], ReasonCode.PRIMARY_QUESTION))
        if has_portfolio and any(word in lower for word in ("expensive", "overvalued", "valuation relative")):
            steps.append(_step("valuation_ranking", entities, ReasonCode.PRIMARY_QUESTION))
        if has_portfolio and any(word in lower for word in ("fundamentals are weakening", "weakening fundamentals", "improving fundamentals")):
            steps.append(_step("multifactor_screen", entities, ReasonCode.SUPPORTING_CONTEXT))
        if any(word in lower for word in ("macro", "rates", "growth conditions", "inflation", "economic", "recession")):
            steps.append(_step("macro_state", entities, ReasonCode.SUPPORTING_CONTEXT, required="macro" in lower or "data agree" in lower))
        if any(word in lower for word in ("market regime", "breadth", "sector leadership", "market environment")):
            steps.append(_step("market_state", entities, ReasonCode.SUPPORTING_CONTEXT))
        if any(word in lower for word in ("prediction", "odds", "probability", "probabilities", "polymarket", "kalshi")):
            steps.append(_step("prediction_markets", entities, ReasonCode.SUPPORTING_CONTEXT, required="prediction" in lower))
        if has_portfolio and any(word in lower for word in ("risk", "vulnerable", "vulnerability", "exposed", "diversification", "positioned", "holding", "holdings", "fits my portfolio", "fit my portfolio")):
            capability = "portfolio_intelligence" if any(word in lower for word in ("macro", "inflation", "economic", "recession", "hidden", "diversification", "exposed")) else "portfolio_risk"
            steps.append(_step(capability, entities, ReasonCode.PORTFOLIO_FIT))
        if "changed" in lower or "since last review" in lower or "since i last" in lower:
            if has_portfolio and not securities:
                steps.append(_step("portfolio_change", entities, ReasonCode.CHANGE_CONTEXT))
                if "macro" in lower:
                    macro_entities = [entity for entity in entities if entity.kind == EntityKind.MACRO_FACTOR][:1]
                    steps.append(_step("historical_change", macro_entities, ReasonCode.CHANGE_CONTEXT))
            else:
                steps.append(_step("historical_change", securities[:1], ReasonCode.CHANGE_CONTEXT))
        if any(word in lower for word in ("opportunity", "strongest current")):
            steps.append(_step("portfolio_overview", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("argument against", "counterargument", "countercase", "counter case", "bear case", "challenge this recommendation")):
            steps.append(_step("recommendation_countercase", entities, ReasonCode.SUPPORTING_CONTEXT))
        if any(word in lower for word in ("new cash", "invest new cash")):
            steps.append(_step("cash_allocation", entities, ReasonCode.PRIMARY_QUESTION))
        if "watchlist" in lower:
            steps.append(_step("watchlist_comparison", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("rebalance", "optimize", "optimization")):
            steps.append(_step("portfolio_analysis", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("deep research", "research dossier", "full company research")) and securities:
            steps.append(_step("company_research", securities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("data quality", "missing reliable data", "data coverage", "reliable is the data", "trust these rankings", "complete is the evidence")):
            steps.append(_step("data_quality", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("upcoming events", "upcoming catalysts", "earnings calendar")):
            steps.append(_step("portfolio_events", entities, ReasonCode.PRIMARY_QUESTION))
        if "score" in lower and securities:
            steps.append(_step("score_attribution", entities, ReasonCode.PRIMARY_QUESTION))
        if "invalidate" in lower and "thesis" in lower:
            steps.append(_step("thesis_invalidation", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("replacement", "replace it", "replace this")):
            steps.append(_step("thesis_replacement", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("decision journal", "retrospective", "why did i")):
            steps.append(_step("decision_journal", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("what matters today", "attention today")):
            steps.append(_step("today_attention", entities, ReasonCode.PRIMARY_QUESTION))
        if any(word in lower for word in ("versus spy", "vs spy", "relative to spy", "benchmark")) and has_portfolio:
            steps.append(_step("benchmark_outlook", entities, ReasonCode.PRIMARY_QUESTION))
    # Stable de-duplication and minimum-capability scoring: the first occurrence
    # wins, then irrelevant optional context is not added merely because it exists.
    steps = list({step.capability: step for step in reversed(steps)}.values())[::-1]
    if not steps:
        raise PlanValidationError(["unsupported_analytical_requirement"])
    if len(steps) > MAX_SYNCHRONOUS_CAPABILITIES + MAX_HEAVY_JOBS:
        steps = sorted(steps, key=lambda row: (not row.required, row.reason_code != ReasonCode.PRIMARY_QUESTION))[:MAX_SYNCHRONOUS_CAPABILITIES + MAX_HEAVY_JOBS]
    return CapabilityPlan(goal=question[:500], entities=entities, portfolio_context_required=any(
        "portfolio" in CAPABILITY_REGISTRY[step.capability].required_context for step in steps
    ), steps=steps, response_mode=ResponseMode.COMPOSED)


PlannerModelCall = Callable[[dict[str, Any]], dict[str, Any]]


def plan_with_model(question: str, entities: list[ResolvedEntity], *, portfolio_id: str | None,
                    model_call: PlannerModelCall, model_name: str, conversation: ConversationAnalyticalContext | None = None) -> tuple[CapabilityPlan, PlannerTelemetry]:
    started = time.monotonic(); repaired = False
    context = {"portfolio_id": portfolio_id, "resolved_entity_ids": [entity.canonical_id for entity in entities]}
    cache_key = normalized_plan_cache_key(question, entities)
    cached = _PLAN_CACHE.get(cache_key)
    if cached:
        return cached.model_copy(deep=True), PlannerTelemetry(True, model_name, 0.0, 0.0, False, len(cached.steps), cache_hit=True)
    payload = {
        "prompt_version": PLANNER_PROMPT_VERSION, "registry_version": CAPABILITY_REGISTRY_VERSION,
        "question": question[:800], "entities": [row.model_dump(mode="json") for row in entities],
        "portfolio_available": bool(portfolio_id),
        "capabilities": [{"name": row.name, "description": row.description, "entities": list(row.supported_entities),
                          "required_context": list(row.required_context), "heavy_job": row.heavy_job,
                          "output_schema": row.output_schema} for row in CAPABILITY_REGISTRY.values()],
        "constraints": {"max_sync": MAX_SYNCHRONOUS_CAPABILITIES, "max_heavy": MAX_HEAVY_JOBS,
                        "max_depth": MAX_PLAN_DEPTH, "registered_only": True, "no_reasoning_prose": True},
        "conversation_context": (conversation or ConversationAnalyticalContext()).model_dump(mode="json"),
    }
    last_error: Exception | None = None
    for attempt in range(MAX_PLANNER_REPAIRS + 1):
        try:
            raw = model_call({**payload, "repair": attempt == 1})
            plan = CapabilityPlan.model_validate(raw)
            plan = plan.model_copy(update={"planner_model": model_name,
                                           "planner_prompt_version": PLANNER_PROMPT_VERSION})
            validation_started = time.monotonic(); validate_capability_plan(plan, context)
            validation_ms = (time.monotonic() - validation_started) * 1000
            _PLAN_CACHE[cache_key] = plan.model_copy(deep=True)
            return plan, PlannerTelemetry(True, model_name, (time.monotonic() - started) * 1000,
                                          validation_ms, repaired, len(plan.steps),
                                          raw.get("input_tokens"), raw.get("output_tokens"))
        except (ValidationError, PlanValidationError, TypeError, ValueError) as exc:
            last_error = exc; repaired = attempt == 0
    raise PlanValidationError([f"planner_schema_failure:{type(last_error).__name__}"])


def should_use_compositional_planner(question: str, direct_intent: str, confidence: float,
                                     conversation: ConversationAnalyticalContext | None = None) -> bool:
    lower = question.lower()
    established_compound_routes = {
        "OPPORTUNITY_RANKING", "THESIS_REPLACEMENT", "PORTFOLIO_CHANGE", "VALUATION_RANKING",
        "HIDDEN_RISK", "MULTI_SCENARIO", "WATCHLIST_COMPARISON", "PORTFOLIO_EVENTS",
        "DATA_QUALITY", "SCORE_ATTRIBUTION", "THESIS_INVALIDATION", "PORTFOLIO_ANALYSIS",
        "MULTIFACTOR_SCREEN", "RECOMMENDATION_COUNTERCASE", "CASH_ALLOCATION",
        "RESEARCH_RANKING",
        "PORTFOLIO_PERFORMANCE", "GAIN_LOSS_ATTRIBUTION", "RISK_EFFICIENCY", "DIVERSIFICATION",
        "OVERLAP_RISK", "DOWNSIDE_CAPACITY", "POSITION_SIZING", "CASH_RESERVE", "SECTOR_SHOCK",
        "DECISION_VS_INDEX", "THESIS_STRENGTH", "POSITION_ACTION_REVIEW", "AVERAGING_DOWN_REVIEW",
        "TARGET_PRICE_REVIEW", "OPTIONS_COSTS", "OPTIONS_EXPIRY", "TRADE_PLAN_METRICS",
    }
    if direct_intent in established_compound_routes:
        return False
    domains = sum(bool(re.search(pattern, lower)) for pattern in (
        r"\bmacro|rates|inflation|recession", r"\bmarket regime|breadth|sector leadership",
        r"\bprediction|odds|probability", r"\bportfolio|holdings|diversification|exposed",
        r"\bcompare|\bversus\b|\bvs\b", r"\bchanged|since last review", r"\bwhat if|scenario|backtest",
    ))
    follow_up = bool(conversation and conversation.active_entities and re.search(r"\b(which one|that choice|how does that|what if|against that|same scenario)\b", lower))
    return follow_up or domains >= 2 or direct_intent == "GENERAL" or confidence < 0.8


class SupportedFinding(BaseModel):
    result_id: str
    capability: str
    source_category: SourceCategory
    status: AnalysisStatus
    summary: str


class ComposedAnalysisResult(BaseModel):
    question: str
    result_id: str
    registry_version: str = CAPABILITY_REGISTRY_VERSION
    component_results: list[AnalysisResult]
    overall_status: AnalysisStatus
    supported_findings: list[SupportedFinding] = Field(default_factory=list)
    conflicting_findings: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    pending_jobs: list[JobReference] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)


def _component_summary(result: AnalysisResult) -> str:
    if result.summary:
        for key in ("message", "conclusion", "regime"):
            if result.summary.get(key): return str(result.summary[key])
    if isinstance(result.data, dict):
        for key in ("headline", "summary", "regime", "state", "message"):
            value = result.data.get(key)
            if value and str(value).upper() not in {"SUCCESS", "PARTIAL", "UNAVAILABLE"}:
                return str(value)
        for key in ("positions", "candidates", "events", "findings", "results", "material_changes"):
            value = result.data.get(key)
            if isinstance(value, list):
                return f"{result.capability.replace('_', ' ').title()} produced {len(value)} typed {key.replace('_', ' ')} row{'s' if len(value) != 1 else ''}."
    return f"{result.capability.replace('_', ' ').title()} did not expose a substantive deterministic summary."


def compose_results(question: str, plan: CapabilityPlan, results: list[AnalysisResult]) -> ComposedAnalysisResult:
    by_capability = {result.capability: result for result in results}
    required = {step.capability for step in plan.steps if step.required}
    required_results = [by_capability.get(name) for name in required]
    pending = [result.job for result in results if result.job and result.status == AnalysisStatus.PENDING]
    usable = [result for result in results if result.status in {AnalysisStatus.SUCCESS, AnalysisStatus.PARTIAL}]
    if any(result and result.status == AnalysisStatus.FAILED for result in required_results):
        # One bounded fallback composition pass preserves independently
        # verified components instead of discarding them with the failed node.
        status = AnalysisStatus.PARTIAL if usable else AnalysisStatus.FAILED
    elif pending and not usable:
        status = AnalysisStatus.PENDING
    elif any(result is None or result.status == AnalysisStatus.UNAVAILABLE for result in required_results):
        status = AnalysisStatus.PARTIAL if usable else AnalysisStatus.UNAVAILABLE
    elif pending:
        status = AnalysisStatus.PARTIAL
    elif any(result and result.status == AnalysisStatus.PARTIAL for result in required_results) or any(
        result.status != AnalysisStatus.SUCCESS for result in results
    ):
        status = AnalysisStatus.PARTIAL
    else:
        status = AnalysisStatus.SUCCESS
    findings: list[SupportedFinding] = []
    limitations: list[str] = []
    for result in results:
        descriptor = CAPABILITY_REGISTRY.get(result.capability)
        findings.append(SupportedFinding(
            result_id=f"result_{stable_fingerprint({'capability': result.capability, 'fingerprint': result.input_fingerprint})[:16]}",
            capability=result.capability,
            source_category=descriptor.source_category if descriptor else SourceCategory.MODEL_OUTPUT,
            status=result.status, summary=_component_summary(result),
        ))
        limitations.extend(result.limitations)
        if result.status in {AnalysisStatus.UNAVAILABLE, AnalysisStatus.FAILED}:
            limitations.append(f"{result.capability.replace('_', ' ')} was {result.status.value.lower()}.")
    conflicts: list[dict[str, Any]] = []
    polarities: dict[str, list[str]] = {"positive": [], "negative": []}
    for finding in findings:
        lower = finding.summary.lower()
        if any(word in lower for word in ("positive", "improving", "favorable", "strong")): polarities["positive"].append(finding.capability)
        if any(word in lower for word in ("negative", "weakening", "unfavorable", "risk", "fragile")): polarities["negative"].append(finding.capability)
    if polarities["positive"] and polarities["negative"]:
        conflicts.append({"type": "MIXED_DIRECTION", "supporting": polarities["positive"], "opposing": polarities["negative"]})
    coverage = {"planned": len(plan.steps), "returned": len(results), "usable": len(usable),
                "required": len(required), "required_usable": sum(bool(row and row.status in {AnalysisStatus.SUCCESS, AnalysisStatus.PARTIAL}) for row in required_results)}
    result_id = f"composed_{stable_fingerprint({'question': question, 'plan': plan.model_dump(mode='json'), 'results': [r.input_fingerprint for r in results]})[:20]}"
    return ComposedAnalysisResult(question=question, result_id=result_id, component_results=results,
                                  overall_status=status, supported_findings=findings,
                                  conflicting_findings=conflicts, limitations=list(dict.fromkeys(limitations)),
                                  pending_jobs=[row for row in pending if row], coverage=coverage)


def render_composed(result: ComposedAnalysisResult) -> str:
    def public_limitation(value: str) -> bool:
        lowered = value.lower()
        return not any(marker in lowered for marker in (
            "legacy analysisresult adapter", "versioned registry", "request-scoped verifier",
        ))

    usable = [row for row in result.supported_findings if row.status in {AnalysisStatus.SUCCESS, AnalysisStatus.PARTIAL}]
    unavailable = [row for row in result.supported_findings if row.status in {AnalysisStatus.UNAVAILABLE, AnalysisStatus.FAILED}]
    if result.overall_status == AnalysisStatus.PENDING and not usable:
        jobs = ", ".join(job.id for job in result.pending_jobs) or "the durable job"
        return f"The requested analysis is still running ({jobs}). No interim financial result was invented."
    answer = usable[0].summary if usable else "EagleEyes does not yet have enough supported evidence to answer this question."
    evidence = "\n".join(f"{index}. [{row.source_category.value}] {row.summary}" for index, row in enumerate(usable, 1)) or "1. No verified component result is currently available."
    sections = [f"**Answer**\n\n{answer}", f"**Key evidence**\n\n{evidence}"]
    if result.conflicting_findings:
        conflict = result.conflicting_findings[0]
        sections.append("**Counterevidence / tradeoffs**\n\nThe verified components point in mixed directions: "
                        + ", ".join(conflict["supporting"]) + " are supportive, while "
                        + ", ".join(conflict["opposing"]) + " are opposing evidence.")
    missing = [f"{row.capability}: {row.status.value}" for row in unavailable]
    missing.extend(value for value in result.limitations if public_limitation(value))
    if missing:
        sections.append("**Missing or unavailable evidence**\n\n" + "\n".join(f"- {item}" for item in dict.fromkeys(missing)))
    sections.append(f"**Confidence / coverage**\n\nOverall status: **{result.overall_status.value}**. "
                    f"Usable components: {result.coverage.get('usable', 0)} of {result.coverage.get('planned', 0)} planned. "
                    "This is decision support, not trade execution.")
    return "\n\n".join(sections)


def composed_to_analysis_result(composed: ComposedAnalysisResult) -> AnalysisResult:
    now = datetime.now(timezone.utc)
    dependencies = [DependencyResult(name=row.capability, required=True, status=row.status) for row in composed.component_results]
    passed = composed.overall_status not in {AnalysisStatus.FAILED, AnalysisStatus.UNAVAILABLE}
    return AnalysisResult(
        capability="composed_analysis", calculation_version=COMPOSER_VERSION,
        input_fingerprint=stable_fingerprint(composed.model_dump(mode="json")), status=composed.overall_status,
        data=composed.model_dump(mode="json"), coverage=Coverage.not_tracked(), freshness=Freshness(calculated_at=now),
        dependencies=dependencies, limitations=composed.limitations,
        verification=VerificationResult(passed=passed, answer_allowed=passed, recommendation_allowed=False,
            checks=[VerificationCheck(name="registered_composition", passed=passed,
                severity=VerificationSeverity.INFO if passed else VerificationSeverity.ERROR,
                message="Every component was selected from the versioned registry and retained its canonical status.")]),
        job=composed.pending_jobs[0] if len(composed.pending_jobs) == 1 and not any(
            row.status in {AnalysisStatus.SUCCESS, AnalysisStatus.PARTIAL} for row in composed.component_results
        ) else None,
    )


def context_from_previous(raw: dict[str, Any] | None) -> ConversationAnalyticalContext:
    raw = raw or {}
    structured = raw.get("analytical_context") if isinstance(raw.get("analytical_context"), dict) else raw
    try:
        return ConversationAnalyticalContext.model_validate(structured)
    except ValidationError:
        entities = [ResolvedEntity(kind=EntityKind.SECURITY, canonical_id=str(ticker).upper()) for ticker in raw.get("tickers", [])]
        return ConversationAnalyticalContext(active_entities=entities, active_portfolio=raw.get("portfolio_id"),
                                             active_comparison=list(raw.get("tickers", []))[:MAX_COMPARISON_ENTITIES],
                                             active_capabilities=list(raw.get("tool_names", [])),
                                             recent_result_ids=list(raw.get("result_ids", [])))


def resolve_entities(question: str, tickers: Iterable[str], *, portfolio_id: str | None,
                     previous: ConversationAnalyticalContext | None = None) -> list[ResolvedEntity]:
    entities = [ResolvedEntity(kind=EntityKind.SECURITY, canonical_id=str(ticker).upper(), source_text=str(ticker)) for ticker in tickers]
    lower = question.lower()
    if not entities and previous and re.search(r"\b(which one|it|that choice|same|how does that|what if)\b", lower):
        entities.extend(previous.active_entities)
    if portfolio_id:
        entities.append(ResolvedEntity(kind=EntityKind.PORTFOLIO, canonical_id=portfolio_id, display_name="active portfolio", source_text="my portfolio"))
    if re.search(r"\bspy\b|\bbenchmark\b", lower):
        entities.append(ResolvedEntity(kind=EntityKind.BENCHMARK, canonical_id="SPY", display_name="SPDR S&P 500 ETF Trust"))
    for phrase, factor in (("rates", "rates"), ("inflation", "inflation"), ("growth", "growth"), ("recession", "recession")):
        if phrase in lower: entities.append(ResolvedEntity(kind=EntityKind.MACRO_FACTOR, canonical_id=factor, source_text=phrase))
    return list({(entity.kind, entity.canonical_id): entity for entity in entities}.values())[:MAX_ENTITIES]
