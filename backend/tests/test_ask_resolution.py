from __future__ import annotations

import json

from backend.ask_resolution import DependencyClass, SupportedAnswer, compose_supported_answer, DEPENDENCY_MATRIX
from backend.ask_runtime import PortfolioContext, enforce_output_symbol_boundary, verify_results
from backend.ask_portfolio import _coverage_for, compose


def context() -> PortfolioContext:
    return PortfolioContext(
        portfolio_id="p1", name="Owner", positions=({"ticker": "MSFT", "weight": 1.0},),
        excluded_positions=({"ticker": "CASH"}, {"ticker": "PONPX"}),
        excluded_symbols=("CASH", "PONPX"), total_positions=1, source_positions=3,
        normalized_weights={"MSFT": 1.0}, as_of="2026-08-22T00:00:00Z", version="v1",
    )


def tool(summary: dict, *, status: str = "partial", prerequisites: list[dict] | None = None) -> list[dict]:
    return [{
        "tool_name": "portfolio_overview", "status": status, "summary": summary,
        "analysis_result": {
            "capability": "portfolio_overview", "status": status.upper(), "data": summary,
            "prerequisites": prerequisites or [],
        },
    }]


def test_dependency_matrix_separates_system_jobs_and_user_context():
    assert DEPENDENCY_MATRIX["prices"] == DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA
    assert DEPENDENCY_MATRIX["simulation"] == DependencyClass.ON_DEMAND_COMPUTATION
    assert DEPENDENCY_MATRIX["saved_thesis"] == DependencyClass.USER_REQUIRED_CONTEXT


def test_excluded_symbol_boundary_suppresses_entire_claims_and_nested_lists():
    rows = [{"tool_name": "risk", "status": "partial", "summary": {
        "positions": [{"ticker": "MSFT", "weight": .8}, {"ticker": "PONPX", "weight": .2}],
        "clusters": [{"holdings": ["MSFT", "PONPX"], "note": "measured overlap"}],
        "warning": "PONPX reappeared in stale output",
    }}]
    cleaned = enforce_output_symbol_boundary(rows, context())
    encoded = json.dumps(cleaned)
    assert "PONPX" not in encoded
    assert "MSFT" in encoded
    assert cleaned[0]["summary"].get("warning") is None


def test_opportunity_fallback_returns_near_matches_with_failed_gates():
    summary = {"candidates": [], "ineligible_candidates": [{
        "ticker": "MSFT", "fundamental_quality": 82, "valuation": 45, "momentum": 70,
        "portfolio_fit": 55, "eligibility": {"missing_fields": ["fundamental_history"]},
        "supporting_evidence": ["Stored price momentum is positive."],
    }]}
    _, answer = compose_supported_answer(
        intent="OPPORTUNITY_RANKING", question="opportunities", context=context(),
        tool_results=tool(summary), deterministic_answer="No eligible opportunity.",
    )
    assert isinstance(answer, SupportedAnswer)
    assert "MSFT" in answer.direct_answer
    assert "fundamental_history" in answer.direct_answer
    assert answer.partial_claims


def test_missing_thesis_blocks_only_personalized_claim():
    summary = {"thesis": {"exists": False}, "weakest_evidence_holdings": [
        {"ticker": "MSFT", "health_score": 42, "weight": 1.0},
    ]}
    prerequisites = [{"name": "saved_thesis_exists", "satisfied": False,
                      "reason": "No saved thesis exists for the selected portfolio."}]
    resolution, answer = compose_supported_answer(
        intent="THESIS_REPLACEMENT", question="weakest thesis", context=context(),
        tool_results=tool(summary, status="unavailable", prerequisites=prerequisites), deterministic_answer=None,
    )
    assert "cannot rank your personal theses" in answer.direct_answer
    assert "MSFT" in answer.direct_answer
    assert answer.supported_claims[0].scope == "objective"
    assert resolution.user_required_missing_context


def test_data_quality_is_field_level_not_all_or_nothing_coverage():
    summary = {"positions": [
        {"ticker": "MSFT", "trust_classification": "LOW", "eligibility": {
            "required_checks": {"momentum_history": True, "fundamental_history": False},
            "missing_fields": ["fundamental_history"],
        }},
        {"ticker": "AMZN", "trust_classification": "HIGH", "eligibility": {
            "required_checks": {"momentum_history": True, "fundamental_history": True},
            "missing_fields": [],
        }},
    ]}
    _, answer = compose_supported_answer(
        intent="DATA_QUALITY", question="quality", context=context(),
        tool_results=tool(summary), deterministic_answer="0/2 coverage",
    )
    assert "Fundamental History**: 1/2" in answer.direct_answer
    assert "Momentum History**: 2/2" in answer.direct_answer
    assert "0/2 coverage" not in answer.direct_answer


def test_missing_optimizer_keeps_objective_concentration_and_pending_job():
    summary = {"optimizer_run": None, "all_holdings": [{"ticker": "MSFT", "weight": 1.0}]}
    results = tool(summary, status="unavailable")
    results.append({"tool_name": "portfolio_analysis_job", "status": "pending", "job_id": "job-1",
                    "summary": {"message": "queued"}})
    _, answer = compose_supported_answer(
        intent="PORTFOLIO_ANALYSIS", question="rebalance", context=context(),
        tool_results=results, deterministic_answer=None,
    )
    assert "MSFT" in answer.direct_answer
    assert "tax-aware" in answer.direct_answer
    assert answer.jobs_started[0]["job_id"] == "job-1"


def test_zero_material_changes_is_valid_portfolio_level_coverage():
    coverage = _coverage_for("portfolio_change", {"material_changes": []}, context())
    verification = verify_results("PORTFOLIO_CHANGE", context(), [], [{
        "tool_name": "portfolio_change", "status": "success", "coverage": coverage.model_dump(),
        "summary": {"historical_snapshot": {"exists": True}, "material_changes": []},
    }])
    assert coverage.requested_entities == []
    assert verification.answer_allowed is True
    assert verification.failures == []


def test_event_answer_surfaces_independent_provider_limitations():
    answer = compose("PORTFOLIO_EVENTS", [{"status": "partial", "summary": {
        "events": [],
        "event_completeness": {"category_completeness": {
            "earnings": "MISSING", "macro_calendar": "MISSING",
            "company_catalysts": "MISSING", "prediction_markets": "CURRENT",
        }},
        "provider_limitations": {
            "earnings": "No configured adapter supplies an earnings calendar.",
            "macro_calendar": "FRED observations do not supply a forward release calendar.",
        },
    }}])
    assert "No configured adapter supplies an earnings calendar." in answer
    assert "FRED observations do not supply a forward release calendar." in answer
