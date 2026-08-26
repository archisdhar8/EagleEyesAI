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


def test_gain_loss_attribution_uses_cost_basis_and_discloses_scope():
    _, answer = compose_supported_answer(
        intent="GAIN_LOSS_ATTRIBUTION", question="gains and losses", context=context(),
        tool_results=[{"tool_name": "portfolio_risk", "status": "complete", "summary": {"positions": [
            {"ticker": "MSFT", "weight": .6, "market_value": 1600, "cost_basis": 1000, "unrealized_gain_loss": 600},
            {"ticker": "AMZN", "weight": .4, "market_value": 800, "cost_basis": 1000, "unrealized_gain_loss": -200},
        ]}}], deterministic_answer=None,
    )
    assert "MSFT" in answer.direct_answer and "$600" in answer.direct_answer
    assert "AMZN" in answer.direct_answer and "$-200" in answer.direct_answer
    assert "not total-return attribution" in answer.direct_answer


def test_risk_sizing_and_cash_answers_use_saved_profile_and_policy():
    result = [{"tool_name": "portfolio_risk", "status": "complete", "summary": {
        "positions": [{"ticker": "MSFT", "weight": .25}],
        "profile": {"risk_tolerance": 6, "loss_capacity": 5, "annual_withdrawal": 12000, "annual_income_need": 8000},
        "policy": {"status": "approved", "max_single_stock_weight": .20, "minimum_cash_reserve": 15000,
                   "target_allocation": {"cash": .10}},
    }}]
    _, sizing = compose_supported_answer(intent="POSITION_SIZING", question="too large", context=context(),
                                         tool_results=result, deterministic_answer=None)
    assert "20.0%" in sizing.direct_answer and "MSFT" in sizing.direct_answer and "5.0%" in sizing.direct_answer
    _, cash = compose_supported_answer(intent="CASH_RESERVE", question="cash", context=context(),
                                       tool_results=result, deterministic_answer=None)
    assert "$15,000" in cash.direct_answer and "10.0%" in cash.direct_answer


def test_options_gap_is_specific_and_never_returns_capability_status():
    _, answer = compose_supported_answer(
        intent="OPTIONS_EXPIRY", question="enough time", context=context(),
        tool_results=tool({"message": "portfolio risk returned SUCCESS"}), deterministic_answer="portfolio risk returned SUCCESS",
    )
    assert "option symbol" in answer.direct_answer
    assert "portfolio risk returned SUCCESS" not in answer.direct_answer
    assert answer.partial_claims


def test_option_cost_followup_calculates_supplied_ticket_without_saving_it():
    _, answer = compose_supported_answer(
        intent="OPTIONS_COSTS",
        question="AAPL 200C, long 2, expiry 2026-12-18, fill 8.40, bid 8.10, ask 8.60, commission 1.30, theta -0.07",
        context=context(), tool_results=[{"tool_name": "portfolio_risk", "status": "complete", "summary": {"positions": [{"ticker": "AAPL"}]}}],
        deterministic_answer=None,
    )
    assert "$1,680.00" in answer.direct_answer
    assert "$100.00" in answer.direct_answer
    assert "$-14.00 per day" in answer.direct_answer
    assert "not yet saved or market-verified" in answer.direct_answer


def test_risk_efficiency_uses_historical_proxy_before_asking_for_objective():
    results = [
        {"tool_name": "portfolio_risk", "status": "complete", "summary": {
            "profile": {"risk_tolerance": 6, "loss_capacity": 5},
            "positions": [{"ticker": "MSFT", "weight": 1.0}],
        }},
        {"tool_name": "portfolio_backtest", "status": "complete", "summary": {"results": [
            {"key": "current_portfolio", "label": "Current", "annual_return": .12, "volatility": .10, "maximum_drawdown": -.08},
            {"key": "benchmark_spy", "label": "SPY", "annual_return": .10, "volatility": .12, "maximum_drawdown": -.11},
        ]}},
    ]
    _, answer = compose_supported_answer(
        intent="RISK_EFFICIENCY", question="more risk than necessary", context=context(),
        tool_results=results, deterministic_answer=None,
    )
    assert "Return / volatility" in answer.direct_answer
    assert "SPY" in answer.direct_answer
    assert "lower drawdown" in answer.direct_answer


def test_after_tax_index_answer_shows_gross_gap_and_requests_ledger():
    results = [{"tool_name": "portfolio_backtest", "status": "complete", "summary": {"results": [
        {"key": "current_portfolio", "total_return": .14},
        {"key": "benchmark_spy", "label": "SPY", "total_return": .10},
    ]}}]
    _, answer = compose_supported_answer(
        intent="DECISION_VS_INDEX", question="after taxes and fees", context=context(),
        tool_results=results, deterministic_answer=None,
    )
    assert "4.0%" in answer.direct_answer
    assert "maximum combined tax, fee, timing, and trading drag" in answer.direct_answer
    assert "import that ledger" in answer.direct_answer


def test_averaging_down_without_ticker_lists_saved_losers_and_asks_for_size():
    results = [{"tool_name": "portfolio_risk", "status": "complete", "summary": {"positions": [
        {"ticker": "NKE", "weight": .03, "unrealized_gain_loss": -1200},
    ]}}]
    _, answer = compose_supported_answer(
        intent="AVERAGING_DOWN_REVIEW", question="average down", context=context(),
        tool_results=results, deterministic_answer=None,
    )
    assert "NKE" in answer.direct_answer and "$-1,200" in answer.direct_answer
    assert "proposed dollar amount" in answer.direct_answer


def test_target_price_without_ticker_shows_relative_valuation_then_asks_for_method():
    results = [
        {"tool_name": "company_analysis", "status": "partial", "summary": {"message": "ticker required"}},
        {"tool_name": "portfolio_overview", "status": "complete", "summary": {"candidates": [
            {"ticker": "MSFT", "valuation": 62, "opportunity_score": 70},
        ]}},
    ]
    _, answer = compose_supported_answer(
        intent="TARGET_PRICE_REVIEW", question="attractive price", context=context(),
        tool_results=results, deterministic_answer=None,
    )
    assert "MSFT" in answer.direct_answer and "62.0" in answer.direct_answer
    assert "earnings multiple" in answer.direct_answer and "DCF" in answer.direct_answer
