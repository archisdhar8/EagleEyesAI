from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import database, phase4_analytics, read_models, theses
from .analytical_contract import (
    AnalysisResult, AnalysisStatus, Coverage, DependencyResult, LineageItem, Prerequisite,
    VerificationCheck, VerificationResult, VerificationSeverity, build_entity_coverage,
    build_freshness, canonical_data, parse_timestamp, with_canonical_result,
)
from .ask_runtime import PortfolioContext, classify_candidate, parse_scenario_factors


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _selected_portfolio(user_id: str, portfolio_id: str | None) -> dict[str, Any]:
    if not portfolio_id:
        raise ValueError("Select a portfolio before asking a portfolio-specific question.")
    return database.get_portfolio(portfolio_id, user_id)


def _overview(user_id: str, portfolio_id: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        row = database.latest_portfolio_health(user_id, portfolio_id)
    except Exception as exc:
        return None, f"Portfolio health storage is not ready ({type(exc).__name__}). Apply the portfolio-health migration and backfill a snapshot."
    return (dict(row.get("result") or {}) if row else None), None


def _briefing(user_id: str) -> dict[str, Any]:
    try:
        return database.latest_briefing_snapshot(user_id) or {}
    except Exception:
        return {}


def _evidence(tool: str, portfolio: dict[str, Any], summary: dict[str, Any], as_of: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    status = "complete" if summary.get("status") != "unavailable" else "unavailable"
    result = {"tool_name": tool, "status": status, "title": summary.get("title") or tool.replace("_", " ").title(),
              "summary": summary, "as_of": as_of or portfolio.get("updated_at")}
    grounded = [] if status == "unavailable" else [{
        "label": summary.get("title") or result["title"], "as_of": as_of or portfolio.get("updated_at"),
        "url": None, "data": summary, "claim_type": "MODEL_OUTPUT",
    }]
    return [result], grounded


_CALCULATION_VERSIONS = {
    "portfolio_overview": "opportunity-v2",
    "thesis_replacement": "replacement-v2",
    "portfolio_change": "portfolio-change-v2",
    "valuation_ranking": "relative-valuation-v2",
    "portfolio_intelligence": "portfolio-intelligence-v1",
    "portfolio_scenario": "scenario-compatibility-v2",
    "watchlist_comparison": "watchlist-dominance-v2",
    "portfolio_events": "portfolio-events-v3",
    "data_quality": "data-quality-v2",
    "score_attribution": "score-attribution-v2",
    "thesis_monitor": "thesis-invalidation-v2",
    "multifactor_screen": "fundamental-trend-screen-v2",
    "recommendation_countercase": "countercase-v2",
    "cash_allocation": "cash-allocation-v2",
    "portfolio_analysis": "rebalance-actionability-v2",
}


def _required_freshness_inputs(tool: str, summary: dict[str, Any], as_of: str | None) -> list[tuple[str, Any]]:
    """Name required inputs without treating every historical observation as a current dependency."""
    dates: list[tuple[str, Any]] = [("portfolio_health_snapshot", as_of)] if as_of else []
    if tool in {"watchlist_comparison", "cash_allocation", "thesis_replacement"}:
        for row in summary.get("all_watchlist_rows") or summary.get("watchlist_candidates") or []:
            timestamp = row.get("as_of") or row.get("updated_at") or row.get("calculated_at")
            if timestamp:
                dates.append((f"watchlist:{row.get('ticker') or 'unknown'}", timestamp))
    elif tool == "portfolio_scenario":
        simulation = summary.get("latest_simulation") or {}
        if simulation.get("created_at"):
            dates.append(("scenario_run", simulation["created_at"]))
    elif tool == "portfolio_analysis":
        optimizer = summary.get("optimizer_run") or {}
        if optimizer.get("created_at"):
            dates.append(("optimizer_run", optimizer["created_at"]))
    elif tool == "thesis_monitor":
        for row in summary.get("saved_theses") or []:
            timestamp = row.get("updated_at") or row.get("created_at")
            if timestamp:
                dates.append((f"thesis:{row.get('ticker') or row.get('id') or 'unknown'}", timestamp))
    return dates


def _coverage_for(tool: str, summary: dict[str, Any], context: PortfolioContext | None) -> Coverage:
    if tool == "score_attribution":
        row = summary.get("holding") or {}
        requested = [str(row.get("ticker") or "").upper()] if row else []
        return build_entity_coverage(
            requested, [row] if row else [],
            ["current_score", "previous_score", "total_delta", "component_deltas", "comparable_baseline"],
            weights=context.normalized_weights if context else None,
        )
    if tool in {"watchlist_comparison", "thesis_replacement", "cash_allocation"}:
        rows = list(summary.get("all_watchlist_rows") or summary.get("watchlist_candidates") or [])
        requested = [str(row.get("ticker") or "").upper() for row in rows]
        return build_entity_coverage(
            requested, rows,
            ["fundamental_score", "valuation_score", "technical_score", "confidence", "candidate_type"],
        )
    if tool == "portfolio_events":
        return Coverage(methodology=(
            "Per-holding event-calendar coverage is not tracked by the current read model; an empty list is not full coverage."
        ))
    if tool == "portfolio_change":
        return Coverage(methodology=(
            "Portfolio change is evaluated against a compatible portfolio-level baseline; zero material changes is a valid result, not zero holding coverage."
        ))
    if tool in {"portfolio_scenario", "portfolio_analysis"}:
        return Coverage(methodology=(
            "Per-holding analytical coverage is not tracked by the current cached simulation/optimizer read model."
        ))
    requested = list(context.symbols) if context else []
    rows = list(summary.get("all_holdings") or summary.get("positions") or [])
    if tool == "portfolio_overview":
        rows = list(summary.get("candidates") or []) + list(summary.get("ineligible_candidates") or [])
    elif tool == "valuation_ranking":
        rows = list(summary.get("all_relative_valuation") or summary.get("positions") or [])
    elif tool in {"data_quality", "multifactor_screen"}:
        rows = list(summary.get("positions") or [])
    if tool in {"portfolio_overview", "valuation_ranking", "multifactor_screen"}:
        requested = [str(row.get("ticker") or "").upper() for row in rows if row.get("ticker")]
    required = {
        "portfolio_overview": ["ticker", "opportunity_score", "eligibility"],
        "portfolio_change": ["domain", "materiality", "reason"],
        "valuation_ranking": ["ticker", "relative_value_gap", "eligibility"],
        "data_quality": ["ticker", "trust_classification", "rankable", "eligibility"],
        "multifactor_screen": ["ticker", "fundamental_score", "valuation_score", "momentum_score", "fundamental_trend"],
        "portfolio_intelligence": ["health_score", "risk_contribution"],
        "recommendation_countercase": ["health_score", "risk_contribution"],
    }.get(tool, [])
    if tool == "thesis_monitor":
        rows = list(summary.get("saved_theses") or [])
        required = ["ticker", "summary"]
    return build_entity_coverage(requested, rows, required, weights=context.normalized_weights if context else None)


def _canonical_result(
    tool: str, portfolio: dict[str, Any], summary: dict[str, Any], as_of: str | None,
    context: PortfolioContext | None, read_model_info: dict[str, Any] | None = None,
) -> AnalysisResult:
    coverage = _coverage_for(tool, summary, context)
    prerequisites: list[Prerequisite] = []
    if tool in {"thesis_replacement", "thesis_monitor"}:
        exists = bool((summary.get("thesis") or {}).get("exists") or summary.get("saved_theses"))
        prerequisites.append(Prerequisite(
            name="saved_thesis_exists", satisfied=exists,
            reason="At least one saved thesis is available." if exists else "No saved thesis exists for the selected portfolio.",
        ))
    if tool == "portfolio_change":
        exists = bool((summary.get("historical_snapshot") or {}).get("exists"))
        prerequisites.append(Prerequisite(
            name="historical_baseline_exists", satisfied=exists,
            reason="A previous portfolio snapshot is available." if exists else "No previous historical snapshot is available.",
        ))
    if tool == "score_attribution":
        exists = bool((summary.get("holding") or {}).get("comparable_baseline"))
        prerequisites.append(Prerequisite(
            name="score_change_baseline_exists", satisfied=exists,
            reason="A component-level score-change baseline is available." if exists else "No component-level score-change baseline is available.",
        ))
    if tool == "portfolio_scenario":
        exists = bool(summary.get("latest_simulation"))
        prerequisites.append(Prerequisite(
            name="matching_scenario_run_exists", satisfied=exists,
            reason="A cached simulation exists; exact factor compatibility is verified separately." if exists else "No cached portfolio simulation exists.",
        ))
    if tool in {"watchlist_comparison", "cash_allocation", "thesis_replacement"}:
        populated = bool(summary.get("all_watchlist_rows") or summary.get("watchlist_candidates"))
        prerequisites.append(Prerequisite(
            name="watchlist_populated", satisfied=populated,
            reason="Stored watchlist research is available." if populated else "No stored watchlist research is available.",
        ))
    if tool == "cash_allocation":
        hurdle = summary.get("cash_allocation", {}).get("cash_hurdle") or summary.get("cash_hurdle") or {}
        prerequisites.append(Prerequisite(
            name="cash_hurdle_available", satisfied=bool(hurdle.get("available")),
            reason="A supported cash hurdle is available." if hurdle.get("available") else
            "No supported cash or risk-free yield is stored; EagleEyes cannot claim investing is better than cash.",
        ))
    if tool == "portfolio_analysis":
        exists = bool(summary.get("optimizer_run"))
        optimizer = summary.get("optimizer_run") or {}
        optimizer_fingerprint = optimizer.get("portfolio_context_version") or optimizer.get("input_fingerprint")
        compatible = bool(context and optimizer_fingerprint and optimizer_fingerprint == context.version)
        diagnostics = optimizer.get("model_diagnostics") or {}
        selected = next((row for row in optimizer.get("alternatives") or [] if row.get("name") == "Balanced"), None)
        constraint_status = str(
            (diagnostics.get("constraint_status") if isinstance(diagnostics, dict) else None)
            or (selected or {}).get("constraint_status") or optimizer.get("constraint_status") or ""
        ).lower()
        feasible = constraint_status in {"feasible", "satisfied", "optimal", "success"}
        prerequisites.extend([
            Prerequisite(
                name="optimizer_run_exists", satisfied=exists,
                reason="A saved optimizer run is available." if exists else "No saved optimizer run is available.",
            ),
            Prerequisite(
                name="optimizer_input_compatible", satisfied=compatible,
                reason=(
                    "The optimizer input fingerprint matches the current portfolio context."
                    if compatible else "The saved optimizer does not carry a matching current-portfolio input fingerprint."
                ),
            ),
            Prerequisite(
                name="optimizer_feasible", satisfied=feasible,
                reason=(
                    f"The saved optimizer reports a feasible constraint state ({constraint_status})."
                    if feasible else f"The saved optimizer feasibility state is not acceptable ({constraint_status or 'not tracked'})."
                ),
            ),
            Prerequisite(
                name="tax_lots_available", satisfied=False,
                reason="Tax-lot coverage is not tracked by the current cached optimizer result.",
            ),
            Prerequisite(
                name="trading_cost_model_available", satisfied=bool(optimizer.get("trading_cost_model") or optimizer.get("transaction_cost_assumptions")),
                reason=("A stored trading-cost model is available." if optimizer.get("trading_cost_model") or optimizer.get("transaction_cost_assumptions") else
                        "No stored trading-cost model is available; precise implementation costs cannot be claimed."),
            ),
            Prerequisite(
                name="turnover_assumptions_available", satisfied=bool(optimizer.get("turnover_assumptions") or any(
                    row.get("turnover") is not None for row in optimizer.get("alternatives") or []
                )), reason="Turnover is explicitly modeled." if optimizer.get("turnover_assumptions") or any(
                    row.get("turnover") is not None for row in optimizer.get("alternatives") or []
                ) else "Turnover assumptions are unavailable.",
            ),
        ])

    raw_unavailable = summary.get("status") == "unavailable"
    advisory_prerequisites = {"tax_lots_available", "cash_hurdle_available", "trading_cost_model_available", "turnover_assumptions_available"}
    missing_required_prerequisite = any(not item.satisfied for item in prerequisites if item.name not in advisory_prerequisites)
    missing_coverage = bool(
        coverage.requested_entities and coverage.evaluated_entities != coverage.requested_entities
    )
    dates = _required_freshness_inputs(tool, summary, as_of)
    freshness = build_freshness(dates)
    if read_model_info and read_model_info.get("freshness"):
        from .analytical_contract import Freshness
        freshness = Freshness.model_validate(read_model_info["freshness"])
    coverage_untracked = coverage.entity_coverage_percent is None and tool == "portfolio_events"
    status = AnalysisStatus.UNAVAILABLE if raw_unavailable or missing_required_prerequisite else (
        AnalysisStatus.PARTIAL if missing_coverage or freshness.stale is True or coverage_untracked else AnalysisStatus.SUCCESS
    )
    if summary.get("warnings") and status == AnalysisStatus.SUCCESS:
        status = AnalysisStatus.PARTIAL
    if tool == "cash_allocation" and any(not item.satisfied for item in prerequisites if item.name == "cash_hurdle_available"):
        status = AnalysisStatus.PARTIAL if status == AnalysisStatus.SUCCESS else status
    if tool == "portfolio_events" and not bool(summary.get("event_completeness", {}).get("complete")):
        status = AnalysisStatus.PARTIAL
    if read_model_info and read_model_info.get("state") == read_models.CompatibilityState.STALE:
        status = AnalysisStatus.PARTIAL if status == AnalysisStatus.SUCCESS else status
    checks = [
        VerificationCheck(
            name="required_entity_fields_available", passed=not missing_coverage,
            severity=VerificationSeverity.WARNING if missing_coverage else VerificationSeverity.INFO,
            message=(
                f"{len(coverage.evaluated_entities)} of {len(coverage.requested_entities)} requested entities have every required field."
                if coverage.requested_entities else "Entity-level coverage is not tracked for this capability."
            ),
        ),
        VerificationCheck(
            name="required_prerequisites_satisfied", passed=not missing_required_prerequisite,
            severity=VerificationSeverity.ERROR,
            message="Required prerequisites are satisfied." if not missing_required_prerequisite else "One or more required prerequisites are missing.",
        ),
    ]
    if tool == "portfolio_overview":
        candidates = summary.get("candidates") or []
        checks.append(VerificationCheck(
            name="opportunity_eligibility", passed=bool(candidates) and all(
                (row.get("eligibility") or {}).get("eligible") and row.get("opportunity_score") is not None
                for row in candidates
            ), severity=VerificationSeverity.ERROR,
            message="Every ranked opportunity passed raw-data eligibility." if candidates else
            "No security passed every opportunity eligibility gate.",
        ))
    elif tool == "valuation_ranking":
        positions = summary.get("positions") or []
        checks.append(VerificationCheck(
            name="relative_value_inputs", passed=bool(positions) and all(
                row.get("relative_value_gap") is not None and (row.get("eligibility") or {}).get("eligible")
                for row in positions
            ), severity=VerificationSeverity.ERROR,
            message="Eligible relative-value inputs are available." if positions else
            "No eligible relative-value comparison is available.",
        ))
    elif tool == "multifactor_screen":
        positions = summary.get("positions") or []
        checks.append(VerificationCheck(
            name="fundamental_trend_required", passed=bool(positions) and all(
                (row.get("fundamental_trend") or {}).get("direction") == "IMPROVING" for row in positions
            ), severity=VerificationSeverity.ERROR,
            message="Every screened company has a measured improving trend." if positions else
            "No company has sufficient evidence for an improving fundamental trend.",
        ))
    elif tool == "watchlist_comparison":
        checks.append(VerificationCheck(
            name="risk_adjusted_dominance_calculated", passed=bool(summary.get("dominance_results")),
            severity=VerificationSeverity.ERROR,
            message="Watchlist dominance includes risk and portfolio-fit evidence.",
        ))
    elif tool == "thesis_replacement":
        comparisons = summary.get("replacement_comparisons") or []
        checks.append(VerificationCheck(
            name="replacement_dominance", passed=any(
                row.get("replacement_dominance") == "REPLACEMENT_SUPPORTED" for row in comparisons
            ), severity=VerificationSeverity.ERROR,
            message=("At least one candidate proves replacement dominance." if comparisons else
                     "No incumbent-versus-candidate replacement comparison is available."),
        ))
    elif tool == "cash_allocation":
        checks.append(VerificationCheck(
            name="cash_hurdle", passed=bool((summary.get("cash_allocation") or {}).get("cash_hurdle", {}).get("available")),
            severity=VerificationSeverity.ERROR,
            message="A sourced cash hurdle is available." if (summary.get("cash_allocation") or {}).get("cash_hurdle", {}).get("available") else
            "No sourced cash hurdle is available; investing cannot be claimed superior to cash.",
        ))
    elif tool == "score_attribution":
        holding = summary.get("holding") or {}
        reconciles = holding.get("unexplained_delta") is not None and abs(_number(holding.get("unexplained_delta"))) <= .5
        checks.append(VerificationCheck(
            name="score_delta_reconciles", passed=bool(holding.get("comparable_baseline")) and reconciles,
            severity=VerificationSeverity.ERROR,
            message="Component impacts reconcile to the observed total delta." if reconciles else
            "Comparable component history is absent or does not reconcile to the total score delta.",
        ))
    elif tool == "portfolio_events":
        checks.append(VerificationCheck(
            name="event_category_completeness", passed=bool((summary.get("event_completeness") or {}).get("complete")),
            severity=VerificationSeverity.WARNING,
            message="Earnings, macro, and company-catalyst categories are covered." if (summary.get("event_completeness") or {}).get("complete") else
            "One or more event categories are incomplete.",
        ))
    elif tool == "data_quality":
        checks.append(VerificationCheck(
            name="ranking_eligibility_classified", passed=all(
                row.get("trust_classification") in {"HIGH", "MEDIUM", "LOW", "NOT_RANKABLE"}
                for row in summary.get("positions") or []
            ), severity=VerificationSeverity.ERROR,
            message="Every holding has a deterministic ranking-trust classification.",
        ))
    elif tool == "portfolio_analysis":
        decision = summary.get("rebalance_decision") or {}
        checks.extend([
            VerificationCheck(name="rebalance_fingerprint", passed=bool(decision.get("portfolio_fingerprint_match")),
                              severity=VerificationSeverity.ERROR, message=("Optimizer fingerprint matches the current portfolio." if decision.get("portfolio_fingerprint_match") else "Optimizer fingerprint does not match the current portfolio.")),
            VerificationCheck(name="rebalance_feasible", passed=bool(decision.get("actionable")),
                              severity=VerificationSeverity.ERROR, message=("A feasible compatible rebalance is actionable." if decision.get("actionable") else "No feasible compatible rebalance is actionable.")),
            VerificationCheck(name="tax_capability_labeled", passed=bool(decision.get("tax_aware")) == bool(decision.get("tax_data_available")),
                              severity=VerificationSeverity.ERROR, message="Tax-aware status matches tax-lot availability."),
        ])
    lineage = [
        LineageItem(
            domain="portfolio", dataset="portfolio_holdings", provider="user_saved",
            source_version=context.version if context else None,
            effective_at=parse_timestamp(portfolio.get("updated_at")), claim_group="portfolio_context",
        ),
        LineageItem(
            domain="portfolio", dataset=(read_model_info or {}).get("type", "portfolio_health_snapshot"), provider=database.storage_mode(),
            source_version=(read_model_info or {}).get("calculation_version") or _CALCULATION_VERSIONS.get(tool, "ask-cached-capability-v1"),
            effective_at=parse_timestamp(as_of), claim_group=tool,
        ),
    ]
    dependency_status = AnalysisStatus.UNAVAILABLE if raw_unavailable else AnalysisStatus.SUCCESS
    input_fingerprint = context.version if context else None
    if tool == "portfolio_analysis":
        optimizer = summary.get("optimizer_run") or {}
        input_fingerprint = optimizer.get("input_fingerprint") or optimizer.get("portfolio_context_version")
    method_errors = any(not check.passed and check.severity == VerificationSeverity.ERROR for check in checks)
    if method_errors and status == AnalysisStatus.SUCCESS:
        status = AnalysisStatus.PARTIAL
    recommendation_allowed = status == AnalysisStatus.SUCCESS and tool != "portfolio_analysis"
    if tool in {"thesis_replacement", "cash_allocation"} and method_errors:
        recommendation_allowed = False
    return AnalysisResult(
        capability=tool,
        calculation_version=_CALCULATION_VERSIONS.get(tool, "ask-cached-capability-v1"),
        input_fingerprint=input_fingerprint,
        status=status,
        data=summary,
        coverage=coverage,
        freshness=freshness,
        lineage=lineage,
        dependencies=[DependencyResult(
            name=(read_model_info or {}).get("type", "portfolio_health_snapshot"), required=True, status=dependency_status,
            freshness=build_freshness([("portfolio_health_snapshot", as_of)]),
            cache_state=(read_model_info or {}).get("state", "legacy_adapter"), coverage=coverage,
        )],
        limitations=[str(summary.get("method"))] if summary.get("method") else [],
        warnings=list(summary.get("warnings") or []),
        prerequisites=prerequisites,
        verification=VerificationResult(
            passed=status == AnalysisStatus.SUCCESS,
            answer_allowed=status not in {AnalysisStatus.FAILED, AnalysisStatus.PENDING},
            recommendation_allowed=recommendation_allowed,
            checks=checks,
        ),
        summary={"title": summary.get("title"), "status": status.value},
    )


def _snapshot_required(tool: str, portfolio: dict[str, Any], overview: dict[str, Any] | None,
                       storage_error: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    if overview:
        return None
    message = storage_error or "No cached portfolio-health snapshot exists yet. A background portfolio refresh is required."
    return _evidence(tool, portfolio, {"status": "unavailable", "title": "Portfolio intelligence is preparing", "message": message}, portfolio.get("updated_at"))


def _factor_rank(holdings: list[dict[str, Any]], keys: tuple[str, ...], reverse: bool = True) -> list[dict[str, Any]]:
    eligible = [row for row in holdings if all(row.get(key) is not None for key in keys)]
    return sorted(eligible, key=lambda row: sum(_number(row.get(key)) for key in keys) / len(keys), reverse=reverse)


def _overview_from_read_model(read_model_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Adapt a typed read payload to the unchanged Phase 1 summary computations."""
    base = {"holdings": data.get("holdings") or [], "health": data.get("health") or {}, "ask_cache": {}}
    if read_model_type == "portfolio_opportunity":
        base["ask_cache"] = {"opportunity_candidates": data.get("opportunity_candidates") or []}
    elif read_model_type == "portfolio_risk":
        base["ask_cache"] = {"portfolio_intelligence": data.get("intelligence") or {},
                             "countercase": data.get("countercase") or {}}
    elif read_model_type == "portfolio_change":
        base.update({"changes": data.get("changes") or [], "warnings": data.get("warnings") or [],
                     "history": [{"source": "read_model_baseline"}] if data.get("baseline_available") else [],
                     "change_set": data.get("change_set") or {}})
    elif read_model_type == "portfolio_factor_state":
        base["ask_cache"] = {"relative_valuation": data.get("relative_valuation") or [],
                             "fundamental_trends": data.get("fundamental_trends") or {},
                             "improving_fundamental_screen": data.get("improving_fundamental_screen") or []}
    elif read_model_type == "watchlist_comparison":
        base["ask_cache"] = {"watchlist_research": data.get("research") or [],
                             "watchlist_dominance": data.get("dominance") or [],
                             "replacement_comparisons": data.get("replacement_comparisons") or [],
                             "cash_allocation": data.get("cash_allocation") or {}}
        base["read_model_theses"] = data.get("theses") or []
    elif read_model_type == "portfolio_events":
        base["ask_cache"] = {"events": data.get("events") or [], "typed_events": data.get("typed_events") or {}}
    elif read_model_type == "portfolio_data_quality":
        base["warnings"] = data.get("warnings") or []
        base["ask_cache"] = {"trust_classifications": data.get("trust_classifications") or [],
                             "classification_coverage": data.get("classification_coverage") or {}}
    elif read_model_type == "score_attribution":
        base["ask_cache"] = {"score_attributions": data.get("attributions") or []}
    elif read_model_type == "thesis_status":
        base["read_model_theses"] = data.get("theses") or []
        base["ask_cache"] = {"thesis_invalidation": data.get("invalidation_results") or []}
    elif read_model_type == "portfolio_scenario":
        base["ask_cache"] = {"latest_simulation": data.get("latest_simulation"), "scenarios": data.get("scenarios") or [],
                             "supported_factors": data.get("supported_factors") or [],
                             "factor_registry": data.get("factor_registry") or {}}
    elif read_model_type == "optimizer_compatibility":
        base["ask_cache"] = {"latest_optimizer": data.get("latest_optimizer"),
                             "rebalance_decision": data.get("rebalance_decision") or {}}
    return base


def run(tool: str, user_id: str, portfolio_id: str | None, question: str,
        tickers: tuple[str, ...] = (), context: PortfolioContext | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        portfolio = context.portfolio_payload() if context else _selected_portfolio(user_id, portfolio_id)
    except (KeyError, ValueError) as exc:
        empty = {"status": "unavailable", "title": "Portfolio context is required", "message": str(exc)}
        return _evidence(tool, {"updated_at": None}, empty, None)
    read_model_info: dict[str, Any] | None = None
    read_model_type = read_models.TOOL_READ_MODEL.get(tool)
    loaded = None
    if read_model_type and context:
        try:
            loaded = read_models.load_compatible_read_model(
                user_id, str(portfolio["id"]), read_model_type, context.version,
            )
        except Exception:
            loaded = None  # Missing migration/storage retains the explicit legacy adapter.
    if loaded and loaded.model and loaded.state in {read_models.CompatibilityState.CURRENT, read_models.CompatibilityState.STALE}:
        overview = _overview_from_read_model(read_model_type or "", loaded.model.data)
        metadata = loaded.model.metadata
        as_of_value = metadata.effective_through or metadata.calculated_at
        overview["as_of"] = as_of_value.isoformat()
        read_model_info = {
            "id": loaded.model.id, "type": read_model_type, "state": loaded.state.value,
            "reason": loaded.reason, "schema_version": metadata.schema_version,
            "calculation_version": metadata.calculation_version, "builder_version": metadata.builder_version,
            "freshness": metadata.freshness.model_dump(mode="json"),
            "input_fingerprint_match": loaded.input_fingerprint_match,
            "upstream_version_match": loaded.upstream_version_match, "legacy_adapter_used": False,
        }
        if loaded.state == read_models.CompatibilityState.STALE:
            overview.setdefault("warnings", []).append(f"Capability read model is stale: {loaded.reason}")
    elif loaded and loaded.state == read_models.CompatibilityState.INCOMPATIBLE:
        empty = {"status": "unavailable", "title": "Compatible portfolio intelligence is preparing",
                 "message": loaded.reason}
        return _covered_evidence(tool, portfolio, empty, portfolio.get("updated_at"), context,
                                 {"type": read_model_type, "state": loaded.state.value,
                                  "reason": loaded.reason, "legacy_adapter_used": False})
    else:
        overview, storage_error = _overview(user_id, str(portfolio["id"]))
        required = _snapshot_required(tool, portfolio, overview, storage_error)
        if required:
            return required
        assert overview is not None
        read_model_info = {"type": "portfolio_health_snapshot", "state": "LEGACY",
                           "legacy_adapter_used": True, "input_fingerprint_match": None,
                           "upstream_version_match": None}
    allowed = set(context.symbols) if context else None
    holdings = [row for row in list(overview.get("holdings") or [])
                if allowed is None or str(row.get("ticker") or "").upper() in allowed]
    if context:
        by_ticker = {str(row.get("ticker") or "").upper(): row for row in holdings}
        # The request context owns portfolio weights. Cached analytical fields
        # may enrich it, but a stale snapshot may not restore removed assets or
        # overwrite an in-memory renormalization.
        holdings = [{**by_ticker.get(row["ticker"], {}), **dict(row),
                     "ticker": row["ticker"], "weight": row.get("weight")}
                    for row in context.positions]
        overview = {**overview, "holdings": holdings}
    holding_tickers = {str(row.get("ticker") or "").upper() for row in holdings}
    as_of = overview.get("as_of") or portfolio.get("updated_at")
    health = overview.get("health") or {}
    ask_cache = overview.get("ask_cache") or {}

    if tool == "portfolio_overview":
        all_candidates = list(ask_cache.get("opportunity_candidates") or [])
        candidates = [row for row in all_candidates if (row.get("eligibility") or {}).get("eligible")][:3]
        summary = {"title": "Strongest evidence-backed portfolio setups", "health": health, "candidates": candidates,
                   "ineligible_candidates": [row for row in all_candidates if not (row.get("eligibility") or {}).get("eligible")],
                   "all_holdings": holdings,
                   "method": "Opportunity-v2 combines observed fundamental quality and trend, relative valuation evidence, momentum, balance-sheet quality, incremental portfolio fit, thesis state, and data eligibility. It ranks evidence-backed setups; it does not forecast returns."}
        if not candidates:
            summary["warnings"] = ["No holding passes every opportunity eligibility gate; displayed evidence must not be treated as an opportunity ranking."]
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "portfolio_change":
        change_set = overview.get("change_set") or {}
        summary = {"title": "Material portfolio changes", "health": health, "changes": overview.get("changes") or [],
                   "material_changes": change_set.get("changes") or [], "baseline_status": change_set.get("baseline_status"),
                   "materiality_thresholds": change_set.get("materiality_thresholds") or {},
                   "history": overview.get("history") or [], "warnings": overview.get("warnings") or [],
                   "all_holdings": holdings}
        summary["historical_snapshot"] = {
            "exists": bool(summary["history"]),
            "available_dates": [row.get("as_of") or row.get("created_at") for row in summary["history"] if row.get("as_of") or row.get("created_at")],
        }
        if not summary["historical_snapshot"]["exists"]:
            summary.update({"status": "unavailable", "message": "No previous portfolio snapshot exists, so material change cannot be calculated."})
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "valuation_ranking":
        ranked = list(ask_cache.get("relative_valuation") or [])
        eligible = [row for row in ranked if (row.get("eligibility") or {}).get("eligible") and row.get("relative_value_gap") is not None]
        summary = {"title": "Valuation burden relative to growth and fundamental quality", "positions": eligible[:10],
                   "all_holdings": holdings,
                   "all_relative_valuation": ranked,
                   "method": "Relative-valuation-v2 compares observed P/E, price-to-sales and free-cash-flow yield where available against stored EPS growth and fundamental quality. Sector peers are used only when at least two eligible peers exist."}
        if not eligible:
            summary["warnings"] = ["No holding has sufficient raw valuation, growth, and history inputs for a relative-value conclusion."]
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "data_quality":
        ranked = list(ask_cache.get("trust_classifications") or [])
        summary = {"title": "Portfolio ranking trust and eligibility review", "positions": ranked,
                   "all_holdings": holdings,
                   "classification_coverage": ask_cache.get("classification_coverage") or {},
                   "coverage": health.get("coverage"), "warnings": overview.get("warnings") or [],
                   "method": "Data-quality-v2 classifies HIGH, MEDIUM, LOW, or NOT_RANKABLE from raw required-field coverage, price/fundamental history, freshness, placeholder detection, and lineage—not symbol presence alone."}
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "multifactor_screen":
        ranked = list(ask_cache.get("improving_fundamental_screen") or [])
        trends = ask_cache.get("fundamental_trends") or {}
        near_matches = [{**row, "fundamental_trend": trends.get(str(row.get("ticker") or "").upper()) or {}}
                        for row in holdings]
        summary = {"title": "Fundamentals, valuation, and momentum screen", "positions": ranked[:15],
                   "all_holdings": holdings,
                   "near_matches": near_matches,
                   "method": "Fundamental-trend-screen-v2 requires an improving multi-period reported trend plus available valuation and positive momentum. A high current fundamental level alone is not improvement."}
        if not ranked:
            summary["warnings"] = ["No holding has sufficient stored multi-period evidence to prove improving fundamentals alongside valuation and momentum."]
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "score_attribution":
        selected = None
        if tickers:
            selected = next((row for row in ask_cache.get("score_attributions") or [] if row.get("ticker") == tickers[0]), None)
        if not selected:
            return _evidence(tool, portfolio, {"status": "unavailable", "title": "Company context is required",
                "message": "Name a holding or open its research page before asking why its score changed."}, as_of)
        summary = {"title": f"{selected['ticker']} score attribution", "holding": selected,
                   "component_changes": selected.get("component_deltas") or [],
                   "method": "Score-attribution-v2 compares actual compatible snapshot inputs, ranks weighted component impacts, separates methodology changes, and reports any unreconciled delta."}
        if not selected.get("comparable_baseline"):
            summary.update({"status": "unavailable", "message": "No component-level prior snapshot exists for this holding, so the score change cannot be attributed."})
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool in {"portfolio_intelligence", "recommendation_countercase"}:
        risk_ranked = sorted(holdings, key=lambda row: _number(row.get("risk_contribution")), reverse=True)
        concentration = [row for row in overview.get("actions") or [] if "concentration" in str(row.get("reason", "")).lower()]
        intelligence = ask_cache.get("portfolio_intelligence") or {}
        summary = {"title": "Hidden portfolio risk" if tool == "portfolio_intelligence" else "Countercase to the leading portfolio opportunity",
                   "health": health, "highest_risk_holdings": risk_ranked[:10], "concentration_actions": concentration,
                   "all_holdings": holdings,
                   "concentration": intelligence.get("concentration") or {},
                   "correlation": intelligence.get("correlation") or {},
                   "economic_dependencies": intelligence.get("economic_dependencies") or [],
                   "coverage": intelligence.get("coverage") or {},
                   "countercase": ask_cache.get("countercase") or {},
                   "warnings": overview.get("warnings") or [], "top_candidate": _factor_rank(holdings, ("health_score",))[:1],
                   "method": "Cached position, sector and industry concentration; return-correlation clusters; mapped economic dependencies; modeled risk contribution; and evidence warnings."}
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "portfolio_events":
        # Read models intentionally retain raw provider rows for provenance.
        # Re-apply the strict time/status boundary at request time so a cached
        # event cannot remain "upcoming" merely because the row is still stored.
        typed = phase4_analytics.build_portfolio_events(
            list(ask_cache.get("events") or []), holdings,
        )
        summary = {"title": "Upcoming material portfolio events", "events": list(typed.get("events") or [])[:20],
                   "event_completeness": typed,
                   "provider_limitations": typed.get("provider_limitations") or {},
                   "method": "Portfolio-events-v3 normalizes event category, mapped portfolio weight, materiality, source freshness, and confidence; completeness is reported independently for earnings, macro, company catalysts, and prediction markets."}
        return _covered_evidence(tool, portfolio, summary, ask_cache.get("generated_at") or as_of, context, read_model_info)

    if tool in {"watchlist_comparison", "thesis_replacement", "cash_allocation"}:
        watchlist = list(ask_cache.get("watchlist_research") or [])
        # A watchlist entry already owned is an add-to-existing candidate, not
        # a new position or replacement. Preserve it only with that explicit
        # classification.
        for row in watchlist:
            action = "REPLACEMENT" if tool == "thesis_replacement" else "ADD"
            row["candidate_type"] = str(classify_candidate(
                str(row.get("ticker") or ""), action,
                context,
            )) if context else ("ADD_TO_EXISTING" if str(row.get("ticker") or "").upper() in holding_tickers else "NEW_POSITION")
        watchlist_rows = sorted(watchlist, key=lambda row: (
            _number(row.get("fundamental_score")) + _number(row.get("valuation_score"))
            + _number(row.get("technical_score")) + _number(row.get("confidence"))
        ), reverse=True)
        add_to_existing = [row for row in watchlist_rows if row.get("candidate_type") == "ADD_TO_EXISTING"]
        if tool == "watchlist_comparison":
            watchlist_rows = [row for row in watchlist_rows if row.get("candidate_type") == "NEW_POSITION"]
        weak = sorted(holdings, key=lambda row: _number(row.get("health_score")))[:5]
        if tool == "thesis_replacement":
            watchlist_rows = [row for row in watchlist_rows if row.get("candidate_type") == "REPLACEMENT"]
        active_theses = [row for row in (overview.get("read_model_theses") if "read_model_theses" in overview else theses.list_theses(user_id))
                         if str(row.get("ticker") or "").upper() in holding_tickers]
        if tool == "thesis_replacement" and not active_theses:
            summary = {"status": "unavailable", "title": "No saved investment theses",
                       "message": "No saved thesis exists for this portfolio, so EagleEyes cannot identify a weakest thesis or claim that a replacement invalidates it.",
                       "watchlist_candidates": watchlist_rows[:5], "weakest_evidence_holdings": weak,
                       "dominance_results": ask_cache.get("watchlist_dominance") or [],
                       "thesis": {"exists": False, "count": 0}}
        else:
            summary = {"title": "Watchlist and portfolio comparison" if tool == "watchlist_comparison" else "New-cash research queue" if tool == "cash_allocation" else "Thesis and replacement review",
                       "watchlist_candidates": watchlist_rows[:10], "weakest_holdings": weak,
                       "add_to_existing_candidates": add_to_existing[:10],
                       "saved_theses": active_theses[:30],
                       "thesis": {"exists": bool(active_theses), "count": len(active_theses)},
                       "dominance_results": ask_cache.get("watchlist_dominance") or [],
                       "replacement_comparisons": ask_cache.get("replacement_comparisons") or [],
                       "cash_allocation": ask_cache.get("cash_allocation") or {},
                       "method": "Watchlist-dominance-v2 combines stored fundamentals, valuation, momentum, volatility/downside evidence, confidence, return correlation, and incremental sector concentration. It is a decision composite, not a Sharpe ratio or expected-return forecast."}
        summary["all_watchlist_rows"] = watchlist_rows
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "thesis_monitor":
        active_theses = [row for row in (overview.get("read_model_theses") if "read_model_theses" in overview else theses.list_theses(user_id))
                         if str(row.get("ticker") or "").upper() in holding_tickers]
        summary = {"title": "Thesis invalidation review", "saved_theses": active_theses[:30],
                   "invalidation_results": ask_cache.get("thesis_invalidation") or [],
                   "largest_positions": sorted(holdings, key=lambda row: _number(row.get("weight")), reverse=True)[:10],
                   "thesis": {"exists": bool(active_theses), "count": len(active_theses)}}
        if not active_theses:
            summary.update({"status": "unavailable", "message": "No saved thesis exists. EagleEyes can show evidence risks, but it cannot invent the user's thesis or its invalidation conditions."})
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "portfolio_scenario":
        simulation = ask_cache.get("latest_simulation")
        # Scenario narration evaluates the current portfolio path. Optimizer
        # attempts inside the cached run are separate artifacts and must not
        # contaminate scenario compatibility or expose infeasible weights.
        scenario_simulation = ({key: value for key, value in simulation.items() if key != "optimizer"}
                               if isinstance(simulation, dict) else simulation)
        summary = {"title": "Cached portfolio scenario matrix", "latest_simulation": scenario_simulation,
                   "market_scenarios": ask_cache.get("scenarios") or [],
                   "all_holdings": holdings,
                   "requested_conditions": question,
                   "method": "Latest cached portfolio simulation and stored scenario probabilities; no simulation or provider refresh runs inside chat."}
        if not simulation:
            summary.update({"status": "unavailable", "message": "No cached portfolio simulation exists yet. Queue the canonical scenario refresh before relying on this comparison."})
        summary["scenario_factors"] = [row.__dict__ for row in parse_scenario_factors(question)]
        scenario_input = ((simulation or {}).get("input") or {}).get("scenario") or {}
        supported: list[dict[str, Any]] = list(ask_cache.get("supported_factors") or [])
        if scenario_input.get("rate_state") == "tightening":
            if not any(row.get("factor") == "interest_rates" and row.get("direction") == "increase" for row in supported):
                supported.append({"factor": "interest_rates", "direction": "increase", "support_type": "EMPIRICAL_SIMULATION"})
        elif scenario_input.get("rate_state") == "easing":
            supported.append({"factor": "interest_rates", "direction": "decrease", "support_type": "EMPIRICAL_SIMULATION"})
        if scenario_input.get("economic_state") == "recession":
            if not any(row.get("factor") == "economic_growth" and row.get("direction") == "decrease" for row in supported):
                supported.append({"factor": "economic_growth", "direction": "decrease", "support_type": "EMPIRICAL_SIMULATION"})
        elif scenario_input.get("economic_state") == "expansion":
            supported.append({"factor": "economic_growth", "direction": "increase", "support_type": "EMPIRICAL_SIMULATION"})
        if scenario_input.get("inflation_state") == "accelerating":
            supported.append({"factor": "inflation", "direction": "increase", "support_type": "EMPIRICAL_SIMULATION"})
        elif scenario_input.get("inflation_state") == "cooling":
            supported.append({"factor": "inflation", "direction": "decrease", "support_type": "EMPIRICAL_SIMULATION"})
        summary["supported_scenario_factors"] = supported
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    if tool == "portfolio_analysis":
        optimizer = ask_cache.get("latest_optimizer")
        summary = {
            "title": "Latest saved portfolio analysis",
            "optimizer_run": optimizer,
            "all_holdings": holdings,
            "selected_alternative": next((
                row for row in list((optimizer or {}).get("alternatives") or [])
                if row.get("name") == "Balanced"
            ), None),
            "model_diagnostics": (optimizer or {}).get("model_diagnostics") or {},
            "rebalance_decision": ask_cache.get("rebalance_decision") or {},
            "warnings": (optimizer or {}).get("warnings") or [],
            "method": "Latest saved optimizer run. Compatibility, feasibility, tax-lot coverage, and constraints must pass before recommendation use.",
        }
        if not optimizer:
            summary.update({"status": "unavailable", "message": "No saved portfolio optimizer run exists."})
        return _covered_evidence(tool, portfolio, summary, as_of, context, read_model_info)

    return _evidence(tool, portfolio, {"status": "unavailable", "title": tool.replace("_", " ").title(), "message": "No cached portfolio aggregator is registered for this question."}, as_of)


def _covered_evidence(tool: str, portfolio: dict[str, Any], summary: dict[str, Any],
                      as_of: str | None, context: PortfolioContext | None,
                      read_model_info: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results, grounded = _evidence(tool, portfolio, summary, as_of)
    for row in results:
        analysis = _canonical_result(tool, portfolio, summary, as_of, context, read_model_info)
        row.update(with_canonical_result({}, analysis))
        row["status"] = analysis.status.value.lower()
        row["coverage"] = {
            "requested": len(analysis.coverage.requested_entities),
            "evaluated": len(analysis.coverage.evaluated_entities),
            "missing": len(analysis.coverage.missing_entities),
            "missing_symbols": analysis.coverage.missing_entities,
            "percent": analysis.coverage.entity_coverage_percent,
        }
        if context:
            row["portfolio_context_version"] = context.version
        row["read_model"] = read_model_info or {
            "type": "portfolio_health_snapshot", "state": "LEGACY", "legacy_adapter_used": True,
        }
    return results, grounded


def _rows(items: list[dict[str, Any]], formatter, limit: int = 5) -> str:
    return "\n".join(f"{index}. {formatter(row)}" for index, row in enumerate(items[:limit], 1))


def _weight_rows(items: list[dict[str, Any]], label_key: str, limit: int = 5) -> str:
    eligible = [row for row in items if row.get(label_key) and row.get("weight") is not None]
    eligible.sort(key=lambda row: _number(row.get("weight")), reverse=True)
    return _rows(
        eligible,
        lambda row: f"**{row.get(label_key)}** — {_number(row.get('weight')):.1%}",
        limit,
    )


def _factor_label(value: Any) -> str:
    acronyms = {"ai": "AI", "cpi": "CPI", "gdp": "GDP"}
    return " ".join(acronyms.get(word.lower(), word.title()) for word in str(value or "").replace("_", " ").split())


def _hidden_risk_answer(summary: dict[str, Any]) -> str:
    concentration = summary.get("concentration") or {}
    positions = list(concentration.get("positions") or [])
    sectors = list(concentration.get("sector") or [])
    industries = list(concentration.get("industry") or [])
    correlation = summary.get("correlation") or {}
    clusters = list(correlation.get("clusters") or [])
    dependencies = list(summary.get("economic_dependencies") or [])
    risk = list(summary.get("highest_risk_holdings") or [])
    coverage = summary.get("coverage") or {}

    position_text = _rows(
        positions,
        lambda row: f"**{row.get('ticker')}** — {_number(row.get('weight')):.1%} of portfolio value",
        6,
    )
    sector_text = _weight_rows(sectors, "sector", 5)
    industry_text = _weight_rows(industries, "industry", 4)
    cluster_text = _rows(
        clusters,
        lambda row: (
            f"**{', '.join(row.get('holdings') or [])}** — {_number(row.get('portfolio_weight')):.1%} combined weight"
            + (f"; strongest measured pair correlation {_number((row.get('strongest_pair') or {}).get('correlation')):.2f}"
               if row.get("strongest_pair") else "")
        ),
        3,
    )
    dependency_text = _rows(
        dependencies,
        lambda row: (
            f"**{_factor_label(row.get('factor'))}** — "
            f"{_number(row.get('mapped_portfolio_weight')):.1%} mapped exposure across "
            f"{', '.join((row.get('holdings') or [])[:8]) or 'covered holdings'}; {row.get('mechanism') or 'shared economic driver'}"
        ),
        4,
    )
    risk_text = _rows(
        risk,
        lambda row: (
            f"**{row.get('ticker')}** — modeled risk contribution {_number(row.get('risk_contribution')):.1%}, "
            f"portfolio weight {_number(row.get('weight')):.1%}, health {_number(row.get('health_score')):.0f}/100"
        ),
        8,
    )
    effective = concentration.get("effective_holdings")
    largest = positions[0] if positions else None
    headline = (
        f"The portfolio's visible concentration starts with **{largest.get('ticker')} at {_number(largest.get('weight')):.1%}**"
        if largest else "The cached snapshot does not contain position weights"
    )
    if effective is not None:
        headline += f", and its weights are equivalent to roughly **{_number(effective):.1f} equally sized holdings**"
    headline += ". The more important risk concentration is the overlap between the largest positions, correlated clusters, and shared economic drivers below [S1]."

    sections = [f"## Conclusion\n\n{headline}"]
    if position_text:
        sections.append(f"## Capital concentration\n\n{position_text}")
    if sector_text or industry_text:
        classification = ""
        if sector_text:
            classification += f"**Largest classified sectors**\n\n{sector_text}"
        if industry_text:
            classification += ("\n\n" if classification else "") + f"**Largest classified industries**\n\n{industry_text}"
        sections.append(f"## Sector and industry overlap\n\n{classification}")
    shared = ""
    if cluster_text:
        shared += f"**Return-correlation clusters**\n\n{cluster_text}"
    elif str(correlation.get("status") or "").upper() == "UNAVAILABLE":
        shared += f"Return-correlation evidence is unavailable: {correlation.get('reason') or 'stored price history was insufficient.'}"
    if dependency_text:
        shared += ("\n\n" if shared else "") + f"**Shared economic dependencies**\n\n{dependency_text}"
    if shared:
        sections.append(f"## Hidden shared-risk concentration\n\n{shared}")
    if risk_text:
        sections.append(f"## Largest modeled risk contributors\n\n{risk_text}")

    classification_contract = coverage.get("classification") or {}
    metadata_coverage = (classification_contract.get("security_metadata") or {}).get("portfolio_weight_coverage")
    rendered_contract = classification_contract.get("rendered_sector") or {}
    fund_contract = classification_contract.get("fund_level") or {}
    unknown_contract = classification_contract.get("unknown") or {}
    unclassified_weight = sum(
        _number(row.get("weight")) for row in sectors
        if str(row.get("sector") or "").strip().lower() in {"unclassified", "unknown", "unavailable"}
    )
    sector_row_coverage = max(0.0, 1.0 - unclassified_weight) if sectors else None
    if classification_contract:
        rendered_weight = _number(rendered_contract.get("portfolio_weight_coverage"), sector_row_coverage or 0)
        coverage_note = (
            f"Rendered issuer-sector coverage is **{rendered_weight:.1%}** of portfolio weight; "
            f"security-record metadata coverage is **{_number(metadata_coverage):.1%}** and is not a sector measure. "
            f"Funds represent **{_number(fund_contract.get('portfolio_weight')):.1%}** at fund level; "
            f"look-through is available for **{_number(fund_contract.get('look_through_available_weight')):.1%}** and unavailable for "
            f"**{_number(fund_contract.get('look_through_unavailable_weight')):.1%}**. "
            f"Unknown instrument/classification weight is **{_number(unknown_contract.get('portfolio_weight')):.1%}**. "
        )
    elif sector_row_coverage is not None:
        coverage_note = f"Rendered issuer-sector coverage is **{sector_row_coverage:.1%}** of portfolio weight. "
    else:
        coverage_note = "The snapshot does not report classification coverage. "
    coverage_note += "Fund-level classification is not issuer-sector look-through, so direct holdings may overlap with a fund more than the sector rows reveal."
    sections.append(f"## Coverage limits\n\n{coverage_note}")
    sections.append("**What to verify:** inspect ETF look-through, the covariance date and sample size, and whether the largest shared economic dependencies match how you understand the businesses.")
    return "\n\n".join(sections)


def compose(intent: str, tool_results: list[dict[str, Any]]) -> str | None:
    result = next((row for row in tool_results if row.get("status") in {"complete", "success", "partial"}), None)
    summary = canonical_data(result or {}) or {}
    unavailable = next((row for row in tool_results if row.get("status") == "unavailable"), None)
    if not result:
        unavailable_data = canonical_data(unavailable or {}) or {}
        message = unavailable_data.get("message") if isinstance(unavailable_data, dict) else None
        if not message and unavailable:
            canonical = unavailable.get("analysis_result") or {}
            missing = [
                row.get("reason") for row in canonical.get("prerequisites") or []
                if not row.get("satisfied") and row.get("reason")
            ]
            message = " ".join(missing)
        return f"{message}\n\n**What to verify:** confirm the selected portfolio and complete the missing saved-data prerequisite." if message else None

    if intent == "OPPORTUNITY_RANKING":
        rows = summary.get("candidates") or []
        body = _rows(rows, lambda row: (
            f"**{row.get('ticker')}** — evidence-backed setup **{_number(row.get('opportunity_score')):.1f}/100**; "
            f"fundamental quality {_number(row.get('fundamental_quality')):.0f}, trend {((row.get('fundamental_trend') or {}).get('direction') or 'unavailable').lower()}, "
            f"valuation {_number(row.get('valuation')):.0f}, momentum {_number(row.get('momentum')):.0f}, portfolio fit {_number(row.get('portfolio_fit')):.0f}. "
            f"**Why:** {'; '.join(row.get('supporting_evidence') or []) or 'No positive evidence statement passed.'} "
            f"**Main concern:** {'; '.join(row.get('opposing_evidence') or []) or 'No material opposing signal recorded.'} "
            f"**Evidence confidence:** {row.get('confidence')} [S1]"
        ), 3)
        if not body:
            return "No holding currently passes every opportunity-v2 eligibility gate. EagleEyes will not rank low-quality or placeholder-driven factor records as opportunities.\n\n**What to verify:** refresh raw fundamentals and price history, then rebuild the opportunity read model."
        return f"EagleEyes defines an opportunity as the strongest **current evidence-backed setup**, not a forecast of future return.\n\n{body}\n\n{summary.get('method')}\n\n**What to verify:** review the raw valuation, trend periods, thesis state, and concentration effect before recording a decision."
    if intent == "PORTFOLIO_CHANGE":
        changes = summary.get("material_changes") or []
        if not changes:
            status = summary.get("baseline_status")
            return (("No compatible prior baseline exists, so EagleEyes cannot calculate change since the last review." if status == "NO_BASELINE" else
                     "A compatible prior baseline exists, but no change crossed the disclosed materiality thresholds.")
                    + "\n\n**What to verify:** confirm the current and baseline snapshot identities and evidence dates.")
        body = _rows(changes, lambda row: f"**{row.get('entity') or 'Portfolio'} — {str(row.get('domain') or '').replace('_', ' ').title()}**: {row.get('reason')}" + (f" (delta {_number(row.get('delta')):+.2f})" if row.get("delta") is not None else ""), 10)
        return f"These material changes are recorded for the selected portfolio:\n\n{body}\n\n**What to verify:** open the change timeline and inspect the evidence date and trigger for each item."
    if intent == "VALUATION_RANKING":
        body = _rows(summary.get("positions") or [], lambda row: f"**{row.get('ticker')}** — relative-value gap {_number(row.get('relative_value_gap')):+.1f}; valuation burden {_number(row.get('valuation_level')):.1f}, growth support {_number(row.get('growth_support')):.1f}, quality support {_number(row.get('quality_support')):.1f}; peer context {('available' if (row.get('peer_context') or {}).get('available') else 'not available')}; confidence {row.get('confidence')} [S1]", 10)
        return f"These eligible holdings have the largest observed valuation burden after accounting for stored growth and fundamental quality:\n\n{body or 'No holding has sufficient raw valuation and growth inputs for this comparison.'}\n\nThis is a relative evidence gap, not an intrinsic-value estimate or return forecast.\n\n**What to verify:** inspect each underlying multiple, EPS comparison period, peer count, and freshness."
    if intent == "DATA_QUALITY":
        rows = [row for row in summary.get("positions") or [] if row.get("trust_classification") != "HIGH"]
        body = _rows(rows, lambda row: f"**{row.get('ticker')}** — **{row.get('trust_classification')}**; rankable: {row.get('rankable')}; issues: {', '.join((row.get('eligibility') or {}).get('missing_fields') or (row.get('eligibility') or {}).get('placeholder_fields') or []) or 'none'} [S1]", 15)
        return f"The holdings below have the least reliable current ranking inputs:\n\n{body or 'No lower-confidence holdings are recorded.'}\n\nMissing coverage is penalized rather than treated as neutral.\n\n**What to verify:** refresh the largest low-confidence holdings before relying on their relative order."
    if intent == "MULTIFACTOR_SCREEN":
        body = _rows(summary.get("positions") or [], lambda row: f"**{row.get('ticker')}** — trend **{((row.get('fundamental_trend') or {}).get('direction') or 'unavailable').lower()}** across {len((row.get('fundamental_trend') or {}).get('periods_compared') or [])} periods; fundamentals {_number(row.get('fundamental_score')):.0f}, valuation {_number(row.get('valuation_score')):.0f}, momentum {_number(row.get('momentum_score')):.0f} [S1]", 10)
        return f"These holdings have a genuinely improving stored fundamental trend plus available valuation and positive momentum:\n\n{body or 'No holding passes all three deterministic requirements with sufficient historical evidence.'}\n\nA strong current fundamental score without an improving trend is excluded.\n\n**What to verify:** inspect the reported periods and metric-level trend evidence."
    if intent == "SCORE_ATTRIBUTION":
        row = summary.get("holding") or {}
        components = _rows(row.get("component_deltas") or [], lambda item: f"**{str(item.get('component')).replace('_', ' ').title()}** — input delta {_number(item.get('input_delta')):+.3f}; score impact {_number(item.get('score_impact')):+.3f}", 8)
        return f"**{row.get('ticker')}** changed from **{_number(row.get('previous_score')):.1f}** to **{_number(row.get('current_score')):.1f}** (total {_number(row.get('total_delta')):+.1f}) [S1].\n\n{components}\n\nUnexplained delta: **{_number(row.get('unexplained_delta')):+.3f}**. Methodology change: **{row.get('methodology_change') or 'none recorded'}**.\n\n**What to verify:** confirm baseline timestamp and calculation-version compatibility before treating the delta as a company change."
    if intent == "PORTFOLIO_EVENTS":
        body = _rows(summary.get("events") or [], lambda row: f"**{row.get('title')}** — {row.get('date') or 'date unavailable'}; {str(row.get('event_type')).replace('_', ' ').title()}; affected weight {_number(row.get('affected_portfolio_weight')):.1%}; materiality {row.get('estimated_materiality')}; confidence {row.get('confidence')} [S1]", 12)
        completeness = (summary.get("event_completeness") or {}).get("category_completeness") or {}
        limitations = summary.get("provider_limitations") or {}
        limitation_text = " ".join(str(value) for value in limitations.values() if value)
        return f"The stored event calendar contains these upcoming portfolio-relevant events:\n\n{body or 'No covered upcoming event is stored.'}\n\n**Category health:** earnings {completeness.get('earnings', 'MISSING')}; macro {completeness.get('macro_calendar', 'MISSING')}; company catalysts {completeness.get('company_catalysts', 'MISSING')}; prediction-market events {completeness.get('prediction_markets', 'MISSING')}.\n\n{limitation_text}\n\n**What to verify:** confirm event dates and missing categories before assuming silence means no catalyst exists."
    if intent == "HIDDEN_RISK":
        return _hidden_risk_answer(summary)
    if intent == "RECOMMENDATION_COUNTERCASE":
        countercase = summary.get("countercase") or {}
        body = _rows(countercase.get("strongest_counterarguments") or [], lambda row: f"**{str(row.get('category')).replace('_', ' ').title()} ({row.get('severity')})** — {row.get('evidence')} [S1]", 8)
        return f"Countercase for **{countercase.get('ticker') or 'no eligible recommendation'}** (recommendation `{countercase.get('recommendation_id') or 'unavailable'}`):\n\n{body or 'No stable eligible recommendation exists to challenge.'}\n\nUnknowns: {', '.join(countercase.get('unresolved_unknowns') or []) or 'none recorded'}.\n\n**What to verify:** confirm the recommendation fingerprint and calculation version still match the current portfolio."
    if intent in {"WATCHLIST_COMPARISON", "THESIS_REPLACEMENT", "CASH_ALLOCATION"}:
        if intent == "CASH_ALLOCATION":
            cash = summary.get("cash_allocation") or {}
            hurdle = cash.get("cash_hurdle") or {}
            rows = cash.get("candidates") or []
            body = _rows(rows, lambda row: f"**{row.get('candidate')}** — {row.get('dominance_status')}; decision score {_number(row.get('decision_score')):.1f}; concentration {((row.get('diversification_effect') or {}).get('concentration_effect') or '').lower()} [S1]", 5)
            hurdle_text = (
                f"{_number(hurdle.get('annual_yield')):.2%} annualized"
                + (f" from {hurdle.get('source')}" if hurdle.get("source") else "")
                + (f" as of {hurdle.get('as_of')}" if hurdle.get("as_of") else "")
                if hurdle.get("available") else
                "unavailable — no supported stored cash/risk-free yield"
            )
            conclusion = str(cash.get('recommended_action') or 'NO_CLEAR_EDGE').replace('_', ' ')
            qualification = (
                "The candidates pass the stored multi-factor comparison, but that does **not** prove a risk-adjusted return above the cash hurdle because EagleEyes has no supported expected-return forecast. "
                if rows and hurdle.get("available") else ""
            )
            return f"**Decision: {conclusion}.**\n\nCash hurdle: **{hurdle_text}** [S1].\n\n{body or 'No candidate has a verified edge over the available comparison set.'}\n\n{qualification}{cash.get('sizing_guidance')}\n\nEagleEyes does not force deployment and does not invent expected returns, taxes, or trading costs."
        if intent == "THESIS_REPLACEMENT":
            comparisons = summary.get("replacement_comparisons") or []
            supported = [row for row in comparisons if row.get("replacement_dominance") == "REPLACEMENT_SUPPORTED"]
            body = _rows(supported or comparisons, lambda row: f"**{row.get('incumbent')} → {row.get('candidate')}** — {str(row.get('replacement_dominance')).replace('_', ' ')}; incumbent {_number(row.get('incumbent_score')):.1f}, candidate {_number(row.get('candidate_score')):.1f}; concentration {((row.get('portfolio_fit') or {}).get('concentration_effect') or '').lower()} [S1]", 5)
            return f"Replacement review:\n\n{body or 'No candidate proves deterministic replacement dominance.'}\n\nA replacement is supported only when the candidate dominates the weakest saved-thesis incumbent and does not worsen incremental concentration. EagleEyes does not force a swap."
        dominance = summary.get("dominance_results") or []
        body = _rows(dominance, lambda row: f"**{row.get('candidate')}** ({str(row.get('candidate_type')).replace('_', ' ').lower()}) — {str(row.get('dominance_status')).replace('_', ' ')}; decision score {_number(row.get('decision_score')):.1f}; correlation {_number((row.get('diversification_effect') or {}).get('candidate_portfolio_correlation')):.2f}; concentration {((row.get('diversification_effect') or {}).get('concentration_effect') or '').lower()} [S1]", 8)
        clear = [row.get("candidate") for row in dominance if row.get("dominance_status") == "DOMINATES"]
        conclusion = ("Clear stronger new-position cases: " + ", ".join(clear) + "." if clear else
                      "No new watchlist position proves a stronger risk-adjusted case than the comparison holdings.")
        return f"**{conclusion}**\n\nWatchlist candidates compared with the weakest existing holdings on evidence quality, stored volatility, correlation, and incremental concentration:\n\n{body or 'No watchlist candidate has sufficient stored evidence.'}\n\nThis is a defined decision composite—not a Sharpe ratio or calibrated outperformance probability."
    if intent == "THESIS_INVALIDATION":
        theses_rows = summary.get("invalidation_results") or []
        body = _rows(theses_rows, lambda row: f"**{row.get('ticker')}** — saved thesis: {row.get('thesis_exists')}; explicit breakers: {len(row.get('explicit_breakers') or [])}; missing: {', '.join(row.get('missing_evidence') or []) or 'none'} [S1]", 10)
        return f"Thesis invalidation status for the largest positions:\n\n{body}\n\nEagleEyes uses only user-saved assumptions and breakers. It does not invent personalized invalidation criteria."
    if intent == "MULTI_SCENARIO":
        simulation = summary.get("latest_simulation") or {}
        factors = summary.get("scenario_factors") or []
        factor_text = ", ".join(
            f"**{_factor_label(row.get('factor'))} {row.get('direction')}**" for row in factors
        ) or "no supported factors"
        methodologies = "; ".join(f"{_factor_label(row.get('factor'))}: {str(row.get('support_type') or 'unsupported').replace('_', ' ').lower()}" for row in summary.get("supported_scenario_factors") or [])
        current = next((row for row in simulation.get("outcomes") or [] if row.get("strategy_key") in {"current", "current_portfolio"}), None) or next(iter(simulation.get("outcomes") or []), {})
        real_wealth = current.get("real_wealth_percentiles") or current.get("wealth_percentiles") or {}
        drawdown = current.get("drawdown_percentiles") or {}
        terminal_loss_probability = current.get("terminal_loss_probability")
        if terminal_loss_probability is None:
            terminal_loss_probability = current.get("probability_of_loss")
        adverse_drawdown = current.get("simulated_max_drawdown_p95")
        adverse_label = "95th-percentile maximum peak-to-trough drawdown severity"
        if adverse_drawdown is None:
            adverse_drawdown = drawdown.get("p10")
            adverse_label = "10th percentile of the signed maximum-drawdown distribution"
        ai_support = next((row for row in summary.get("supported_scenario_factors") or [] if row.get("factor") == "ai_capex"), {})
        outcome_text = (
            f"For the current-portfolio path, cached median real terminal wealth is **{_number(real_wealth.get('p50')):,.0f}**, "
            f"probability of ending the horizon below the starting value is **{_number(terminal_loss_probability):.1%}**, "
            f"and the {adverse_label} is **{_number(adverse_drawdown):.1%}** [S1]. "
            if current else "No current-portfolio outcome row is stored. "
        )
        ai_text = (f"The separate AI-capex slowdown mapping touches **{_number(ai_support.get('mapped_portfolio_weight')):.1%}** of portfolio weight across {', '.join(ai_support.get('affected_holdings') or [])}; it is exposure mapping, not a loss estimate [S1]. " if ai_support else "")
        return (
            f"The request contains these independent scenario factors: {factor_text} [S1]. "
            f"The latest cached portfolio simulation uses model **{simulation.get('model_version') or 'unknown'}** [S1]. "
            + outcome_text + ai_text +
            "EagleEyes preserves each factor separately; it will not silently collapse a rates, growth, and AI-capex question into a recession-only case. "
            f"Methodologies are kept separate: {methodologies}. AI-capex exposure mapping does not claim a simulated loss magnitude. No live provider refresh or new simulation ran inside chat.\n\n"
            "**What to verify:** open the cached scenario matrix and confirm that every named factor has a mapped portfolio sensitivity before relying on a combined-case conclusion."
        )
    if intent == "PORTFOLIO_ANALYSIS":
        decision = summary.get("rebalance_decision") or {}
        targets = sorted(decision.get("target_weights") or [], key=lambda row: abs(_number(row.get("delta"))), reverse=True)
        target_text = _rows(targets, lambda row: (
            f"**{row.get('ticker')}** — target {_number(row.get('target_weight')):.1%}; "
            f"change {_number(row.get('delta')):+.1%}; {row.get('reason') or 'constraint-aware model output'} [S1]"
        ), 8)
        return (f"**Actionable rebalance: {decision.get('actionable', False)}.** Feasibility: **{decision.get('feasibility', 'NOT_TRACKED')}**; portfolio fingerprint match: **{decision.get('portfolio_fingerprint_match', False)}** [S1]. "
                f"Expected turnover: **{decision.get('expected_turnover')}**; trading-cost model: **{decision.get('trading_cost_model', 'UNAVAILABLE')}**; tax data available: **{decision.get('tax_data_available', False)}**; tax-aware: **{decision.get('tax_aware', False)}**. "
                + (f"\n\nLargest modeled changes:\n\n{target_text}\n\n" if target_text else "\n\nTarget weights and trades are withheld unless feasibility and fingerprint checks pass. ")
                + "This result is not tax optimized and has no supported trading-cost estimate.\n\n"
                "**What to verify:** refresh a compatible optimizer result and provide lot-level cost basis before requesting tax-aware trades.")
    return None
