"""Offline reusable Phase 7 planner regression suite.

This evaluates plan structure and safety, not financial result availability.
Canonical capability suites remain responsible for analytical quality.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import capability_planner as planner


QUESTIONS = [
    ("Compare MSFT and AMZN and tell me which fits my portfolio better.", ["MSFT", "AMZN"]),
    ("Which of my holdings has strong fundamentals but is hurting diversification?", ["MSFT"]),
    ("Given current rates and growth conditions, where is my portfolio most exposed?", []),
    ("Which prediction-market developments matter most for my holdings?", []),
    ("Is my portfolio positioned well for the current market regime?", []),
    ("Recession odds are rising. Does macro data agree, and which holdings are most exposed?", []),
    ("What changed for MSFT since I last reviewed it?", ["MSFT"]),
    ("If rates fall but AI capex slows, which holdings benefit or suffer?", []),
    ("What is the strongest opportunity and best argument against it?", []),
    ("Backtest my current portfolio against SPY and assess its drawdown.", []),
    ("Which holdings look expensive while fundamentals are weakening?", []),
    ("What changed in my portfolio and macro environment since my last review?", []),
    ("Compare MSFT and AMZN valuation.", ["MSFT", "AMZN"]),
    ("Which watchlist stock would reduce my hidden portfolio risk?", []),
    ("What if I invest new cash instead of selling?", []),
    ("Rebalance my portfolio without changing constraints.", []),
    ("Run deep research on MSFT.", ["MSFT"]),
    ("Given rising inflation, where is my portfolio vulnerable?", []),
    ("Breadth is weakening; is my portfolio positioned for this market regime?", []),
    ("Which Kalshi probability changes matter for my holdings?", []),
    ("Compare MSFT and AMZN while recession risk rises.", ["MSFT", "AMZN"]),
    ("How do MSFT earnings affect risk in my portfolio?", ["MSFT"]),
    ("Show data quality before ranking my holdings.", []),
    ("Which upcoming catalysts matter for my portfolio?", []),
    ("What changed in the MSFT score?", ["MSFT"]),
    ("What would invalidate the thesis for my largest holding?", []),
    ("What replacement would improve portfolio risk?", []),
    ("Use my decision journal retrospective when assessing MSFT.", ["MSFT"]),
    ("What matters today for my portfolio?", []),
    ("How does my portfolio compare with the SPY benchmark?", []),
    ("If oil rises, what happens to my portfolio?", []),
    ("Do recession probabilities and macro conditions identify the same vulnerability?", []),
]


def main() -> None:
    portfolio_id = "phase7-eval-portfolio"
    rows = []
    for question, tickers in QUESTIONS:
        entities = [planner.ResolvedEntity(kind="SECURITY", canonical_id=ticker) for ticker in tickers]
        entities.append(planner.ResolvedEntity(kind="PORTFOLIO", canonical_id=portfolio_id))
        try:
            plan = planner.deterministic_capability_plan(question, entities, portfolio_id=portfolio_id)
            planner.validate_capability_plan(plan, {
                "portfolio_id": portfolio_id, "permissions": "owner_scoped_read_only",
                "resolved_entity_ids": [row.canonical_id for row in entities],
            })
            verdict = "PASS"
            error = None
        except Exception as exc:
            plan = None; verdict = "FAIL"; error = f"{type(exc).__name__}: {exc}"
        rows.append({"question": question, "verdict": verdict, "error": error,
                     "capabilities": [step.capability for step in plan.steps] if plan else [],
                     "node_count": len(plan.steps) if plan else 0,
                     "plan_score": planner.score_capability_plan(plan) if plan else None})
    artifact = {"registry_version": planner.CAPABILITY_REGISTRY_VERSION,
                "prompt_version": planner.PLANNER_PROMPT_VERSION,
                "questions": len(rows), "passed": sum(row["verdict"] == "PASS" for row in rows),
                "failed": sum(row["verdict"] == "FAIL" for row in rows), "results": rows}
    target = Path("artifacts/phase7-planner-acceptance.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps({key: artifact[key] for key in ("questions", "passed", "failed")}, indent=2))


if __name__ == "__main__":
    main()
