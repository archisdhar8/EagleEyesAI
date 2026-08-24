from backend import capability_planner
from backend.ask_orchestration import (
    MAX_REPLANS, MAX_RETRIES, MAX_TOOL_CALLS, actions_for, build_plan,
    execution_state, previous_analysis_context,
)


def test_intent_routing_uses_smallest_approved_tool_set():
    plan = build_plan("What changed in MSFT since my last review?", "research")
    assert plan.intent == "CHANGE"
    assert plan.tools == ("historical_change",)
    assert plan.tickers == ("MSFT",)
    assert len(plan.tools) <= MAX_TOOL_CALLS
    assert plan.limits["max_retries"] == MAX_RETRIES == 0
    assert plan.limits["max_replans"] == MAX_REPLANS == 0


def test_page_context_resolves_pronoun_followup_and_is_controllable():
    plan = build_plan(
        "Does that weaken my thesis?", "research",
        {"ticker": "NVDA", "enabled_context": ["evidence", "thesis"]},
    )
    assert plan.tickers == ("NVDA",)
    assert plan.intent == "THESIS"
    assert "portfolio_intelligence" not in plan.tools


def test_followup_continuity_preserves_comparison_entities():
    plan = build_plan("Which one has the stronger balance sheet?", "research", {},
                      {"intent": "COMPARISON", "tickers": ["MSFT", "AMZN"]})
    assert plan.tickers == ("MSFT", "AMZN")


def test_specialized_intents_do_not_receive_unrelated_tools():
    earnings = build_plan("What changed in AAPL earnings?", "research")
    assert earnings.tools == ("company_analysis",)
    assert "today_attention" not in earnings.tools
    assert "decision_journal" not in earnings.tools


def test_scenario_and_research_ranking_use_minimal_exact_tools():
    scenario = build_plan("Simulate a recession with accelerating inflation and compare the portfolio paths.", "portfolio")
    assert scenario.intent == "SCENARIO"
    assert scenario.tools == ("portfolio_scenario",)
    ranking = build_plan("Which holdings have the strongest and weakest research evidence?", "portfolio")
    assert ranking.intent == "RESEARCH_RANKING"
    assert ranking.tools == ("security_ranking",)


def test_worst_stock_holding_uses_saved_holdings_research_ranking():
    plan = build_plan("what is my worst stock holding", "portfolio")
    assert plan.intent == "RESEARCH_RANKING"
    assert plan.tools == ("security_ranking",)
    assert "stored_evidence" not in plan.tools


def test_best_and_lower_ranking_holdings_use_research_ranking_without_composition():
    question = "what is my best holding? and lower ranking holdings?"
    plan = build_plan(question, "research")
    assert plan.intent == "RESEARCH_RANKING"
    assert plan.tools == ("security_ranking",)
    assert not capability_planner.should_use_compositional_planner(
        question, plan.intent, plan.confidence,
    )


def test_plain_language_concentration_question_uses_full_cached_intelligence():
    plan = build_plan("Where is my portfolio actually concentrated?", "portfolio")
    assert plan.intent == "HIDDEN_RISK"
    assert plan.tools == ("portfolio_intelligence",)
    assert "stored_evidence" not in plan.tools


def test_balanced_rebalance_question_uses_saved_portfolio_analysis():
    plan = build_plan("Why does the Balanced alternative rebalance these holdings?", "portfolio")
    assert plan.intent == "PORTFOLIO_ANALYSIS"
    assert plan.tools == ("portfolio_analysis",)
    assert "stored_evidence" not in plan.tools


def test_benchmark_outlook_and_portfolio_wide_thesis_questions_use_saved_context():
    benchmark = build_plan("Which stocks will outperform SPY and underperform SPY?", "portfolio")
    assert benchmark.intent == "BENCHMARK_OUTLOOK"
    assert benchmark.tools == ("benchmark_outlook",)
    theses = build_plan("Which of my saved theses need review?", "research")
    assert theses.intent == "THESIS"
    assert theses.tools == ("thesis_monitor",)
    assert "stored_evidence" not in theses.tools


def test_move_out_ten_stocks_routes_to_portfolio_rebalance_analysis():
    plan = build_plan("Rebalance the portfolio by identifying the 10 stocks to move out", "portfolio")
    assert plan.intent == "PORTFOLIO_ANALYSIS"
    assert plan.tools == ("portfolio_analysis",)


def test_every_portfolio_starter_prompt_uses_a_bounded_specialized_tool():
    cases = {
        "What are the biggest risks in my saved portfolio?": ("PORTFOLIO_RISK", ("portfolio_risk",)),
        "Simulate a recession with accelerating inflation and compare the portfolio paths.": ("SCENARIO", ("portfolio_scenario",)),
        "Which holdings have the strongest and weakest research evidence?": ("RESEARCH_RANKING", ("security_ranking",)),
        "What changes could improve diversification without silently changing my constraints?": ("PORTFOLIO_ANALYSIS", ("portfolio_analysis",)),
    }
    for prompt, expected in cases.items():
        plan = build_plan(prompt, "portfolio")
        assert (plan.intent, plan.tools) == expected
        assert "stored_evidence" not in plan.tools


def test_explicit_execution_states_and_deep_link_actions():
    assert execution_state("complete") == "SUCCESS"
    assert execution_state("partial") == "PARTIAL"
    assert execution_state("unavailable") == "UNAVAILABLE"
    plan = build_plan("What changed in MSFT?", "research")
    actions = actions_for(plan)
    assert actions[0]["href"] == "/research?view=stocks&ticker=MSFT"
    assert not any(action["href"].startswith("/decisions") for action in actions)

    comparison = actions_for(build_plan("Compare MSFT and AMZN, including portfolio fit.", "research"))
    assert [action["href"] for action in comparison[:2]] == [
        "/research?view=stocks&ticker=MSFT",
        "/research?view=stocks&ticker=AMZN",
    ]


def test_previous_analysis_context_reads_latest_structured_message():
    messages = [
        {"role": "assistant", "structured_content": {"analysis_context": {"tickers": ["AAPL"]}}},
        {"role": "user", "content": "and the other one?"},
        {"role": "assistant", "structured_content": {"analysis_context": {"tickers": ["MSFT", "AMZN"]}}},
    ]
    assert previous_analysis_context(messages)["tickers"] == ["MSFT", "AMZN"]


def test_high_impact_portfolio_question_contracts_and_entity_safety():
    cases = {
        "What are the three strongest opportunities in my portfolio today, and what evidence supports each one?": "OPPORTUNITY_RANKING",
        "Which holding has the weakest investment thesis, and what should I replace it with?": "THESIS_REPLACEMENT",
        "What has materially changed in my portfolio since my last review?": "PORTFOLIO_CHANGE",
        "Which positions are most overvalued relative to their growth and fundamentals?": "VALUATION_RANKING",
        "Where am I taking hidden concentration risk across sectors, themes, and correlated companies?": "HIDDEN_RISK",
        "What would happen to my portfolio if interest rates rose, the economy entered a recession, or AI spending slowed?": "MULTI_SCENARIO",
        "Which watchlist stocks now have a stronger risk-adjusted case than my existing holdings?": "WATCHLIST_COMPARISON",
        "What upcoming earnings reports, economic events, or company catalysts could materially affect my portfolio?": "PORTFOLIO_EVENTS",
        "Which holdings are missing reliable data, and how much should I trust their rankings?": "DATA_QUALITY",
        "Why did this company’s EagleEyes score change, and which inputs contributed most to the change?": "SCORE_ATTRIBUTION",
        "What evidence would invalidate the thesis for each of my largest positions?": "THESIS_INVALIDATION",
        "How should I rebalance the portfolio while minimizing unnecessary turnover, taxes, and trading costs?": "PORTFOLIO_ANALYSIS",
        "Which companies combine improving fundamentals, reasonable valuation, and positive momentum?": "MULTIFACTOR_SCREEN",
        "What are the strongest arguments against EagleEyes’ current top recommendation?": "RECOMMENDATION_COUNTERCASE",
        "If I invested new cash today, where should it go—and why is that better than holding cash?": "CASH_ALLOCATION",
    }
    for question, expected_intent in cases.items():
        plan = build_plan(question, "research", {"portfolio_id": "portfolio-61"})
        assert plan.intent == expected_intent
        assert plan.requires_portfolio
        assert "I" not in plan.tickers
        assert len(plan.tools) <= MAX_TOOL_CALLS


def test_common_uppercase_words_are_not_tickers():
    plan = build_plan("I use AI and ETF research, and THE SEC heading is visible", "research")
    assert plan.tickers == ()


def test_phase8_visual_followup_reuses_registered_analytical_capability() -> None:
    previous = {
        "intent": "PORTFOLIO_RISK",
        "analytical_context": {"active_capabilities": ["portfolio_risk"], "recent_result_ids": ["result_123"]},
    }
    plan = build_plan("Visualize that.", "research", {"portfolio_id": "portfolio-61"}, previous)
    assert plan.intent == "PORTFOLIO_RISK"
    assert plan.tools == ("portfolio_risk",)
    assert plan.requires_portfolio
    refresh = build_plan("Refresh this analysis using the latest verified data.", "research", {"portfolio_id": "portfolio-61"}, previous)
    assert refresh.intent == "PORTFOLIO_RISK"
    assert refresh.tools == ("portfolio_risk",)


def test_phase8_risk_market_and_backtest_followups_use_normal_capability_boundary() -> None:
    risk = build_plan("Add my largest risk contributors.", "research", {"portfolio_id": "portfolio-61"})
    assert risk.tools == ("portfolio_risk",)
    market = build_plan("Compare against the current market regime.", "research", {"portfolio_id": "portfolio-61"})
    assert market.tools == ("market_state",)
    backtest = build_plan("Add a five-year backtest against SPY.", "research", {"portfolio_id": "portfolio-61"})
    assert backtest.tools == ("portfolio_backtest",)
    assert backtest.requires_portfolio


def test_job_status_followup_reuses_conversation_capability_without_job_id() -> None:
    scenario = build_plan("is it done?", "research", {"portfolio_id": "portfolio-61"}, {
        "pending_jobs": [{"job_id": "job-1", "kind": "SIMULATION", "status": "pending"}],
        "analytical_context": {"active_capabilities": ["portfolio_scenario"]},
    })
    assert (scenario.intent, scenario.tools) == ("MULTI_SCENARIO", ("portfolio_scenario",))

    completed_optimizer = build_plan("show the optimizer now", "research", {"portfolio_id": "portfolio-61"}, {
        "analytical_context": {"active_capabilities": ["portfolio_analysis"]},
    })
    assert (completed_optimizer.intent, completed_optimizer.tools) == ("PORTFOLIO_ANALYSIS", ("portfolio_analysis",))
