from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .analytical_contract import canonical_data
from .ask_runtime import PortfolioContext


class DependencyClass(StrEnum):
    ALWAYS_AVAILABLE_SYSTEM_DATA = "ALWAYS_AVAILABLE_SYSTEM_DATA"
    ON_DEMAND_COMPUTATION = "ON_DEMAND_COMPUTATION"
    USER_REQUIRED_CONTEXT = "USER_REQUIRED_CONTEXT"


class DataHealthStatus(StrEnum):
    CURRENT = "CURRENT"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    MISSING = "MISSING"
    FAILED = "FAILED"


class DataHealthDomain(BaseModel):
    domain: str
    status: DataHealthStatus
    coverage: float | None = None
    freshness: str | None = None
    last_successful_update: str | None = None
    failure_reason: str | None = None
    repair_action: str | None = None


class SupportedClaim(BaseModel):
    claim: str
    scope: str = "objective"
    evidence_ids: list[str] = Field(default_factory=list)


class RequirementResolution(BaseModel):
    claims_requested: list[str] = Field(default_factory=list)
    evidence_available: list[str] = Field(default_factory=list)
    stale_or_missing_system_data: list[str] = Field(default_factory=list)
    automatically_creatable_computation: list[str] = Field(default_factory=list)
    user_required_missing_context: list[str] = Field(default_factory=list)
    jobs_or_actions: list[dict[str, Any]] = Field(default_factory=list)
    fallback_capabilities: list[str] = Field(default_factory=list)


class SupportedAnswer(BaseModel):
    direct_answer: str
    supported_claims: list[SupportedClaim] = Field(default_factory=list)
    partial_claims: list[SupportedClaim] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    pending_claims: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    jobs_started: list[dict[str, Any]] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    user_input_needed: list[str] = Field(default_factory=list)
    confidence: str = "LOW"
    coverage: dict[str, Any] = Field(default_factory=dict)


DEPENDENCY_MATRIX: dict[str, DependencyClass] = {
    "prices": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "price_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "fundamentals": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "fundamental_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "classifications": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "earnings_events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "macro_events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "company_catalysts": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "prediction_market_events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "macro": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "market": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "prediction_markets": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "portfolio_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "score_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "cash_hurdle": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "simulation": DependencyClass.ON_DEMAND_COMPUTATION,
    "optimization": DependencyClass.ON_DEMAND_COMPUTATION,
    "backtest": DependencyClass.ON_DEMAND_COMPUTATION,
    "deep_research": DependencyClass.ON_DEMAND_COMPUTATION,
    "saved_thesis": DependencyClass.USER_REQUIRED_CONTEXT,
    "thesis_breakers": DependencyClass.USER_REQUIRED_CONTEXT,
    "tax_lots": DependencyClass.USER_REQUIRED_CONTEXT,
    "custom_constraints": DependencyClass.USER_REQUIRED_CONTEXT,
}


_REQUESTED_CLAIMS = {
    "OPPORTUNITY_RANKING": ["eligible opportunity ranking", "supporting evidence"],
    "THESIS_REPLACEMENT": ["personal weakest thesis", "objective weakest setup", "replacement evidence"],
    "PORTFOLIO_CHANGE": ["material change since compatible baseline"],
    "VALUATION_RANKING": ["relative valuation burden"],
    "HIDDEN_RISK": ["position, sector, theme, and correlation concentration"],
    "MULTI_SCENARIO": ["scenario loss/wealth estimate", "immediate exposure mapping"],
    "WATCHLIST_COMPARISON": ["candidate versus incumbent dominance"],
    "PORTFOLIO_EVENTS": ["upcoming portfolio events by category"],
    "DATA_QUALITY": ["field-level ranking reliability"],
    "SCORE_ATTRIBUTION": ["score delta attribution"],
    "THESIS_INVALIDATION": ["personal thesis breakers", "objective holding risks"],
    "PORTFOLIO_ANALYSIS": ["actionable rebalance", "current objective portfolio issues"],
    "MULTIFACTOR_SCREEN": ["full matches", "strongest near matches"],
    "RECOMMENDATION_COUNTERCASE": ["countercase to a verified recommendation"],
    "CASH_ALLOCATION": ["candidate evidence versus a sourced cash hurdle"],
}


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _summaries(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [data for row in tool_results if isinstance((data := canonical_data(row) or {}), dict)]


def _first_summary(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    return next(iter(_summaries(tool_results)), {})


def _job_rows(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"job_id": row.get("job_id"), "capability": row.get("tool_name"), "status": row.get("status")}
            for row in tool_results if row.get("job_id")]


def resolve_requirements(
    *, intent: str, question: str, context: PortfolioContext | None,
    tool_results: list[dict[str, Any]], data_health: list[DataHealthDomain] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> RequirementResolution:
    del question, context, conversation_context
    resolution = RequirementResolution(claims_requested=_REQUESTED_CLAIMS.get(intent, [intent.lower().replace("_", " ")]))
    for row in tool_results:
        canonical = row.get("analysis_result") or {}
        capability = str(canonical.get("capability") or row.get("tool_name") or "analysis")
        if str(row.get("status") or "").lower() in {"complete", "success", "partial"}:
            resolution.evidence_available.append(capability)
        for prerequisite in canonical.get("prerequisites") or []:
            if prerequisite.get("satisfied"):
                continue
            name = str(prerequisite.get("name") or "")
            normalized = ("saved_thesis" if "thesis" in name else "tax_lots" if "tax_lot" in name else
                          "simulation" if "scenario" in name else "optimization" if "optimizer" in name else
                          "cash_hurdle" if "cash_hurdle" in name else "portfolio_history" if "historical" in name else name)
            dependency_class = DEPENDENCY_MATRIX.get(normalized, DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA)
            reason = str(prerequisite.get("reason") or normalized.replace("_", " "))
            if dependency_class == DependencyClass.USER_REQUIRED_CONTEXT:
                resolution.user_required_missing_context.append(reason)
            elif dependency_class == DependencyClass.ON_DEMAND_COMPUTATION:
                resolution.automatically_creatable_computation.append(normalized)
            else:
                resolution.stale_or_missing_system_data.append(reason)
    resolution.jobs_or_actions = _job_rows(tool_results)
    for item in data_health or []:
        if item.status != DataHealthStatus.CURRENT:
            resolution.stale_or_missing_system_data.append(
                f"{item.domain}: {item.status.value.lower()}" + (f" ({item.failure_reason})" if item.failure_reason else "")
            )
    fallback = {
        "OPPORTUNITY_RANKING": ["near_match_factor_evidence"],
        "THESIS_REPLACEMENT": ["objective_holding_evidence", "watchlist_dominance"],
        "PORTFOLIO_CHANGE": ["current_portfolio_snapshot"],
        "VALUATION_RANKING": ["partial_relative_valuation"],
        "MULTI_SCENARIO": ["portfolio_exposure_mapping"],
        "THESIS_INVALIDATION": ["objective_risk_evidence"],
        "PORTFOLIO_ANALYSIS": ["concentration_and_risk_diagnostics"],
        "MULTIFACTOR_SCREEN": ["near_match_factor_evidence"],
        "CASH_ALLOCATION": ["candidate_evidence_without_cash_superiority_claim"],
    }
    resolution.fallback_capabilities = fallback.get(intent, [])
    resolution.evidence_available = list(dict.fromkeys(resolution.evidence_available))
    resolution.stale_or_missing_system_data = list(dict.fromkeys(resolution.stale_or_missing_system_data))
    resolution.user_required_missing_context = list(dict.fromkeys(resolution.user_required_missing_context))
    return resolution


def _failed_gates(row: dict[str, Any]) -> list[str]:
    eligibility = row.get("eligibility") or {}
    missing = list(eligibility.get("missing_fields") or row.get("missing_fields") or [])
    placeholders = [f"placeholder {value}" for value in eligibility.get("placeholder_fields") or []]
    return [*missing, *placeholders]


def _near_score(row: dict[str, Any], keys: tuple[str, ...]) -> float:
    values = [_num(row.get(key)) for key in keys]
    observed = [value for value in values if value is not None]
    return sum(observed) / len(observed) if observed else -1


def _holding_line(row: dict[str, Any]) -> str:
    fields = []
    for key, label in (("health_score", "health"), ("fundamental_score", "fundamentals"),
                       ("valuation_score", "valuation"), ("momentum_score", "momentum")):
        if (value := _num(row.get(key))) is not None:
            fields.append(f"{label} {value:.1f}")
    weight = _num(row.get("weight"))
    if weight is not None:
        fields.append(f"weight {weight:.1%}")
    return f"**{row.get('ticker')}** — " + (", ".join(fields) or "limited stored factor evidence")


def compose_supported_answer(
    *, intent: str, question: str, context: PortfolioContext | None,
    tool_results: list[dict[str, Any]], deterministic_answer: str | None,
    data_health: list[DataHealthDomain] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> tuple[RequirementResolution, SupportedAnswer]:
    resolution = resolve_requirements(intent=intent, question=question, context=context, tool_results=tool_results,
                                      data_health=data_health, conversation_context=conversation_context)
    summary = _first_summary(tool_results)
    jobs = resolution.jobs_or_actions
    gaps = resolution.stale_or_missing_system_data
    user_gaps = resolution.user_required_missing_context
    answer = deterministic_answer or "The requested claim is not supported by the currently validated evidence."
    supported: list[SupportedClaim] = []
    partial: list[SupportedClaim] = []
    unsupported: list[str] = []
    pending = [str(row.get("capability") or "calculation") for row in jobs]

    if intent == "OPPORTUNITY_RANKING" and not summary.get("candidates"):
        rows = sorted(summary.get("ineligible_candidates") or [],
                      key=lambda row: _near_score(row, ("fundamental_quality", "valuation", "momentum", "portfolio_fit")), reverse=True)[:3]
        body = []
        for row in rows:
            gates = _failed_gates(row)
            body.append(_holding_line({"ticker": row.get("ticker"), "fundamental_score": row.get("fundamental_quality"),
                                      "valuation_score": row.get("valuation"), "momentum_score": row.get("momentum")})
                        + f". Failed gates: {', '.join(gates) or 'full opportunity score unavailable'}."
                        + (f" Supported signals: {'; '.join(row.get('supporting_evidence') or [])}." if row.get("supporting_evidence") else ""))
        answer = "No holding passes every opportunity gate, so none is labeled fully eligible. The strongest partial setups are:\n\n" + "\n\n".join(body or ["No holding has enough observed factor evidence for a near-match comparison."])
        partial.append(SupportedClaim(claim="Strongest partial setups shown with their failed eligibility gates."))
        unsupported.append("A fully eligible opportunity ranking")
    elif intent == "THESIS_REPLACEMENT" and not (summary.get("thesis") or {}).get("exists"):
        weak = sorted(summary.get("weakest_evidence_holdings") or summary.get("weakest_holdings") or [],
                      key=lambda row: _num(row.get("health_score")) if _num(row.get("health_score")) is not None else 999)[:5]
        candidates = summary.get("dominance_results") or []
        candidate_text = "\n".join(
            f"- **{row.get('candidate')}** — {str(row.get('dominance_status') or 'not proven').replace('_', ' ').lower()}; decision score {_num(row.get('decision_score')):.1f}."
            for row in candidates[:3] if _num(row.get("decision_score")) is not None
        )
        answer = "I cannot rank your personal theses because none are saved. Based only on objective stored evidence, the weakest current setups are:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in weak)
        if candidate_text:
            answer += "\n\nWatchlist evidence (not a forced replacement):\n" + candidate_text
        answer += "\n\nSave a thesis and its breakers to make the replacement claim personal."
        supported.append(SupportedClaim(claim="Objective weakest-evidence holdings", scope="objective"))
        unsupported.append("Personal weakest-thesis ranking and personalized replacement")
    elif intent == "PORTFOLIO_CHANGE" and not (summary.get("historical_snapshot") or {}).get("exists"):
        current = sorted(summary.get("all_holdings") or [], key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:5]
        answer = "There is no compatible prior snapshot, so I cannot truthfully say what changed since the last review. The current baseline is:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in current)
        answer += "\n\nThis snapshot is the durable comparison point for future reviews; it is not presented as a past review."
        supported.append(SupportedClaim(claim="Current portfolio baseline"))
        unsupported.append("Change since last review")
    elif intent == "VALUATION_RANKING" and not summary.get("positions"):
        rows = [row for row in summary.get("all_relative_valuation") or [] if any(value is not None for value in (row.get("inputs") or {}).values())][:8]
        body = []
        for row in rows:
            inputs = row.get("inputs") or {}
            observed = ", ".join(f"{key.replace('_', ' ')} {value:.2f}" for key, raw in inputs.items() if (value := _num(raw)) is not None)
            body.append(f"- **{row.get('ticker')}** — {observed or 'no raw valuation input'}; missing gates: {', '.join(_failed_gates(row)) or 'relative comparison inputs'}."
                        )
        answer = "No position qualifies for the full relative-valuation ranking. These are the strongest partial comparisons, without labeling them overvalued:\n\n" + "\n".join(body or ["- No position has any usable raw valuation input."])
        partial.append(SupportedClaim(claim="Partial valuation evidence with failed gates"))
        unsupported.append("Full relative overvaluation ranking")
    elif intent == "MULTI_SCENARIO" and not summary.get("latest_simulation"):
        rows = sorted(summary.get("all_holdings") or [],
                      key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:8]
        factors = summary.get("scenario_factors") or []
        factor_text = ", ".join(
            f"{str(row.get('factor') or 'factor').replace('_', ' ')} {row.get('direction') or ''}".strip()
            for row in factors
        ) or "the requested factors"
        mapped = summary.get("supported_scenario_factors") or []
        mapped_text = "\n".join(
            f"- **{str(row.get('factor') or 'factor').replace('_', ' ').title()}** — "
            f"{_num(row.get('mapped_portfolio_weight')):.1%} mapped weight across "
            f"{', '.join(row.get('affected_holdings') or []) or 'covered holdings'}; "
            f"{str(row.get('support_type') or 'exposure mapping').replace('_', ' ').lower()}."
            for row in mapped if _num(row.get("mapped_portfolio_weight")) is not None
        )
        answer = (
            f"A compatible simulation for **{factor_text}** is not cached yet, so I cannot state a loss, drawdown, "
            "or terminal-wealth estimate. The canonical simulation job has been queued.\n\n"
            "**Current exposure starting point**\n\n" +
            "\n".join(f"- {_holding_line(row)}" for row in rows)
        )
        if mapped_text:
            answer += "\n\n**Available deterministic factor mapping**\n\n" + mapped_text
        answer += "\n\nThese weights and mappings show where a shock could enter the portfolio; they are not a modeled loss estimate."
        supported.append(SupportedClaim(claim="Current portfolio exposure and supported factor mapping"))
        pending.append("compatible multi-factor simulation")
        unsupported.append("Scenario loss, drawdown, and wealth estimates before simulation completion")
    elif intent == "DATA_QUALITY":
        rows = summary.get("positions") or []
        checks = sorted({key for row in rows for key in (row.get("eligibility") or {}).get("required_checks", {})})
        counts = {
            check: sum(bool((row.get("eligibility") or {}).get("required_checks", {}).get(check)) for row in rows)
            for check in checks
        }
        coverage_lines = []
        for check in checks:
            coverage_lines.append(f"- **{check.replace('_', ' ').title()}**: {counts[check]}/{len(rows)} holdings")
        rankable = sum(bool(row.get("rankable")) for row in rows)
        momentum_count = counts.get("momentum_history", counts.get("momentum", 0))
        domain_lines = [
            f"- **Prices and price history**: {min(counts.get('price_freshness', 0), momentum_count)}/{len(rows)} holdings",
            f"- **Fundamentals and history**: {min(counts.get('fundamental_freshness', 0), counts.get('fundamental_history', 0))}/{len(rows)} holdings",
            f"- **Momentum inputs**: {momentum_count}/{len(rows)} holdings",
            f"- **Ranking eligibility**: {rankable}/{len(rows)} holdings",
            "- **Full opportunity eligibility**: not independently counted by this data-quality read model.",
            "- **Classifications and valuation inputs**: not independently counted by this read model; they remain separate data-health domains and are not inferred from symbol presence.",
        ]
        holding_lines = []
        for row in rows:
            missing = _failed_gates(row)
            if missing or row.get("trust_classification") != "HIGH":
                holding_lines.append(f"- **{row.get('ticker')}** — {row.get('trust_classification')}; missing: {', '.join(missing) or 'no required field, but confidence remains below high'}."
                                     )
        answer = "Ranking reliability is field-specific; it is not a single all-or-nothing coverage number.\n\n**Decision-domain coverage**\n\n" + "\n".join(domain_lines)
        answer += "\n\n**Methodology checks**\n\n" + "\n".join(coverage_lines or ["- Field coverage is not present in the current read model."])
        answer += "\n\n**Holdings needing attention**\n\n" + "\n".join(holding_lines[:20] or ["- No lower-confidence holding is recorded."])
        supported.append(SupportedClaim(claim="Field-level and per-holding data quality"))
    elif intent == "SCORE_ATTRIBUTION" and not summary.get("holding"):
        answer = (
            "Name a holding (for example, `MSFT`) or open that holding's research page before asking why its score changed. "
            "Score attribution requires one company plus a compatible prior score snapshot; no company-specific explanation was generated."
        )
        user_gaps.append("A holding ticker")
        unsupported.append("Score attribution without a named holding")
    elif intent == "THESIS_INVALIDATION" and not (summary.get("thesis") or {}).get("exists"):
        rows = summary.get("largest_positions") or []
        body = []
        for row in rows:
            risks = []
            if (_num(row.get("risk_contribution")) or 0) >= .05:
                risks.append(f"modeled risk contribution {_num(row.get('risk_contribution')):.1%}")
            if (_num(row.get("valuation_score")) or 100) < 45:
                risks.append(f"weak valuation evidence {_num(row.get('valuation_score')):.0f}/100")
            if (_num(row.get("momentum_score")) or 100) < 45:
                risks.append(f"weak momentum evidence {_num(row.get('momentum_score')):.0f}/100")
            body.append(f"- **{row.get('ticker')}** — {', '.join(risks) or 'no objective breaker-like risk crossed the stored thresholds'}."
                        )
        answer = "No saved theses or personal breakers exist, so I cannot claim what would invalidate your thesis. These are objective, non-personalized risks for the largest positions:\n\n" + "\n".join(body)
        supported.append(SupportedClaim(claim="Objective risks for largest positions", scope="objective"))
        unsupported.append("Personal thesis invalidation conditions")
    elif intent == "PORTFOLIO_ANALYSIS" and not summary.get("optimizer_run"):
        rows = sorted(summary.get("all_holdings") or [], key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:8]
        answer = "A compatible optimizer job has been queued. While it runs, the current objective concentration starting point is:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in rows)
        answer += "\n\nI cannot make tax-aware trade claims without tax lots, and exact turnover/cost claims remain pending with the optimizer."
        supported.append(SupportedClaim(claim="Current position concentration"))
        pending.append("compatible optimization")
        unsupported.append("Tax-aware trades without tax lots")
    elif intent == "MULTIFACTOR_SCREEN" and not summary.get("positions"):
        rows = sorted(summary.get("near_matches") or summary.get("all_holdings") or [],
                      key=lambda row: _near_score(row, ("fundamental_score", "valuation_score", "momentum_score")), reverse=True)[:10]
        body = []
        for row in rows:
            failed = list(row.get("failed_criteria") or [])
            if not failed:
                trend = ((row.get("fundamental_trend") or {}).get("direction") or "UNAVAILABLE")
                if trend != "IMPROVING": failed.append(f"fundamental trend is {trend.lower()}")
                if (_num(row.get("valuation_score")) or 0) <= 0: failed.append("valuation unavailable")
                if (_num(row.get("momentum_score")) or 0) < 50: failed.append("momentum is not positive")
            body.append(f"- {_holding_line(row)}. Failed criteria: {', '.join(failed) or 'full historical eligibility'}.")
        answer = "No company passes all multifactor gates. The strongest near-matches are:\n\n" + "\n".join(body or ["- No company has enough factor evidence for a near-match."])
        partial.append(SupportedClaim(claim="Multifactor near matches with failed criteria"))
        unsupported.append("Full multifactor eligibility")
    elif intent == "RECOMMENDATION_COUNTERCASE" and not (summary.get("countercase") or {}).get("ticker"):
        candidates = summary.get("top_candidate") or []
        answer = "There is no current verified EagleEyes recommendation, so there is no recommendation-specific countercase to audit."
        if candidates:
            answer += "\n\nThe strongest current holding by stored health evidence is not a recommendation: " + _holding_line(candidates[0]) + "."
        unsupported.append("Countercase to a nonexistent recommendation")
    elif intent == "CASH_ALLOCATION":
        cash = summary.get("cash_allocation") or {}
        hurdle = cash.get("cash_hurdle") or {}
        if not hurdle.get("available"):
            candidates = cash.get("candidates") or summary.get("dominance_results") or []
            body = "\n".join(f"- **{row.get('candidate')}** — {str(row.get('dominance_status') or 'not proven').replace('_', ' ').lower()}; decision score {_num(row.get('decision_score')):.1f}."
                                for row in candidates[:5] if _num(row.get("decision_score")) is not None)
            answer = "The sourced cash hurdle is missing, so I cannot claim that investing beats cash. Current candidate evidence is:\n\n" + (body or "- No candidate has sufficient verified comparison evidence.")
            partial.append(SupportedClaim(claim="Candidate evidence without a cash-superiority claim"))
            unsupported.append("Investing is better than cash")
    elif deterministic_answer:
        supported.append(SupportedClaim(claim="Deterministic capability answer"))

    coverage = next((row.get("coverage") for row in tool_results if isinstance(row.get("coverage"), dict)), {})
    return resolution, SupportedAnswer(
        direct_answer=answer, supported_claims=supported, partial_claims=partial,
        unsupported_claims=list(dict.fromkeys(unsupported)), pending_claims=list(dict.fromkeys(pending)),
        evidence=resolution.evidence_available, jobs_started=jobs, data_gaps=gaps,
        user_input_needed=user_gaps, confidence="HIGH" if supported and not partial else "MEDIUM" if supported or partial else "LOW",
        coverage=coverage or {},
    )
