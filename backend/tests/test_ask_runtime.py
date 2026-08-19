from backend.ask_runtime import (
    CandidateType, FULL_COVERAGE_PERCENT, PARTIAL_COVERAGE_PERCENT,
    attach_coverage, build_portfolio_context, classify_candidate,
    parse_scenario_factors, verify_results,
    sanitize_tool_results,
)


def _portfolio(count: int = 57):
    holdings = [{"ticker": f"S{index}", "market_value": index + 1} for index in range(count)]
    return {"id": "p1", "name": "Test", "updated_at": "2026-08-19", "holdings": holdings}


def test_canonical_context_excludes_and_renormalizes_positions():
    portfolio = _portfolio(2)
    portfolio["holdings"] += [
        {"ticker": "PONPX", "market_value": 50},
        {"ticker": "CASH", "market_value": 50},
    ]
    context = build_portfolio_context(portfolio)

    assert context.symbols == ("S0", "S1")
    assert context.excluded_symbols == ("CASH", "PONPX")
    assert context.total_positions == 2
    assert abs(sum(context.normalized_weights.values()) - 1.0) < 1e-9
    assert all(row["ticker"] not in context.portfolio_payload()["holdings"] for row in [])


def test_portfolio_fingerprint_changes_with_request_scoped_holdings():
    original = build_portfolio_context(_portfolio(3))
    changed_payload = _portfolio(3)
    changed_payload["holdings"] = changed_payload["holdings"][:-1]
    changed = build_portfolio_context(changed_payload)
    assert original.version != changed.version


def test_coverage_policy_full_partial_and_blocked():
    context = build_portfolio_context(_portfolio())
    assert FULL_COVERAGE_PERCENT == 90.0
    assert PARTIAL_COVERAGE_PERCENT == 60.0

    full = {}
    attach_coverage(full, context)
    verified = verify_results("DATA_QUALITY", context, [], [full])
    assert verified.status == "SUCCESS"
    assert verified.answer_allowed

    partial = {}
    attach_coverage(partial, context, context.symbols[:50])
    verified = verify_results("DATA_QUALITY", context, [], [partial])
    assert verified.status == "PARTIAL"
    assert verified.answer_allowed

    low = {}
    attach_coverage(low, context, context.symbols[:16])
    verified = verify_results("DATA_QUALITY", context, [], [low])
    assert verified.status == "FAILED"
    assert not verified.answer_allowed


def test_scenario_parser_retains_every_independent_factor():
    cases = {
        "rates rise and AI spending slows": {("interest_rates", "increase"), ("ai_capex", "decrease")},
        "interest rates rose, the economy entered a recession, or AI spending slowed": {
            ("interest_rates", "increase"), ("economic_growth", "decrease"), ("ai_capex", "decrease"),
        },
        "higher yields and weaker consumer demand": {("interest_rates", "increase"), ("economic_growth", "decrease")},
        "inflation falls but unemployment increases": {("inflation", "decrease"), ("unemployment", "increase")},
        "oil rises while the dollar strengthens": {("oil", "increase"), ("us_dollar", "increase")},
    }
    for question, expected in cases.items():
        factors = {(row.factor, row.direction) for row in parse_scenario_factors(question)}
        assert expected <= factors


def test_excluded_asset_leak_and_infeasible_optimizer_block_recommendations():
    portfolio = _portfolio(3)
    portfolio["holdings"].append({"ticker": "CASH", "market_value": 20})
    context = build_portfolio_context(portfolio)
    tool = {
        "tool_name": "portfolio_rebalance_review",
        "status": "partial",
        "summary": {
            "optimizer": {"status": "INFEASIBLE"},
            "candidates": [{"ticker": "CASH"}],
        },
    }
    attach_coverage(tool, context)

    verified = verify_results("PORTFOLIO_ANALYSIS", context, [], [tool])

    assert not verified.recommendation_allowed
    assert verified.optimizer_feasible is False
    assert any("Excluded positions" in row for row in verified.failures)
    assert any("feasible" in row for row in verified.failures)
    sanitized = sanitize_tool_results([{**tool, "summary": {**tool["summary"], "allocations": [{"ticker": "S0"}]}}], verified)
    assert "allocations" not in sanitized[0]["summary"]


def test_candidate_types_distinguish_existing_adds_from_new_positions():
    context = build_portfolio_context(_portfolio(2))
    assert classify_candidate("S0", "ADD", context) == CandidateType.ADD_TO_EXISTING
    assert classify_candidate("NEW", "ADD", context) == CandidateType.NEW_POSITION
    assert classify_candidate("S0", "REDUCE", context) == CandidateType.REDUCE
    assert classify_candidate("S0", "EXIT", context) == CandidateType.EXIT


def test_verifier_rejects_stale_context_and_owned_new_position_label():
    context = build_portfolio_context(_portfolio(2))
    tool = {
        "tool_name": "watchlist_comparison",
        "status": "complete",
        "portfolio_context_version": "different-context",
        "summary": {"candidates": [{"ticker": "S0", "candidate_type": "NEW_POSITION"}]},
    }
    attach_coverage(tool, context)
    tool["portfolio_context_version"] = "different-context"

    verified = verify_results("WATCHLIST_COMPARISON", context, [], [tool])

    assert not verified.recommendation_allowed
    assert any("different portfolio context" in row for row in verified.failures)
    assert any("mislabeled" in row for row in verified.failures)


def test_scenario_verification_blocks_an_unmapped_ai_capex_factor():
    context = build_portfolio_context(_portfolio(3))
    factors = parse_scenario_factors("rates rise and AI spending slows")
    tool = {"tool_name": "portfolio_scenario", "status": "complete", "summary": {
        "supported_scenario_factors": [{"factor": "interest_rates", "direction": "increase"}],
    }}
    attach_coverage(tool, context)
    verified = verify_results("MULTI_SCENARIO", context, factors, [tool])
    assert not verified.scenario_valid
    assert any("ai_capex decrease" in row for row in verified.failures)


def test_infeasible_scenario_optimizer_is_never_exposed_as_a_recommendation():
    context = build_portfolio_context(_portfolio(3))
    factors = parse_scenario_factors("rates rise")
    tool = {"tool_name": "portfolio_scenario", "status": "complete", "summary": {
        "supported_scenario_factors": [{"factor": "interest_rates", "direction": "increase"}],
        "simulation": {"optimizer": {"status": "INFEASIBLE"}, "outcomes": [{"ticker": "S0", "weight": 1.0}]},
    }}
    attach_coverage(tool, context)

    verified = verify_results("MULTI_SCENARIO", context, factors, [tool])
    sanitized = sanitize_tool_results([tool], verified)

    assert verified.optimizer_feasible is False
    assert "outcomes" not in sanitized[0]["summary"]["simulation"]
