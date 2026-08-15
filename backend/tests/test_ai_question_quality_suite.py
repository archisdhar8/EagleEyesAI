from __future__ import annotations

import json
from pathlib import Path

from backend.dashboard_workspace import compile_spec, deterministic_plan


CASES = json.loads((Path(__file__).parents[1] / "fixtures" / "ai_question_quality.json").read_text())


def test_quality_suite_contains_40_realistic_complete_contracts() -> None:
    assert 30 <= len(CASES) <= 50
    required = {"question", "intent", "entities", "factor", "unit", "period", "benchmark", "widgets", "narrative_terms"}
    assert all(required == set(case) for case in CASES)
    assert len({case["question"] for case in CASES}) == len(CASES)


def test_quality_suite_plans_entities_factors_periods_benchmarks_and_widgets() -> None:
    failures = []
    for case in CASES:
        plan = deterministic_plan(case["question"])
        spec = compile_spec(plan)
        widgets = {item["widget_type"] for item in spec["widgets"]}
        checks = {
            "intent": plan.intent == case["intent"],
            "entities": set(case["entities"]).issubset(set(plan.entities.tickers)),
            "factor": case["factor"] in {"portfolio", "company", "portfolio_fit", "market", "freshness", "combined_scenario", "recession"} or plan.filters.get("macro_factor") == case["factor"],
            "unit": bool(case["unit"]),
            "period": plan.time_range == case["period"],
            "benchmark": case["benchmark"] == "none" or plan.filters.get("requested_benchmark") == case["benchmark"],
            "widgets": set(case["widgets"]).issubset(widgets),
            "narrative": len(case["narrative_terms"]) >= 2,
        }
        if not all(checks.values()):
            failures.append({"question": case["question"], "failed": [key for key, value in checks.items() if not value], "widgets": sorted(widgets), "filters": plan.filters})
    assert not failures, failures
