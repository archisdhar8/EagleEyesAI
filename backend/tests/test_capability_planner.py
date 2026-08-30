from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.analytical_contract import (
    AnalysisResult, AnalysisStatus, Coverage, Freshness, JobReference,
    VerificationResult,
)
from backend import capability_planner as planner


PORTFOLIO_ID = "portfolio-1"


def entities(*tickers: str, portfolio: bool = True) -> list[planner.ResolvedEntity]:
    rows = [planner.ResolvedEntity(kind=planner.EntityKind.SECURITY, canonical_id=ticker) for ticker in tickers]
    if portfolio:
        rows.append(planner.ResolvedEntity(kind=planner.EntityKind.PORTFOLIO, canonical_id=PORTFOLIO_ID))
    return rows


MIXED_QUESTIONS = [
    ("Compare MSFT and Amazon and tell me which fits my portfolio better.", ("MSFT", "AMZN"), {"company_comparison", "portfolio_risk"}),
    ("Which of my holdings has strong fundamentals but is hurting diversification?", ("MSFT",), {"company_analysis", "portfolio_intelligence"}),
    ("Given current rates and growth conditions, where is my portfolio most exposed?", (), {"macro_state", "portfolio_intelligence"}),
    ("Which prediction-market developments matter most for my holdings?", (), {"prediction_markets", "portfolio_risk"}),
    ("Is my portfolio positioned well for the current market regime?", (), {"market_state", "portfolio_risk"}),
    ("Recession odds are rising. Does the macro data agree, and which holdings are most exposed?", (), {"macro_state", "prediction_markets", "portfolio_intelligence"}),
    ("What changed for MSFT since I last reviewed it?", ("MSFT",), {"historical_change"}),
    ("If rates fall but AI capex slows, which of my holdings benefit or suffer?", (), {"portfolio_scenario"}),
    ("What is your strongest current opportunity and what is the best argument against it?", (), {"portfolio_overview", "recommendation_countercase"}),
    ("Backtest my current portfolio against SPY and tell me whether the extra return justified the drawdown.", (), {"portfolio_risk", "portfolio_backtest"}),
    ("Which holdings look expensive while fundamentals are weakening?", (), {"valuation_ranking", "multifactor_screen"}),
    ("What has changed in my portfolio and macro environment since my last review?", (), {"macro_state", "portfolio_change", "historical_change"}),
    ("Compare MSFT versus AMZN valuation.", ("MSFT", "AMZN"), {"company_comparison"}),
    ("Which watchlist stock would reduce my hidden portfolio risk?", (), {"watchlist_comparison", "portfolio_intelligence"}),
    ("What if I invest new cash instead of selling anything in my portfolio?", (), {"cash_allocation"}),
    ("How should I rebalance my portfolio without changing constraints?", (), {"portfolio_analysis"}),
    ("Run deep research on MSFT.", ("MSFT",), {"company_research"}),
    ("Given rising inflation, where is my portfolio vulnerable?", (), {"macro_state", "portfolio_intelligence"}),
    ("Breadth is weakening; is my portfolio positioned for this market regime?", (), {"market_state", "portfolio_risk"}),
    ("Which Kalshi probability changes matter for my holdings?", (), {"prediction_markets", "portfolio_risk"}),
    ("Compare MSFT and AMZN while recession risk rises.", ("MSFT", "AMZN"), {"company_comparison", "macro_state"}),
    ("How do MSFT earnings affect risk in my portfolio?", ("MSFT",), {"company_analysis", "portfolio_risk"}),
    ("Show portfolio data quality before ranking my holdings.", (), {"data_quality", "portfolio_risk"}),
    ("Which upcoming events or catalysts matter for my portfolio?", (), {"portfolio_events"}),
    ("What changed in the MSFT score?", ("MSFT",), {"score_attribution", "historical_change"}),
    ("What would invalidate the thesis for my largest portfolio holding?", (), {"thesis_invalidation", "portfolio_risk"}),
    ("What replacement would improve my portfolio risk?", (), {"thesis_replacement", "portfolio_risk"}),
    ("Use my decision journal retrospective when assessing MSFT.", ("MSFT",), {"decision_journal"}),
    ("What matters today for my portfolio?", (), {"today_attention"}),
    ("How does my portfolio compare with the SPY benchmark?", (), {"benchmark_outlook"}),
    ("If oil rises, what happens to my current portfolio?", (), {"portfolio_scenario"}),
    ("Do recession probabilities and macro conditions identify the same portfolio vulnerability?", (), {"prediction_markets", "macro_state", "portfolio_intelligence"}),
]


@pytest.mark.parametrize(("question", "tickers", "expected"), MIXED_QUESTIONS)
def test_mixed_domain_regression_corpus(question: str, tickers: tuple[str, ...], expected: set[str]) -> None:
    plan = planner.deterministic_capability_plan(question, entities(*tickers), portfolio_id=PORTFOLIO_ID)
    planner.validate_capability_plan(plan, {
        "portfolio_id": PORTFOLIO_ID, "permissions": "owner_scoped_read_only",
        "resolved_entity_ids": [row.canonical_id for row in plan.entities],
    })
    names = {step.capability for step in plan.steps}
    assert expected <= names
    assert len(plan.steps) <= planner.MAX_SYNCHRONOUS_CAPABILITIES + planner.MAX_HEAVY_JOBS
    assert sum(planner.CAPABILITY_REGISTRY[name].heavy_job for name in names) <= planner.MAX_HEAVY_JOBS


def base_plan(capability: str = "macro_state") -> planner.CapabilityPlan:
    descriptor = planner.CAPABILITY_REGISTRY.get(capability)
    output = descriptor.output_schema if descriptor else "Arbitrary"
    return planner.CapabilityPlan(goal="test", entities=[], steps=[planner.CapabilityPlanStep(
        step_id="step", capability=capability, reason_code=planner.ReasonCode.PRIMARY_QUESTION,
        expected_output=output,
    )])


@pytest.mark.parametrize("mutator,expected", [
    (lambda plan: setattr(plan.steps[0], "capability", "run_arbitrary_python"), "unknown_capability"),
    (lambda plan: plan.steps[0].inputs.update({"python": "print(1)"}), "arbitrary_execution_input"),
    (lambda plan: plan.steps[0].inputs.update({"sql": "select *"}), "arbitrary_execution_input"),
    (lambda plan: plan.steps[0].inputs.update({"api_url": "https://attacker.example"}), "arbitrary_execution_input"),
    (lambda plan: setattr(plan.steps[0], "expected_output", "InventedResult"), "output_schema_mismatch"),
    (lambda plan: plan.steps[0].inputs.update({"entity_ids": ["FAKE"]}), "unresolved_entity"),
])
def test_adversarial_plan_is_rejected(mutator, expected: str) -> None:
    plan = base_plan(); mutator(plan)
    with pytest.raises(planner.PlanValidationError) as exc:
        planner.validate_capability_plan(plan, {"resolved_entity_ids": ["MSFT"]})
    assert expected in str(exc.value)


def test_twenty_capabilities_are_rejected() -> None:
    plan = base_plan()
    plan.steps = [plan.steps[0].model_copy(update={"step_id": f"step_{index}"}) for index in range(20)]
    with pytest.raises(planner.PlanValidationError, match="too_many_plan_nodes"):
        planner.validate_capability_plan(plan)


def test_cycle_is_rejected() -> None:
    plan = planner.CapabilityPlan(goal="cycle", steps=[
        planner.CapabilityPlanStep(step_id="one", capability="macro_state", depends_on=["two"], reason_code="PRIMARY_QUESTION", expected_output="MacroStateResult"),
        planner.CapabilityPlanStep(step_id="two", capability="market_state", depends_on=["one"], reason_code="SUPPORTING_CONTEXT", expected_output="MarketStateResult"),
    ])
    with pytest.raises(planner.PlanValidationError, match="cycle_or_excessive_depth"):
        planner.validate_capability_plan(plan)


def test_more_than_one_heavy_job_is_rejected() -> None:
    plan = planner.CapabilityPlan(goal="heavy", entities=entities("MSFT"), portfolio_context_required=True, steps=[
        planner._step("portfolio_backtest", entities("MSFT"), planner.ReasonCode.PRIMARY_QUESTION),
        planner._step("company_research", entities("MSFT"), planner.ReasonCode.SUPPORTING_CONTEXT),
    ])
    with pytest.raises(planner.PlanValidationError, match="too_many_heavy_jobs"):
        planner.validate_capability_plan(plan, {"portfolio_id": PORTFOLIO_ID})


def test_unsupported_scenario_is_rejected() -> None:
    rows = entities()
    plan = planner.CapabilityPlan(goal="unsupported scenario", entities=rows, portfolio_context_required=True,
        steps=[planner._step("portfolio_scenario", rows, planner.ReasonCode.SCENARIO_INPUT, factors=["meteor_strike"])])
    with pytest.raises(planner.PlanValidationError, match="unsupported_scenario_factor"):
        planner.validate_capability_plan(plan, {"portfolio_id": PORTFOLIO_ID})


def test_invented_plan_entity_is_rejected() -> None:
    plan = base_plan(); plan.entities = [planner.ResolvedEntity(kind="SECURITY", canonical_id="FAKE")]
    with pytest.raises(planner.PlanValidationError, match="planner_invented_entity"):
        planner.validate_capability_plan(plan, {"resolved_entity_ids": ["MSFT"]})


def result(capability: str, status: AnalysisStatus, *, message: str, job: bool = False) -> AnalysisResult:
    now = datetime.now(timezone.utc)
    return AnalysisResult(capability=capability, calculation_version="test-v1", input_fingerprint=capability,
        status=status, data={"summary": message}, coverage=Coverage.not_tracked(), freshness=Freshness(calculated_at=now),
        limitations=[] if status == AnalysisStatus.SUCCESS else [f"{capability} limitation"],
        verification=VerificationResult(passed=status != AnalysisStatus.FAILED,
            answer_allowed=status not in {AnalysisStatus.FAILED, AnalysisStatus.UNAVAILABLE}, recommendation_allowed=False),
        job=JobReference(id="job-1", kind="BACKTEST") if job else None)


def test_partial_failure_preserves_successful_evidence() -> None:
    rows = entities()
    plan = planner.deterministic_capability_plan(
        "Recession odds are rising. Does macro data agree and which holdings are exposed?", rows,
        portfolio_id=PORTFOLIO_ID,
    )
    composed = planner.compose_results("question", plan, [
        result("macro_state", AnalysisStatus.SUCCESS, message="Growth is weakening."),
        result("prediction_markets", AnalysisStatus.UNAVAILABLE, message="No prediction coverage."),
        result("portfolio_intelligence", AnalysisStatus.SUCCESS, message="Cyclical exposure is concentrated."),
    ])
    assert composed.overall_status == AnalysisStatus.PARTIAL
    rendered = planner.render_composed(composed)
    assert "Growth is weakening" in rendered
    assert "prediction_markets: UNAVAILABLE" in rendered


def test_required_failure_with_another_success_keeps_narrow_partial_answer() -> None:
    rows = entities()
    plan = planner.CapabilityPlan(
        goal="rank valuation and show risk", entities=rows, portfolio_context_required=True,
        steps=[
            planner._step("valuation_ranking", rows, planner.ReasonCode.PRIMARY_QUESTION),
            planner._step("portfolio_risk", rows, planner.ReasonCode.PRIMARY_QUESTION),
        ],
    )
    composed = planner.compose_results("question", plan, [
        result("valuation_ranking", AnalysisStatus.FAILED, message="valuation failed"),
        result("portfolio_risk", AnalysisStatus.SUCCESS, message="NVDA is the largest risk contributor."),
    ])
    assert composed.overall_status == AnalysisStatus.PARTIAL
    rendered = planner.render_composed(composed)
    assert "NVDA is the largest risk contributor" in rendered
    assert "valuation_ranking: FAILED" in rendered


def test_composed_answer_hides_internal_adapter_and_registry_diagnostics() -> None:
    rows = entities()
    plan = planner.CapabilityPlan(
        goal="question", entities=rows, portfolio_context_required=True,
        steps=[planner._step("portfolio_risk", rows, planner.ReasonCode.PRIMARY_QUESTION)],
    )
    composed = planner.compose_results("question", plan, [
        result("portfolio_risk", AnalysisStatus.PARTIAL, message="Useful saved risk evidence."),
    ])
    composed.limitations.extend([
        "Converted through the legacy AnalysisResult adapter; unavailable metadata was not fabricated.",
        "Every component was selected from the versioned registry.",
    ])

    rendered = planner.render_composed(composed)

    assert "Useful saved risk evidence" in rendered
    assert "legacy AnalysisResult adapter" not in rendered
    assert "versioned registry" not in rendered


def test_heavy_pending_keeps_available_portfolio_risk() -> None:
    rows = entities()
    plan = planner.deterministic_capability_plan(
        "Backtest my current portfolio and assess drawdown risk.", rows, portfolio_id=PORTFOLIO_ID,
    )
    composed = planner.compose_results("question", plan, [
        result("portfolio_risk", AnalysisStatus.SUCCESS, message="Top-five weight is concentrated."),
        result("portfolio_backtest", AnalysisStatus.PENDING, message="Backtest queued.", job=True),
    ])
    assert composed.overall_status == AnalysisStatus.PARTIAL
    assert composed.pending_jobs[0].id == "job-1"
    assert "Top-five weight" in planner.render_composed(composed)


def test_follow_up_uses_structured_entities_not_chat_prose() -> None:
    context = planner.ConversationAnalyticalContext(
        active_entities=entities("MSFT", "AMZN", portfolio=False), active_comparison=["MSFT", "AMZN"],
        active_capabilities=["company_comparison"], recent_result_ids=["result_previous"],
    )
    resolved = planner.resolve_entities("Which one fits my portfolio better?", [], portfolio_id=PORTFOLIO_ID, previous=context)
    plan = planner.deterministic_capability_plan("Which one fits my portfolio better?", resolved,
                                                 portfolio_id=PORTFOLIO_ID, conversation=context)
    assert {row.canonical_id for row in plan.entities} >= {"MSFT", "AMZN"}
    assert {step.capability for step in plan.steps} == {"company_comparison", "portfolio_risk"}


def test_model_planner_repairs_schema_only_once() -> None:
    planner._PLAN_CACHE.clear(); calls = []
    valid = base_plan().model_dump(mode="json")
    def model_call(payload):
        calls.append(payload)
        return {"malformed": True} if len(calls) == 1 else valid
    plan, telemetry = planner.plan_with_model("unique macro repair query", [], portfolio_id=None,
                                               model_call=model_call, model_name="test-model")
    assert plan.steps[0].capability == "macro_state"
    assert telemetry.repair_attempted is True
    assert len(calls) == 2


def test_plan_cache_never_caches_analytical_results() -> None:
    planner._PLAN_CACHE.clear(); calls = []
    valid = base_plan().model_dump(mode="json")
    def model_call(_): calls.append(1); return valid
    first, _ = planner.plan_with_model("cache structure query", [], portfolio_id=None, model_call=model_call, model_name="m")
    second, telemetry = planner.plan_with_model("cache structure query", [], portfolio_id=None, model_call=model_call, model_name="m")
    assert first == second and len(calls) == 1 and telemetry.cache_hit
    assert not hasattr(second, "component_results")


def test_simple_known_route_bypasses_planner() -> None:
    assert planner.should_use_compositional_planner("What is the macro state?", "MACRO_STATE", .98) is False
    assert planner.should_use_compositional_planner("Compare MSFT and AMZN.", "COMPARISON", .98) is False


def test_registry_has_no_execution_callables_and_is_versioned() -> None:
    assert planner.CAPABILITY_REGISTRY_VERSION == "capability-registry-v1"
    assert len(planner.CAPABILITY_REGISTRY) >= 25
    assert all(not callable(value) for descriptor in planner.CAPABILITY_REGISTRY.values()
               for value in descriptor.model_dump().values())
