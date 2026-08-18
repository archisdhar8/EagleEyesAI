from backend.ask_orchestration import (
    MAX_REPLANS, MAX_RETRIES, MAX_TOOL_CALLS, actions_for, build_plan,
    execution_state, previous_analysis_context,
)


def test_intent_routing_uses_smallest_approved_tool_set():
    plan = build_plan("What changed in MSFT since my last review?", "research")
    assert plan.intent == "CHANGE"
    assert plan.tools == ("evidence_changes", "thesis_monitor")
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
    assert earnings.tools == ("earnings_intelligence", "thesis_monitor")
    assert "today_attention" not in earnings.tools
    assert "decision_journal" not in earnings.tools


def test_scenario_and_research_ranking_use_minimal_exact_tools():
    scenario = build_plan("Simulate a recession with accelerating inflation and compare the portfolio paths.", "portfolio")
    assert scenario.intent == "SCENARIO"
    assert scenario.tools == ("portfolio_scenario",)
    ranking = build_plan("Which holdings have the strongest and weakest research evidence?", "portfolio")
    assert ranking.intent == "RESEARCH_RANKING"
    assert ranking.tools == ("security_ranking",)


def test_balanced_rebalance_question_uses_saved_portfolio_analysis():
    plan = build_plan("Why does the Balanced alternative rebalance these holdings?", "portfolio")
    assert plan.intent == "PORTFOLIO_ANALYSIS"
    assert plan.tools == ("portfolio_analysis",)
    assert "stored_evidence" not in plan.tools


def test_explicit_execution_states_and_deep_link_actions():
    assert execution_state("complete") == "SUCCESS"
    assert execution_state("partial") == "PARTIAL"
    assert execution_state("unavailable") == "UNAVAILABLE"
    plan = build_plan("What changed in MSFT?", "research")
    actions = actions_for(plan)
    assert actions[0]["href"] == "/research?view=stocks&ticker=MSFT"
    assert any(action["href"].startswith("/decisions?ticker=MSFT") for action in actions)


def test_previous_analysis_context_reads_latest_structured_message():
    messages = [
        {"role": "assistant", "structured_content": {"analysis_context": {"tickers": ["AAPL"]}}},
        {"role": "user", "content": "and the other one?"},
        {"role": "assistant", "structured_content": {"analysis_context": {"tickers": ["MSFT", "AMZN"]}}},
    ]
    assert previous_analysis_context(messages)["tickers"] == ["MSFT", "AMZN"]
