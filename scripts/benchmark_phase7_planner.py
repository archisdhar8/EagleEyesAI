from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import ask_execution, ask_orchestration, capability_planner as planner
from backend.analytical_contract import AnalysisResult, AnalysisStatus, Coverage, Freshness, VerificationResult


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values); index = min(len(ordered) - 1, int(len(ordered) * quantile))
    return round(ordered[index], 4)


def summary(values: list[float]) -> dict[str, float]:
    return {"median_ms": round(statistics.median(values), 4), "p95_ms": percentile(values, .95)}


def canonical(capability: str) -> AnalysisResult:
    return AnalysisResult(capability=capability, calculation_version="benchmark-v1", input_fingerprint=capability,
        status=AnalysisStatus.SUCCESS, data={"summary": f"{capability} evidence"}, coverage=Coverage.not_tracked(),
        freshness=Freshness(calculated_at=datetime.now(timezone.utc)),
        verification=VerificationResult(passed=True, answer_allowed=True, recommendation_allowed=False))


def main(samples: int = 500) -> None:
    entities = [planner.ResolvedEntity(kind="PORTFOLIO", canonical_id="p1")]
    direct: list[float] = []; planning: list[float] = []; validation: list[float] = []
    execution: list[float] = []; composition: list[float] = []; narration = [0.0] * samples
    for index in range(samples):
        started = time.perf_counter(); ask_orchestration.build_plan("What is the macro state?", "portfolio", {})
        direct.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter(); plan = planner.deterministic_capability_plan(
            "Given recession probabilities and macro conditions, where is my portfolio exposed?", entities, portfolio_id="p1")
        planning.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter(); planner.validate_capability_plan(plan, {"portfolio_id": "p1", "resolved_entity_ids": ["p1"]})
        validation.append((time.perf_counter() - started) * 1000)
        nodes = tuple(ask_execution.ExecutionNode(node_id=f"node_{node}", dependency_name=step.capability,
            required=step.required, executor=lambda *_: ask_execution.NodeExecutionValue()) for node, step in enumerate(plan.steps))
        started = time.perf_counter(); ask_execution.execute_capability_plan(ask_execution.CapabilityExecutionPlan(
            request_id=f"bench-{index}", capability="COMPOSED_ANALYSIS", absolute_deadline_monotonic=time.monotonic() + 1,
            initial_budget_ms=1000, nodes=nodes, max_concurrency=4))
        execution.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter(); composed = planner.compose_results("question", plan, [canonical(step.capability) for step in plan.steps]); planner.render_composed(composed)
        composition.append((time.perf_counter() - started) * 1000)
    total = [sum(values) for values in zip(direct, planning, validation, execution, composition, narration)]
    artifact = {"samples": samples, "environment": "local synthetic no-I/O capability boundary",
        "direct_route": summary(direct), "planner": summary(planning), "validation": summary(validation),
        "capability_execution": summary(execution), "composition": summary(composition),
        "optional_narration_disabled": summary(narration), "total_composed": summary(total)}
    target = Path("artifacts/phase7-planner-benchmark.json"); target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))


if __name__ == "__main__": main()
