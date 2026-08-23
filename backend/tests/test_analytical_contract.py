from __future__ import annotations

from datetime import datetime, timezone

from backend import ask_portfolio
from backend.analytical_contract import (
    AnalysisStatus,
    DependencyResult,
    Prerequisite,
    build_entity_coverage,
    build_freshness,
    derive_analysis_status,
)
from backend.ask_runtime import build_portfolio_context


def _portfolio() -> dict:
    return {
        "id": "portfolio-1",
        "name": "Contract fixture",
        "updated_at": "2026-08-20T12:00:00Z",
        "holdings": [
            {"ticker": "AAA", "weight": 0.57},
            {"ticker": "BBB", "weight": 0.40},
            {"ticker": "CASH", "weight": 0.03},
        ],
    }


def test_entity_coverage_reports_40_of_57_without_inventing_full_coverage() -> None:
    requested = [f"E{index:02d}" for index in range(1, 58)]
    rows = [{"ticker": ticker, "score": 71, "drivers": ["growth"]} for ticker in requested[:40]]
    coverage = build_entity_coverage(
        requested, rows,
        ["score", "drivers"],
        weights={ticker: 1 / 57 for ticker in requested},
    )

    assert len(coverage.requested_entities) == 57
    assert len(coverage.evaluated_entities) == 40
    assert len(coverage.missing_entities) == 17
    assert coverage.entity_coverage_percent == 70.2
    assert coverage.weight_coverage_percent == 70.2
    assert coverage.field_coverage_percent == 70.2


def test_freshness_is_bounded_by_oldest_required_input() -> None:
    freshness = build_freshness(
        [("prices", "2026-08-19T20:00:00Z"), ("fundamentals", "2026-08-10T00:00:00Z")],
        calculated_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        stale_after_days=7,
    )

    assert freshness.effective_through == datetime(2026, 8, 10, tzinfo=timezone.utc)
    assert freshness.stale is True
    assert freshness.stale_dependencies == ["fundamentals"]


def test_optional_failure_is_partial_but_required_unavailable_blocks() -> None:
    optional = [
        DependencyResult(name="holdings", required=True, status=AnalysisStatus.SUCCESS),
        DependencyResult(name="news", required=False, status=AnalysisStatus.FAILED, error_class="TimeoutError"),
    ]
    required = [DependencyResult(name="holdings", required=True, status=AnalysisStatus.UNAVAILABLE)]

    assert derive_analysis_status(optional) == AnalysisStatus.PARTIAL
    assert derive_analysis_status(required) == AnalysisStatus.UNAVAILABLE


def test_internal_dependency_error_message_is_never_serialized() -> None:
    dependency = DependencyResult(
        name="provider", required=False, status=AnalysisStatus.FAILED,
        error_class="TimeoutError", error_message_internal="account-specific upstream detail",
    )

    assert dependency.error_message_internal is not None
    assert "error_message_internal" not in dependency.model_dump(mode="json")


def test_required_failure_is_failed_and_missing_prerequisite_is_unavailable() -> None:
    assert derive_analysis_status([
        DependencyResult(name="optimizer", required=True, status=AnalysisStatus.FAILED),
    ]) == AnalysisStatus.FAILED
    assert derive_analysis_status([], prerequisites=[
        Prerequisite(name="thesis", satisfied=False, reason="No saved thesis."),
    ]) == AnalysisStatus.UNAVAILABLE


def test_optimizer_fingerprint_mismatch_and_infeasible_run_withhold_recommendation() -> None:
    portfolio = _portfolio()
    context = build_portfolio_context(portfolio)
    summary = {
        "title": "Latest analysis",
        "optimizer_run": {
            "input_fingerprint": "older-portfolio",
            "model_diagnostics": {"constraint_status": "infeasible"},
            "alternatives": [{"name": "Balanced", "allocations": [{"ticker": "AAA", "target_weight": 0.8}]}],
        },
    }

    result = ask_portfolio._canonical_result(
        "portfolio_analysis", portfolio, summary, "2026-08-20T12:00:00Z", context,
    )

    assert result.status == AnalysisStatus.UNAVAILABLE
    assert result.input_fingerprint == "older-portfolio"
    assert result.verification.recommendation_allowed is False
    assert {row.name for row in result.prerequisites if not row.satisfied} >= {
        "optimizer_input_compatible", "optimizer_feasible", "tax_lots_available",
    }


def test_missing_thesis_is_explicit_prerequisite_not_invented_content() -> None:
    portfolio = _portfolio()
    context = build_portfolio_context(portfolio)
    result = ask_portfolio._canonical_result(
        "thesis_monitor", portfolio,
        {"title": "No thesis", "saved_theses": [], "status": "unavailable", "message": "No saved thesis."},
        "2026-08-20T12:00:00Z", context,
    )

    assert result.status == AnalysisStatus.UNAVAILABLE
    assert result.prerequisites[0].name == "saved_thesis_exists"
    assert result.prerequisites[0].satisfied is False


def test_gemini_disabled_renderer_uses_the_same_canonical_result() -> None:
    portfolio = _portfolio()
    context = build_portfolio_context(portfolio)
    summary = {
        "title": "Latest analysis",
        "optimizer_run": {"model_diagnostics": {"constraint_status": "infeasible"}},
        "method": "cached optimizer",
    }
    analysis = ask_portfolio._canonical_result(
        "portfolio_analysis", portfolio, summary, "2026-08-20T12:00:00Z", context,
    )
    answer = ask_portfolio.compose("PORTFOLIO_ANALYSIS", [{
        "tool_name": "portfolio_analysis",
        "status": analysis.status.value.lower(),
        "analysis_result": analysis.model_dump(mode="json", exclude_none=True),
    }])

    assert answer is not None
    assert "not carry a matching" in answer
    assert "tax-lot coverage" in answer.lower()
    assert "target_weight" not in answer
