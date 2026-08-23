from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from backend import ask_orchestration
from backend.phase4_analytics import (
    TrendDirection,
    build_cash_allocation,
    build_countercase,
    build_data_quality,
    build_fundamental_trend,
    build_material_change_set,
    build_opportunity_candidates,
    build_portfolio_events,
    build_rebalance_contract,
    build_relative_valuation,
    build_replacement_comparisons,
    build_scenario_support,
    build_score_attributions,
    build_thesis_invalidation,
    build_watchlist_dominance,
    portfolio_fit_delta,
)


QUESTIONS_AND_INTENTS = [
    ("What are the three strongest opportunities in my portfolio today, and what evidence supports each one?", "OPPORTUNITY_RANKING"),
    ("Which holding has the weakest investment thesis, and what should I replace it with?", "THESIS_REPLACEMENT"),
    ("What has materially changed in my portfolio since my last review?", "PORTFOLIO_CHANGE"),
    ("Which positions are most overvalued relative to their growth and fundamentals?", "VALUATION_RANKING"),
    ("Where am I taking hidden concentration risk across sectors, themes, and correlated companies?", "HIDDEN_RISK"),
    ("What would happen to my portfolio if interest rates rose, the economy entered a recession, or AI spending slowed?", "MULTI_SCENARIO"),
    ("Which watchlist stocks now have a stronger risk-adjusted case than my existing holdings?", "WATCHLIST_COMPARISON"),
    ("What upcoming earnings reports, economic events, or company catalysts could materially affect my portfolio?", "PORTFOLIO_EVENTS"),
    ("Which holdings are missing reliable data, and how much should I trust their rankings?", "DATA_QUALITY"),
    ("Why did this company’s EagleEyes score change, and which inputs contributed most to the change?", "SCORE_ATTRIBUTION"),
    ("What evidence would invalidate the thesis for each of my largest positions?", "THESIS_INVALIDATION"),
    ("How should I rebalance the portfolio while minimizing unnecessary turnover, taxes, and trading costs?", "PORTFOLIO_ANALYSIS"),
    ("Which companies combine improving fundamentals, reasonable valuation, and positive momentum?", "MULTIFACTOR_SCREEN"),
    ("What are the strongest arguments against EagleEyes’ current top recommendation?", "RECOMMENDATION_COUNTERCASE"),
    ("If I invested new cash today, where should it go—and why is that better than holding cash?", "CASH_ALLOCATION"),
]


def period(ticker: str, offset: int, revenue: float, eps: float, fcf: float, operating: float,
           debt: float = 20, assets: float = 100, shares: float = 10) -> dict:
    date = datetime.now(timezone.utc) - timedelta(days=(2 - offset) * 90)
    return {"ticker": ticker, "period_end": date.date().isoformat(), "data_quality_score": .9, "metrics": {
        "revenue": revenue, "eps_diluted": eps, "free_cash_flow": fcf,
        "operating_income": operating, "total_debt": debt, "total_assets": assets,
        "cash": 10, "shares_diluted": shares,
    }}


def price_rows(ticker: str, start: float = 100, drift: float = .001) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    values = []
    price = start
    for index in range(180):
        price *= 1 + drift + math.sin(index / 7) * .004
        values.append({"ticker": ticker, "date": (today - timedelta(days=179 - index)).isoformat(), "close": price})
    return values


def bundle() -> dict:
    fundamentals = [
        period("AAA", 0, 100, 2, 10, 15), period("AAA", 1, 112, 2.5, 13, 19), period("AAA", 2, 130, 3.4, 18, 25),
        period("BBB", 0, 100, 5, 15, 20), period("BBB", 1, 99, 4.5, 13, 18), period("BBB", 2, 95, 4, 10, 15),
        period("CAND", 0, 90, 1.5, 8, 12), period("CAND", 1, 105, 2.3, 12, 18), period("CAND", 2, 130, 4, 20, 28),
    ]
    return {
        "fundamentals": fundamentals,
        "prices": price_rows("AAA", 100, .001) + price_rows("BBB", 80, -.0002) + price_rows("CAND", 70, .0012),
        "securities": [
            {"ticker": "AAA", "sector": "Technology"}, {"ticker": "BBB", "sector": "Utilities"},
            {"ticker": "CAND", "sector": "Healthcare"},
        ],
    }


def holdings() -> list[dict]:
    return [
        {"ticker": "AAA", "weight": .65, "health_score": 75, "fundamental_score": 82,
         "valuation_score": 60, "momentum_score": 70, "risk_contribution": .55,
         "data_confidence": "High", "thesis_status": "ACTIVE"},
        {"ticker": "BBB", "weight": .35, "health_score": 42, "fundamental_score": 50,
         "valuation_score": 65, "momentum_score": 35, "risk_contribution": .25,
         "data_confidence": "Medium", "thesis_status": "ACTIVE"},
    ]


@pytest.mark.parametrize("question,intent", QUESTIONS_AND_INTENTS)
def test_all_15_acceptance_questions_route_to_their_deterministic_capability(question: str, intent: str):
    plan = ask_orchestration.build_plan(question, "portfolio", {"portfolio_id": "portfolio-1"})
    assert plan.intent == intent


def test_opportunity_is_eligible_typed_setup_not_repackaged_health_score():
    candidates = build_opportunity_candidates(holdings(), bundle())
    best = next(row for row in candidates if row["eligibility"]["eligible"])
    source = next(row for row in holdings() if row["ticker"] == best["ticker"])
    assert best["opportunity_score"] != source["health_score"]
    assert best["fundamental_trend"]["direction"] in {"IMPROVING", "STABLE", "DECLINING"}
    assert best["supporting_evidence"]


def test_replacement_never_treats_owned_candidate_as_new_and_requires_multidimensional_dominance():
    research = [
        {"ticker": "AAA", "candidate_eligibility": "ADD_TO_EXISTING", "fundamental_score": 95,
         "valuation_score": 90, "technical_score": 90, "confidence": 90},
        {"ticker": "CAND", "candidate_eligibility": "NEW_POSITION", "fundamental_score": 85,
         "valuation_score": 80, "technical_score": 80, "confidence": 85},
    ]
    dominance = build_watchlist_dominance(research, holdings(), bundle())
    assert next(row for row in dominance if row["candidate"] == "AAA")["candidate_type"] == "ADD_TO_EXISTING"
    comparisons = build_replacement_comparisons([{"ticker": "BBB", "summary": "Weak thesis"}], dominance, holdings(), bundle())
    assert all(row["candidate"] != "AAA" for row in comparisons)
    assert all(row["replacement_dominance"] in {"REPLACEMENT_SUPPORTED", "NO_CLEAR_REPLACEMENT"} for row in comparisons)


def test_change_set_distinguishes_no_baseline_from_no_material_change():
    missing = build_material_change_set([], holdings(), baseline_available=False, baseline_identity=None)
    quiet = build_material_change_set([], holdings(), baseline_available=True, baseline_identity={"id": "old"})
    assert missing["baseline_status"] == "NO_BASELINE"
    assert quiet["baseline_status"] == "NO_MATERIAL_CHANGE"


def test_relative_valuation_does_not_make_high_pe_automatically_most_overvalued_when_growth_supports_it():
    rows = build_relative_valuation(holdings(), bundle())
    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["AAA"]["inputs"]["pe"] > by_ticker["BBB"]["inputs"]["pe"]
    assert by_ticker["AAA"]["growth_support"] > by_ticker["BBB"]["growth_support"]
    assert by_ticker["AAA"]["relative_value_gap"] < by_ticker["BBB"]["relative_value_gap"]


def test_incremental_portfolio_fit_reports_before_after_concentration_and_correlation():
    fit = portfolio_fit_delta("CAND", holdings(), bundle(), allocation=.05)
    assert fit.sector_weight_before == 0
    assert fit.sector_weight_after is not None and fit.sector_weight_after > 0
    assert fit.concentration_effect == "WORSENS"


def test_scenario_registry_keeps_ai_capex_as_qualitative_exposure_not_fake_simulation():
    simulation = {"model_version": "sim-v1", "input": {"scenario": {"rate_state": "tightening", "economic_state": "recession"}}}
    intelligence = {"economic_dependencies": [{"factor": "AI_INFRASTRUCTURE_DEMAND", "holdings": ["AAA"],
                                                 "mapped_portfolio_weight": .65}]}
    support = build_scenario_support(simulation, intelligence)
    ai = next(row for row in support if row["factor"] == "ai_capex")
    assert ai["support_type"] == "QUALITATIVE_EXPOSURE_STRESS"
    assert "no simulated loss magnitude" in ai["methodology"].lower()


def test_watchlist_dominance_is_a_defined_composite_with_risk_and_fit():
    research = [{"ticker": "CAND", "candidate_eligibility": "NEW_POSITION", "fundamental_score": 90,
                 "valuation_score": 80, "technical_score": 85, "confidence": 90}]
    result = build_watchlist_dominance(research, holdings(), bundle())[0]
    assert result["decision_score"] is not None
    assert result["diversification_effect"]["candidate_portfolio_correlation"] is not None
    assert result["dominance_status"] in {"DOMINATES", "NO_CLEAR_DOMINANCE"}


def test_event_result_tracks_materiality_and_category_completeness_separately():
    events = [{"title": "AAA earnings", "event_type": "EARNINGS", "tickers": ["AAA"],
               "starts_at": "2026-09-01T20:00:00Z", "verified_at": "2026-08-20T00:00:00Z", "provider": "fixture"}]
    result = build_portfolio_events(events, holdings())
    assert result["events"][0]["affected_portfolio_weight"] == .65
    assert result["events"][0]["estimated_materiality"] == "HIGH"
    assert result["category_completeness"]["earnings"] == "AVAILABLE"
    assert result["complete"] is False


def test_data_quality_uses_eligibility_not_symbol_presence():
    incomplete_bundle = bundle()
    incomplete_bundle["fundamentals"] = [row for row in incomplete_bundle["fundamentals"] if row["ticker"] != "BBB"]
    quality = {row["ticker"]: row for row in build_data_quality(holdings(), incomplete_bundle)}
    assert quality["BBB"]["trust_classification"] == "NOT_RANKABLE"
    assert quality["BBB"]["rankable"] is False


def test_score_attribution_component_impacts_reconcile_with_total_delta():
    row = {**holdings()[0], "change": 3.5, "component_changes": {"fundamentals": 5, "valuation": 5,
           "momentum": 5, "risk_contribution": -.0125}, "baseline_timestamp": "2026-08-01T00:00:00Z"}
    result = build_score_attributions([row])[0]
    assert result["comparable_baseline"] is True
    assert abs(result["unexplained_delta"]) < 1e-8
    assert sum(item["score_impact"] for item in result["component_deltas"]) == pytest.approx(result["total_delta"])


def test_thesis_invalidation_never_invents_breakers_when_thesis_is_missing():
    result = build_thesis_invalidation([], holdings())
    assert all(row["explicit_breakers"] == [] for row in result)
    assert all(row["missing_evidence"] == ["saved_thesis"] for row in result)


def test_rebalance_never_claims_tax_awareness_without_tax_lots_or_actionability_without_match():
    optimizer = {"portfolio_context_version": "old", "alternatives": [{"name": "Balanced", "constraint_status": "FEASIBLE",
                  "allocations": {"AAA": .5, "BBB": .5}, "tax": {"optimized": True}}]}
    result = build_rebalance_contract(optimizer, "current", holdings())
    assert result["actionable"] is False
    assert result["tax_aware"] is False
    assert result["target_weights"] is None


def test_declining_fundamentals_do_not_count_as_improving_even_when_current_level_is_strong():
    trend = build_fundamental_trend([period("AAA", 0, 150, 5, 20, 30), period("AAA", 1, 130, 4, 15, 23),
                                     period("AAA", 2, 105, 2.5, 9, 15)])
    assert trend.direction == TrendDirection.DECLINING


def test_countercase_has_stable_recommendation_identity_and_specific_evidence():
    opportunities = build_opportunity_candidates(holdings(), bundle())
    intelligence = {"economic_dependencies": [{"factor": "AI_INFRASTRUCTURE_DEMAND", "holdings": ["AAA"],
                                                 "mechanism": "AI spending", "strength": "HIGH"}]}
    first = build_countercase(opportunities, holdings(), intelligence, "fingerprint")
    second = build_countercase(opportunities, holdings(), intelligence, "fingerprint")
    assert first["recommendation_id"] == second["recommendation_id"]
    assert first["strongest_counterarguments"]


def test_cash_allocation_can_hold_cash_and_refuses_to_claim_edge_without_sourced_hurdle():
    no_hurdle = build_cash_allocation([], {})
    with_hurdle = build_cash_allocation([], {"cash_hurdle_yield": .04})
    assert no_hurdle["recommended_action"] == "NO_CLEAR_EDGE"
    assert no_hurdle["cash_hurdle"]["available"] is False
    assert with_hurdle["recommended_action"] == "HOLD_CASH"
