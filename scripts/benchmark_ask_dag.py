from __future__ import annotations

import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ask_execution import (  # noqa: E402
    CapabilityExecutionPlan,
    ExecutionNode,
    ExpectedLatencyClass,
    NodeExecutionValue,
    execute_capability_plan,
)
from backend.analytical_telemetry import DeadlineContext  # noqa: E402


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def sleeping_node(node_id: str, milliseconds: float) -> ExecutionNode:
    def execute(_context, _dependencies):
        time.sleep(milliseconds / 1000)
        return NodeExecutionValue(payload={"node": node_id})

    return ExecutionNode(
        node_id=node_id, dependency_name=node_id, required=True, depends_on=(),
        expected_latency_class=ExpectedLatencyClass.LIGHT_IO, configured_timeout_ms=2_000,
        executor=execute,
    )


def run_nodes(count: int, milliseconds: float = 30) -> float:
    started = time.monotonic()
    deadline = DeadlineContext.from_budget(started, 5)
    plan = CapabilityExecutionPlan(
        request_id=f"benchmark-{count}-{started}", capability="benchmark",
        absolute_deadline_monotonic=deadline.absolute_deadline_monotonic,
        initial_budget_ms=5_000,
        nodes=tuple(sleeping_node(f"node-{index}", milliseconds) for index in range(count)),
        max_concurrency=3,
    )
    execute_capability_plan(plan)
    return (time.monotonic() - started) * 1000


def sample(count: int, repeats: int = 25) -> dict[str, float | int]:
    values = [run_nodes(count) for _ in range(repeats)]
    return {"samples": repeats, "p50_ms": round(statistics.median(values), 2),
            "p95_ms": round(percentile(values, .95), 2)}


def concurrent_requests(repeats: int = 20) -> dict[str, float | int]:
    values = []
    for _ in range(repeats):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _index: run_nodes(1), range(4)))
        values.append((time.monotonic() - started) * 1000)
    return {"samples": repeats, "requests_per_sample": 4,
            "p50_ms": round(statistics.median(values), 2), "p95_ms": round(percentile(values, .95), 2)}


def slow_node_isolation(repeats: int = 20) -> dict[str, float | int]:
    values = []
    for _ in range(repeats):
        slow_started = threading.Event()

        def slow_request():
            slow_started.set()
            return run_nodes(1, 250)

        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(slow_request)
            slow_started.wait(1)
            fast_started = time.monotonic()
            fast = pool.submit(run_nodes, 1, 30)
            fast.result()
            values.append((time.monotonic() - fast_started) * 1000)
            slow.result()
    return {"samples": repeats, "slow_node_ms": 250, "fast_node_ms": 30,
            "fast_request_p50_ms": round(statistics.median(values), 2),
            "fast_request_p95_ms": round(percentile(values, .95), 2)}


def main() -> None:
    payload = {
        "environment": "local synthetic I/O benchmark; not a production SLO claim",
        "single_capability_read": sample(1),
        "two_independent_nodes": sample(2),
        "three_independent_nodes": sample(3),
        "concurrent_user_requests": concurrent_requests(),
        "slow_node_isolation": slow_node_isolation(),
        "old_sequential_theoretical_ms": {"two_nodes": 60, "three_nodes": 90},
    }
    output = ROOT / "artifacts" / "phase3-ask-dag-benchmark.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
