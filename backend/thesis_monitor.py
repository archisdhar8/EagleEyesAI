from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from . import database, evidence, theses
from .resilience import TTLCache


EvaluationState = Literal["SUPPORTS", "WEAKENS", "CONTRADICTS", "UNCHANGED", "UNRELATED", "INSUFFICIENT_EVIDENCE"]
RelevanceState = Literal["RELEVANT", "POSSIBLY_RELEVANT", "UNRELATED"]
AgreementState = Literal["CONSISTENT", "MOSTLY_CONSISTENT", "MIXED", "CONFLICTING", "INSUFFICIENT"]
BreakerState = Literal["NOT_TRIGGERED", "WARNING", "TRIGGERED", "CANNOT_EVALUATE"]
RiskState = Literal["DORMANT", "INCREASING", "MATERIALIZED", "DECREASING", "INSUFFICIENT_EVIDENCE"]
CatalystState = Literal["PENDING", "DEVELOPING", "REALIZED", "FAILED", "DELAYED", "INSUFFICIENT_EVIDENCE"]
OverallStatus = Literal["STABLE", "STRENGTHENING", "WEAKENING", "MATERIAL_REVIEW_REQUIRED", "THESIS_BREAKER_TRIGGERED", "INSUFFICIENT_EVIDENCE"]
CoverageLevel = Literal["HIGH", "MEDIUM", "LOW", "UNAVAILABLE"]


class MonitoringPolicy(BaseModel):
    warning_proximity_percent: float = 5.0
    critical_contradiction_review_weight: int = 4
    material_review_weight: int = 5
    strengthening_weight: int = 4
    max_evidence_per_item: int = 8
    cache_seconds: int = 300


DEFAULT_POLICY = MonitoringPolicy()


class MonitoringEvidence(BaseModel):
    evidence_type: evidence.EvidenceType
    metric: str
    label: str
    relevance: RelevanceState
    relationship: EvaluationState
    previous_value: float | bool | str | None = None
    current_value: float | bool | str | None = None
    unit: str | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    percentage_point_change: float | None = None
    direction: evidence.Direction
    materiality: evidence.Materiality
    source: str
    source_references: list[str] = Field(default_factory=list)
    previous_as_of: datetime | None = None
    current_as_of: datetime | None = None
    freshness: evidence.Freshness
    evidence_quality: evidence.EvidenceQuality
    methodology: str | None = None
    independence_group: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssumptionMonitoringResult(BaseModel):
    assumption_id: str
    description: str
    category: str
    importance: str
    state: EvaluationState
    condition_met: bool | None = None
    deterministic: bool
    relevance_confidence: CoverageLevel
    data_coverage: CoverageLevel
    freshness: CoverageLevel
    evidence_quality: CoverageLevel
    evidence_agreement: AgreementState
    evidence: list[MonitoringEvidence] = Field(default_factory=list)
    unrelated_evidence_count: int = 0
    explanation: str
    rule: str | None = None


class FactorMonitoringResult(BaseModel):
    factor_id: str
    factor_type: Literal["RISK", "CATALYST", "BREAKER"]
    description: str
    state: str
    condition_met: bool | None = None
    deterministic: bool
    periods_required: int = 1
    periods_evaluated: int = 0
    threshold_distance: float | None = None
    evidence_agreement: AgreementState
    evidence: list[MonitoringEvidence] = Field(default_factory=list)
    explanation: str
    rule: str | None = None


class ThesisMonitoringResult(BaseModel):
    thesis_id: str
    thesis_version: int
    ticker: str
    baseline_review_at: datetime
    evaluated_at: datetime
    overall_status: OverallStatus
    requires_review: bool
    assumption_results: list[AssumptionMonitoringResult]
    risk_results: list[FactorMonitoringResult]
    catalyst_results: list[FactorMonitoringResult]
    thesis_breaker_results: list[FactorMonitoringResult]
    evidence_coverage: list[evidence.EvidenceCoverage]
    freshness: CoverageLevel
    evidence_quality: CoverageLevel
    counts: dict[str, int]
    warnings: list[str] = Field(default_factory=list)
    calculation_version: Literal["thesis-monitor-v1"] = "thesis-monitor-v1"
    created_at: datetime


QualitativeClassifier = Callable[[dict[str, Any], list[MonitoringEvidence]], tuple[Any, ...]]
_CACHE = TTLCache(max_entries=128)

METRIC_ALIASES = {
    "gross_margin": "fundamental.gross_margin", "operating_margin": "fundamental.operating_margin",
    "net_margin": "fundamental.net_margin", "revenue_growth": "fundamental.revenue_yoy",
    "revenue_yoy": "fundamental.revenue_yoy", "eps_growth": "fundamental.eps_yoy",
    "eps_yoy": "fundamental.eps_yoy", "fcf_growth": "fundamental.free_cash_flow_yoy",
    "free_cash_flow_yoy": "fundamental.free_cash_flow_yoy", "total_debt": "fundamental.total_debt",
    "cash": "fundamental.cash", "shares_diluted": "fundamental.shares_diluted", "pe": "valuation.pe",
    "price_to_sales": "valuation.price_to_sales", "fcf_yield": "valuation.free_cash_flow_yield",
    "price": "price.close", "unemployment": "macro.UNRATE", "fed_funds": "macro.FEDFUNDS",
    "ten_year_yield": "macro.DGS10", "credit_spread": "macro.BAMLH0A0HYM2",
}

CATEGORY_EVIDENCE: dict[str, set[evidence.EvidenceType]] = {
    "GROWTH": {"FUNDAMENTAL", "ESTIMATE", "EARNINGS", "GUIDANCE"},
    "PROFITABILITY": {"FUNDAMENTAL", "EARNINGS", "GUIDANCE"}, "MARGIN": {"FUNDAMENTAL", "EARNINGS", "GUIDANCE"},
    "VALUATION": {"VALUATION", "PRICE_MARKET"}, "BALANCE_SHEET": {"FUNDAMENTAL", "MACRO", "RISK"},
    "COMPETITIVE_POSITION": {"NEWS", "EVENT", "EARNINGS", "GUIDANCE", "PREDICTION_MARKET"},
    "CAPITAL_ALLOCATION": {"FUNDAMENTAL", "NEWS", "EVENT", "GUIDANCE"},
    "DEMAND": {"FUNDAMENTAL", "ESTIMATE", "EARNINGS", "GUIDANCE", "NEWS", "PREDICTION_MARKET"},
    "MACRO": {"MACRO", "PREDICTION_MARKET"}, "MANAGEMENT": {"NEWS", "EVENT", "EARNINGS", "GUIDANCE"},
    "REGULATORY": {"NEWS", "EVENT", "PREDICTION_MARKET"}, "PORTFOLIO_FIT": {"PORTFOLIO", "RISK"},
    "CUSTOM": {"FUNDAMENTAL", "VALUATION", "ESTIMATE", "EARNINGS", "GUIDANCE", "NEWS", "MACRO", "PREDICTION_MARKET", "EVENT"},
}

STOPWORDS = {"the", "and", "that", "this", "with", "from", "remains", "remain", "company", "current", "will", "does", "not", "above", "below", "than", "into", "enough"}


def normalize_metric(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().lower().replace(" ", "_")
    return METRIC_ALIASES.get(raw, value.strip())


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def evaluate_condition(value: float | None, operator: str | None, threshold: float | None) -> bool | None:
    if value is None or operator is None or threshold is None:
        return None
    return {">": value > threshold, ">=": value >= threshold, "<": value < threshold,
            "<=": value <= threshold, "=": math.isclose(value, threshold, rel_tol=1e-9, abs_tol=1e-12),
            "!=": not math.isclose(value, threshold, rel_tol=1e-9, abs_tol=1e-12)}.get(operator)


def parse_period_requirement(value: str | None) -> int:
    if not value:
        return 1
    match = re.search(r"\b(\d+)\b", value)
    if match:
        return max(1, min(12, int(match.group(1))))
    words = {"one": 1, "two": 2, "three": 3, "four": 4}
    lowered = value.lower()
    return next((count for word, count in words.items() if word in lowered), 1)


def _proximity(value: float, threshold: float) -> float:
    if abs(threshold) < 1e-12:
        return abs(value - threshold)
    return abs(value - threshold) / abs(threshold) * 100


def threshold_warning(value: float | None, operator: str | None, threshold: float | None, policy: MonitoringPolicy = DEFAULT_POLICY) -> bool:
    if value is None or operator is None or threshold is None or evaluate_condition(value, operator, threshold):
        return False
    return _proximity(value, threshold) <= policy.warning_proximity_percent


def _tokens(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) >= 3 and word not in STOPWORDS}


def relevance(item: dict[str, Any], change: evidence.EvidenceChange) -> RelevanceState:
    metric = normalize_metric(item.get("metric"))
    if metric:
        return "RELEVANT" if change.metric == metric else "UNRELATED"
    mapping = item.get("evidence_mapping") or {}
    linked_metrics = {normalize_metric(str(value)) for value in mapping.get("metrics", [])}
    if linked_metrics and change.metric in linked_metrics:
        return "RELEVANT"
    linked_types = {str(value).upper() for value in mapping.get("evidence_types", [])}
    if change.evidence_type in linked_types:
        return "RELEVANT"
    overlap = _tokens(str(item.get("description") or "")) & _tokens(f"{change.label} {change.metric} {json.dumps(change.metadata, default=str)}")
    if overlap:
        return "RELEVANT"
    category = str(item.get("category") or mapping.get("category") or "CUSTOM")
    return "POSSIBLY_RELEVANT" if change.evidence_type in CATEGORY_EVIDENCE.get(category, CATEGORY_EVIDENCE["CUSTOM"]) else "UNRELATED"


def _independence_group(change: evidence.EvidenceChange) -> str:
    metadata = change.metadata.get("current_metadata") or change.metadata.get("previous_metadata") or {}
    identity = metadata.get("event_id") or metadata.get("novelty_key") or (change.source_references[0] if change.source_references else None)
    if not identity:
        identity = re.sub(r"[^a-z0-9]+", "-", change.metric.lower()).strip("-")
    return hashlib.sha256(str(identity).encode()).hexdigest()[:16]


def _monitoring_evidence(change: evidence.EvidenceChange, rel: RelevanceState, relationship: EvaluationState) -> MonitoringEvidence:
    return MonitoringEvidence(
        evidence_type=change.evidence_type, metric=change.metric, label=change.label, relevance=rel,
        relationship=relationship, previous_value=change.previous_value, current_value=change.current_value,
        unit=change.unit, absolute_change=change.absolute_change, percent_change=change.percent_change,
        percentage_point_change=change.percentage_point_change, direction=change.direction, materiality=change.materiality, source=change.source,
        source_references=change.source_references, previous_as_of=change.previous_as_of, current_as_of=change.current_as_of,
        freshness=change.freshness, evidence_quality=change.evidence_quality, methodology=change.methodology,
        independence_group=_independence_group(change), metadata=change.metadata,
    )


def _level(values: list[str], *, unavailable: str = "UNAVAILABLE") -> CoverageLevel:
    if not values:
        return unavailable  # type: ignore[return-value]
    ranks = {"UNAVAILABLE": 0, "LOW": 1, "STALE": 1, "MEDIUM": 2, "CURRENT": 3, "HIGH": 3}
    score = sum(ranks.get(value, 0) for value in values) / len(values)
    return "HIGH" if score >= 2.5 else "MEDIUM" if score >= 1.5 else "LOW" if score > 0 else "UNAVAILABLE"


def evidence_agreement(items: list[MonitoringEvidence]) -> AgreementState:
    independent: dict[str, EvaluationState] = {}
    for item in items:
        independent.setdefault(item.independence_group, item.relationship)
    directional = [value for value in independent.values() if value in {"SUPPORTS", "WEAKENS", "CONTRADICTS"}]
    if not directional:
        return "INSUFFICIENT"
    counts = Counter(directional)
    if len(counts) == 1:
        return "CONSISTENT"
    leading = counts.most_common()
    if len(leading) > 1 and leading[0][1] == leading[1][1]:
        return "CONFLICTING" if len(directional) == 2 else "MIXED"
    return "MOSTLY_CONSISTENT" if leading[0][1] / len(directional) >= .67 else "MIXED"


def _history_for_metric(ticker: str, bundle: dict[str, list[dict[str, Any]]], metric: str, current_as_of: datetime) -> list[evidence.EvidenceObservation]:
    dates: set[datetime] = {current_as_of}
    for row in bundle.get("fundamentals", []):
        dates.add(evidence._utc(row["fetched_at"]))
    for row in bundle.get("prices", [])[:30]:
        dates.add(evidence._utc(row["ts"]))
    for row in bundle.get("macro", []):
        dates.add(evidence._utc(row["fetched_at"]))
    for row in bundle.get("prediction_markets", [])[:60]:
        dates.add(evidence._utc(row["observed_at"]))
    values: list[evidence.EvidenceObservation] = []
    for as_of in sorted((value for value in dates if value <= current_as_of), reverse=True)[:60]:
        match = next((item for item in evidence.observations_from_bundle(ticker, bundle, as_of) if item.metric == metric and _number(item.value) is not None), None)
        if match and all(item.effective_date != match.effective_date for item in values):
            values.append(match)
    return values


def _relationship_for_change(change: evidence.EvidenceChange) -> EvaluationState:
    if change.status == "UNCHANGED":
        return "UNCHANGED"
    if change.status in {"MISSING_BASELINE", "MISSING_CURRENT", "SOURCE_DISAGREEMENT", "UNSUPPORTED"}:
        return "INSUFFICIENT_EVIDENCE"
    return "SUPPORTS" if change.direction == "UP" else "WEAKENS" if change.direction == "DOWN" else "UNCHANGED"


def _structured_assumption(item: dict[str, Any], change_set: evidence.EvidenceChangeSet, current: list[evidence.EvidenceObservation]) -> AssumptionMonitoringResult:
    metric = normalize_metric(item.get("metric"))
    observation = next((value for value in current if value.metric == metric), None)
    matching = [change for change in change_set.changes if change.metric == metric]
    value = _number(observation.value) if observation else None
    met = evaluate_condition(value, item.get("operator"), _number(item.get("target_value")))
    unreliable_market = bool(observation and observation.evidence_type == "PREDICTION_MARKET" and observation.evidence_quality in {"LOW", "UNAVAILABLE"})
    if met is None or unreliable_market:
        state: EvaluationState = "INSUFFICIENT_EVIDENCE"
    elif not met:
        state = "CONTRADICTS"
    elif matching and matching[0].status == "UNCHANGED":
        state = "UNCHANGED"
    elif matching:
        prior_met = evaluate_condition(_number(matching[0].previous_value), item.get("operator"), _number(item.get("target_value")))
        state = "SUPPORTS" if prior_met is not True or _relationship_for_change(matching[0]) == "SUPPORTS" else "WEAKENS"
    else:
        state = "SUPPORTS"
    used = [_monitoring_evidence(change, "RELEVANT", state if state != "INSUFFICIENT_EVIDENCE" else state) for change in matching[:3]]
    rule = f"{metric} {item.get('operator')} {item.get('target_value')} {item.get('unit') or ''}".strip()
    return AssumptionMonitoringResult(
        assumption_id=str(item["id"]), description=item["description"], category=item.get("category") or "CUSTOM",
        importance=item.get("importance") or "MEDIUM", state=state, condition_met=met, deterministic=True,
        relevance_confidence="HIGH", data_coverage="HIGH" if observation else "UNAVAILABLE",
        freshness=_level([observation.freshness] if observation else []), evidence_quality=_level([observation.evidence_quality] if observation else []),
        evidence_agreement=evidence_agreement(used), evidence=used,
        explanation=(f"Verified {observation.label} is {observation.value} {observation.unit or ''}; deterministic condition {rule} is {'met' if met else 'not met'}." if observation else f"No verified current observation is available for {metric}."), rule=rule,
    )


def _qualitative_item(item: dict[str, Any], change_set: evidence.EvidenceChangeSet, classifier: QualitativeClassifier | None) -> AssumptionMonitoringResult:
    candidates: list[tuple[evidence.EvidenceChange, RelevanceState]] = [(change, relevance(item, change)) for change in change_set.changes]
    related = [(change, rel) for change, rel in candidates if rel != "UNRELATED"][:DEFAULT_POLICY.max_evidence_per_item]
    traces = [_monitoring_evidence(change, rel, _relationship_for_change(change)) for change, rel in related]
    unrelated = sum(rel == "UNRELATED" for _, rel in candidates)
    model = None
    if not traces:
        state, explanation = "INSUFFICIENT_EVIDENCE", "No sufficiently relevant verified evidence was retrieved for this qualitative assumption."
    elif classifier:
        try:
            classified = classifier(item, traces)
            state, explanation, model = classified[:3]
            if len(classified) > 3 and isinstance(classified[3], dict):
                traces = [trace.model_copy(update={"relationship": classified[3].get(f"E{index + 1}", trace.relationship)}) for index, trace in enumerate(traces)]
        except Exception:
            state, explanation = "INSUFFICIENT_EVIDENCE", "Qualitative evaluation is unavailable; retrieved facts are preserved without an inferred conclusion."
    else:
        state, explanation = "INSUFFICIENT_EVIDENCE", "Relevant evidence exists, but qualitative interpretation is unavailable; no relationship was inferred."
    return AssumptionMonitoringResult(
        assumption_id=str(item["id"]), description=item["description"], category=item.get("category") or "CUSTOM",
        importance=item.get("importance") or "MEDIUM", state=state, deterministic=False,
        relevance_confidence="HIGH" if any(value.relevance == "RELEVANT" for value in traces) else "MEDIUM" if traces else "UNAVAILABLE",
        data_coverage="HIGH" if len(traces) >= 3 else "MEDIUM" if traces else "UNAVAILABLE",
        freshness=_level([value.freshness for value in traces]), evidence_quality=_level([value.evidence_quality for value in traces]),
        evidence_agreement=evidence_agreement(traces), evidence=traces, unrelated_evidence_count=unrelated,
        explanation=explanation, rule=f"bounded qualitative classifier{f' · {model}' if model else ''}",
    )


def _factor_result(item: dict[str, Any], ticker: str, change_set: evidence.EvidenceChangeSet, current: list[evidence.EvidenceObservation], bundle: dict[str, list[dict[str, Any]]], classifier: QualitativeClassifier | None) -> FactorMonitoringResult:
    factor_type = item["factor_type"]
    metric = normalize_metric(item.get("metric"))
    required = parse_period_requirement(item.get("period_requirement"))
    matching = [change for change in change_set.changes if metric and change.metric == metric]
    if metric and item.get("operator") and item.get("threshold") is not None:
        history = _history_for_metric(ticker, bundle, metric, change_set.current_as_of)
        conditions = [evaluate_condition(_number(value.value), item["operator"], _number(item["threshold"])) for value in history]
        evaluated = min(len(conditions), required)
        enough = len(conditions) >= required
        met = enough and all(value is True for value in conditions[:required])
        latest = _number(history[0].value) if history else None
        latest_reliable = bool(history and history[0].evidence_quality not in {"LOW", "UNAVAILABLE"} and history[0].freshness != "STALE")
        warning = bool(not met and latest is not None and threshold_warning(latest, item["operator"], _number(item["threshold"])))
        if factor_type == "BREAKER": state = "TRIGGERED" if met and latest_reliable else "WARNING" if (warning or met) else "NOT_TRIGGERED" if enough else "CANNOT_EVALUATE"
        elif factor_type == "RISK": state = "MATERIALIZED" if met and latest_reliable else "INCREASING" if (warning or met) else "DORMANT" if enough else "INSUFFICIENT_EVIDENCE"
        else: state = "REALIZED" if met and latest_reliable else "DEVELOPING" if (warning or met) else "PENDING" if enough else "INSUFFICIENT_EVIDENCE"
        traces = [_monitoring_evidence(change, "RELEVANT", "CONTRADICTS" if met and factor_type == "BREAKER" else _relationship_for_change(change)) for change in matching[:3]]
        rule = f"{metric} {item['operator']} {item['threshold']} for {required} consecutive period(s)"
        return FactorMonitoringResult(
            factor_id=str(item["id"]), factor_type=factor_type, description=item["description"], state=state,
            condition_met=met if enough else None, deterministic=True, periods_required=required, periods_evaluated=evaluated,
            threshold_distance=None if latest is None else _proximity(latest, float(item["threshold"])),
            evidence_agreement=evidence_agreement(traces), evidence=traces,
            explanation=(f"{evaluated} of {required} required periods were evaluable; the deterministic condition is {'met' if met else 'not met'}{'' if latest_reliable else ', but current evidence quality/freshness limits confirmation'}." if enough else f"Only {evaluated} of {required} required periods have verified observations."), rule=rule,
        )
    qualitative = _qualitative_item({**item, "category": (item.get("evidence_mapping") or {}).get("category", "CUSTOM"), "importance": "HIGH"}, change_set, classifier)
    if factor_type == "BREAKER": state = "TRIGGERED" if qualitative.state == "CONTRADICTS" else "WARNING" if qualitative.state == "WEAKENS" else "NOT_TRIGGERED" if qualitative.state == "SUPPORTS" else "CANNOT_EVALUATE"
    elif factor_type == "RISK": state = "MATERIALIZED" if qualitative.state == "CONTRADICTS" else "INCREASING" if qualitative.state == "WEAKENS" else "DECREASING" if qualitative.state == "SUPPORTS" else "INSUFFICIENT_EVIDENCE"
    else: state = "REALIZED" if qualitative.state == "SUPPORTS" else "FAILED" if qualitative.state == "CONTRADICTS" else "DEVELOPING" if qualitative.state == "WEAKENS" else "INSUFFICIENT_EVIDENCE"
    return FactorMonitoringResult(factor_id=str(item["id"]), factor_type=factor_type, description=item["description"], state=state,
        deterministic=False, periods_required=required, evidence_agreement=qualitative.evidence_agreement,
        evidence=qualitative.evidence, explanation=qualitative.explanation, rule=qualitative.rule)


def overall_status(assumptions: list[AssumptionMonitoringResult], breakers: list[FactorMonitoringResult], risks: list[FactorMonitoringResult], policy: MonitoringPolicy = DEFAULT_POLICY) -> tuple[OverallStatus, bool]:
    if any(item.state == "TRIGGERED" for item in breakers):
        return "THESIS_BREAKER_TRIGGERED", True
    weights = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    negative = sum(weights.get(item.importance, 2) * (2 if item.state == "CONTRADICTS" else 1) for item in assumptions if item.state in {"WEAKENS", "CONTRADICTS"})
    positive = sum(weights.get(item.importance, 2) for item in assumptions if item.state == "SUPPORTS")
    critical = any(item.importance in {"HIGH", "CRITICAL"} and item.state == "CONTRADICTS" for item in assumptions)
    risk_material = any(item.state == "MATERIALIZED" for item in risks)
    conflict = any(item.evidence_agreement in {"MIXED", "CONFLICTING"} and item.importance in {"HIGH", "CRITICAL"} for item in assumptions)
    if critical or risk_material or conflict or negative >= policy.material_review_weight:
        return "MATERIAL_REVIEW_REQUIRED", True
    if negative > 0:
        return "WEAKENING", True
    evaluable = [item for item in assumptions if item.state not in {"INSUFFICIENT_EVIDENCE", "UNRELATED"}]
    if not evaluable:
        return "INSUFFICIENT_EVIDENCE", True
    if positive >= policy.strengthening_weight and all(item.state not in {"WEAKENS", "CONTRADICTS"} for item in assumptions):
        return "STRENGTHENING", False
    return "STABLE", False


def evaluate_thesis(user_id: str, thesis_id: str, *, current_as_of: datetime | None = None, classifier: QualitativeClassifier | None = None, use_cache: bool = True) -> ThesisMonitoringResult:
    thesis = theses.get_thesis(user_id, thesis_id)
    now = current_as_of or datetime.now(timezone.utc)
    cache_key = f"{user_id}:{thesis_id}:{thesis['current_version']}:{now.replace(second=0,microsecond=0).isoformat()}:{bool(classifier)}"
    if use_cache:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return ThesisMonitoringResult.model_validate(cached)
    change_set = evidence.get_changes(user_id, thesis["ticker"], baseline_type="LAST_THESIS_REVIEW", current_as_of=now, include_low=True)
    bundle = evidence.load_history_bundle(thesis["ticker"], change_set.baseline_as_of - timedelta(days=730), now)
    current = evidence.observations_from_bundle(thesis["ticker"], bundle, now)
    assumptions = [_structured_assumption(item, change_set, current) if item.get("metric") else _qualitative_item(item, change_set, classifier) for item in thesis.get("assumptions", [])]
    factors = [_factor_result(item, thesis["ticker"], change_set, current, bundle, classifier) for item in thesis.get("factors", [])]
    risks = [item for item in factors if item.factor_type == "RISK"]
    catalysts = [item for item in factors if item.factor_type == "CATALYST"]
    breakers = [item for item in factors if item.factor_type == "BREAKER"]
    status, review = overall_status(assumptions, breakers, risks)
    all_traces = [trace for item in assumptions for trace in item.evidence] + [trace for item in factors for trace in item.evidence]
    counts = Counter(item.state for item in assumptions)
    counts.update(item.state for item in factors)
    result = ThesisMonitoringResult(
        thesis_id=thesis_id, thesis_version=int(thesis["current_version"]), ticker=thesis["ticker"],
        baseline_review_at=change_set.baseline_as_of, evaluated_at=now, overall_status=status, requires_review=review,
        assumption_results=assumptions, risk_results=risks, catalyst_results=catalysts, thesis_breaker_results=breakers,
        evidence_coverage=change_set.coverage, freshness=_level([item.freshness for item in all_traces]),
        evidence_quality=_level([item.evidence_quality for item in all_traces]), counts=dict(counts),
        warnings=change_set.warnings, created_at=datetime.now(timezone.utc),
    )
    _CACHE.put(cache_key, result.model_dump(mode="json"), ttl_seconds=DEFAULT_POLICY.cache_seconds)
    return result


def _connect():
    return database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()


def mark_reviewed(user_id: str, thesis_id: str, result: ThesisMonitoringResult | None = None) -> dict[str, Any]:
    thesis = theses.get_thesis(user_id, thesis_id)
    monitored = result or evaluate_thesis(user_id, thesis_id)
    review_id, reviewed_at = str(uuid.uuid4()), datetime.now(timezone.utc)
    postgres = bool(database.DATABASE_URL)
    p, prefix = ("%s", "public.") if postgres else ("?", "")
    result_col = "monitoring_result" if postgres else "monitoring_result_json"
    baseline_value = monitored.baseline_review_at if postgres else monitored.baseline_review_at.isoformat()
    evaluated_value = monitored.evaluated_at if postgres else monitored.evaluated_at.isoformat()
    reviewed_value = reviewed_at if postgres else reviewed_at.isoformat()
    with _connect() as conn:
        conn.execute(
            f"""INSERT INTO {prefix}thesis_review_events
            (id,user_id,thesis_id,thesis_version,ticker,baseline_review_at,evaluated_at,reviewed_at,overall_status,requires_review,{result_col},calculation_version,created_at)
            VALUES ({','.join([p] * 13)})""",
            (review_id, user_id, thesis_id, monitored.thesis_version, thesis["ticker"], baseline_value,
             evaluated_value, reviewed_value, monitored.overall_status, monitored.requires_review if postgres else int(monitored.requires_review),
             database._jsonb(monitored.model_dump(mode="json")) if postgres else json.dumps(monitored.model_dump(mode="json")),
             monitored.calculation_version, reviewed_value),
        )
    evidence.capture_snapshot(user_id, thesis["ticker"], "LAST_THESIS_REVIEW", review_id, reviewed_at)
    return {"id": review_id, "thesis_id": thesis_id, "reviewed_at": reviewed_at.isoformat(), "overall_status": monitored.overall_status,
            "next_baseline": "LAST_THESIS_REVIEW", "monitoring_result": monitored.model_dump(mode="json")}


def review_history(user_id: str, thesis_id: str) -> list[dict[str, Any]]:
    theses.get_thesis(user_id, thesis_id)
    postgres = bool(database.DATABASE_URL)
    p, prefix = ("%s", "public.") if postgres else ("?", "")
    column = "monitoring_result" if postgres else "monitoring_result_json"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id,thesis_version,baseline_review_at,evaluated_at,reviewed_at,overall_status,requires_review,{column},calculation_version,created_at FROM {prefix}thesis_review_events WHERE user_id={p} AND thesis_id={p} ORDER BY reviewed_at DESC",
            (user_id, thesis_id),
        ).fetchall()
    result = []
    for row in rows:
        value = dict(row)
        raw = value.pop(column)
        value["monitoring_result"] = json.loads(raw) if isinstance(raw, str) else raw
        result.append({key: evidence._plain(item) for key, item in value.items()})
    return result


def latest_summaries(user_id: str, thesis_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not thesis_ids:
        return {}
    postgres = bool(database.DATABASE_URL)
    p, prefix = ("%s", "public.") if postgres else ("?", "")
    placeholders = ",".join([p] * len(thesis_ids))
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT thesis_id,overall_status,requires_review,reviewed_at,monitoring_result FROM (
            SELECT thesis_id,overall_status,requires_review,reviewed_at,{('monitoring_result' if postgres else 'monitoring_result_json')} AS monitoring_result,
            row_number() OVER (PARTITION BY thesis_id ORDER BY reviewed_at DESC) AS position
            FROM {prefix}thesis_review_events WHERE user_id={p} AND thesis_id IN ({placeholders})
            ) ranked WHERE position=1""", (user_id, *thesis_ids),
        ).fetchall()
    return {str(row["thesis_id"]): {"overall_status": row["overall_status"], "requires_review": bool(row["requires_review"]),
        "reviewed_at": evidence._plain(row["reviewed_at"]), "counts": ((json.loads(row["monitoring_result"]) if isinstance(row["monitoring_result"], str) else row["monitoring_result"]) or {}).get("counts", {})} for row in rows}


def latest_results(user_id: str, thesis_ids: list[str]) -> list[dict[str, Any]]:
    """Load latest precomputed monitor results in one bounded owner-scoped query."""
    if not thesis_ids:
        return []
    postgres = bool(database.DATABASE_URL)
    p, prefix = ("%s", "public.") if postgres else ("?", "")
    placeholders = ",".join([p] * len(thesis_ids))
    column = "monitoring_result" if postgres else "monitoring_result_json"
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {column} FROM (
            SELECT {column},thesis_id,
            row_number() OVER (PARTITION BY thesis_id ORDER BY reviewed_at DESC) AS position
            FROM {prefix}thesis_review_events WHERE user_id={p} AND thesis_id IN ({placeholders})
            ) ranked WHERE position=1""", (user_id, *thesis_ids),
        ).fetchall()
    results = []
    for row in rows:
        raw = row[column]
        results.append(json.loads(raw) if isinstance(raw, str) else raw)
    return results
