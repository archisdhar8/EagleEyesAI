from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from .analytical_telemetry import DeadlineContext


class NodeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED_DEADLINE = "SKIPPED_DEADLINE"
    SKIPPED_DEPENDENCY = "SKIPPED_DEPENDENCY"


class ExpectedLatencyClass(StrEnum):
    MEMORY = "MEMORY"
    DATABASE = "DATABASE"
    LIGHT_IO = "LIGHT_IO"


@dataclass(frozen=True)
class NodeExecutionValue:
    status: NodeStatus = NodeStatus.SUCCESS
    tool_results: tuple[dict[str, Any], ...] = ()
    evidence_rows: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeExecutionContext:
    request_id: str
    capability: str
    node_id: str
    dependency_name: str
    deadline: DeadlineContext
    configured_timeout_ms: float
    effective_timeout_ms: float
    started_monotonic: float

    def remaining_ms(self) -> float:
        return self.deadline.remaining_ms()


NodeExecutor = Callable[[NodeExecutionContext, dict[str, "NodeOutcome"]], NodeExecutionValue]


@dataclass(frozen=True)
class ExecutionNode:
    node_id: str
    dependency_name: str
    required: bool
    depends_on: tuple[str, ...] = ()
    expected_latency_class: ExpectedLatencyClass = ExpectedLatencyClass.DATABASE
    configured_timeout_ms: float = 2500.0
    executor: NodeExecutor = field(compare=False, repr=False, default=lambda *_: NodeExecutionValue())


@dataclass(frozen=True)
class CapabilityExecutionPlan:
    request_id: str
    capability: str
    absolute_deadline_monotonic: float
    initial_budget_ms: float
    nodes: tuple[ExecutionNode, ...]
    max_concurrency: int = 3


@dataclass
class NodeOutcome:
    node_id: str
    dependency_name: str
    required: bool
    depends_on: tuple[str, ...]
    status: NodeStatus
    started_monotonic: float | None = None
    completed_monotonic: float | None = None
    latency_ms: float | None = None
    deadline_remaining_at_start_ms: float | None = None
    deadline_remaining_at_end_ms: float | None = None
    configured_timeout_ms: float | None = None
    effective_timeout_ms: float | None = None
    error_class: str | None = None
    value: NodeExecutionValue | None = None

    def payload(self, request_started_monotonic: float) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "dependency": self.dependency_name, "required": self.required,
            "depends_on": list(self.depends_on), "status": self.status.value,
            "start_ms": None if self.started_monotonic is None else round((self.started_monotonic - request_started_monotonic) * 1000, 2),
            "end_ms": None if self.completed_monotonic is None else round((self.completed_monotonic - request_started_monotonic) * 1000, 2),
            "latency_ms": self.latency_ms,
            "deadline_remaining_at_start_ms": self.deadline_remaining_at_start_ms,
            "deadline_remaining_at_end_ms": self.deadline_remaining_at_end_ms,
            "configured_timeout_ms": self.configured_timeout_ms,
            "effective_timeout_ms": self.effective_timeout_ms,
            "error_class": self.error_class,
            **((self.value.metadata if self.value else {}) or {}),
        }


@dataclass(frozen=True)
class CapabilityExecutionSpec:
    capability: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


CAPABILITY_EXECUTION_SPECS: dict[str, CapabilityExecutionSpec] = {
    "COMPANY_RESEARCH": CapabilityExecutionSpec("COMPANY_RESEARCH", ("company_analysis",)),
    "EARNINGS": CapabilityExecutionSpec("EARNINGS", ("company_analysis",)),
    "COMPARISON": CapabilityExecutionSpec("COMPARISON", ("company_comparison",)),
    "MACRO_STATE": CapabilityExecutionSpec("MACRO_STATE", ("macro_state",)),
    "MARKET_STATE": CapabilityExecutionSpec("MARKET_STATE", ("market_state",)),
    "PREDICTION_MARKETS": CapabilityExecutionSpec("PREDICTION_MARKETS", ("prediction_markets",)),
    "FORECAST": CapabilityExecutionSpec("FORECAST", ("prediction_markets",)),
    "HISTORICAL_CHANGE": CapabilityExecutionSpec("HISTORICAL_CHANGE", ("historical_change",)),
    "CHANGE": CapabilityExecutionSpec("CHANGE", ("historical_change",)),
    "OPPORTUNITY_RANKING": CapabilityExecutionSpec("OPPORTUNITY_RANKING", ("portfolio_overview",), ("thesis_status",)),
    "THESIS_REPLACEMENT": CapabilityExecutionSpec("THESIS_REPLACEMENT", ("thesis_replacement",), ("thesis_status",)),
    "PORTFOLIO_CHANGE": CapabilityExecutionSpec("PORTFOLIO_CHANGE", ("portfolio_change",), ("thesis_status",)),
    "VALUATION_RANKING": CapabilityExecutionSpec("VALUATION_RANKING", ("valuation_ranking",), ("portfolio_data_quality",)),
    "HIDDEN_RISK": CapabilityExecutionSpec("HIDDEN_RISK", ("portfolio_intelligence",), ("thesis_status", "portfolio_scenario")),
    "MULTI_SCENARIO": CapabilityExecutionSpec("MULTI_SCENARIO", ("portfolio_scenario",), ("portfolio_risk",)),
    "WATCHLIST_COMPARISON": CapabilityExecutionSpec("WATCHLIST_COMPARISON", ("watchlist_comparison",), ("portfolio_data_quality",)),
    "PORTFOLIO_EVENTS": CapabilityExecutionSpec("PORTFOLIO_EVENTS", ("portfolio_events",), ("thesis_status",)),
    "DATA_QUALITY": CapabilityExecutionSpec("DATA_QUALITY", ("data_quality",)),
    "SCORE_ATTRIBUTION": CapabilityExecutionSpec("SCORE_ATTRIBUTION", ("score_attribution",), ("thesis_status",)),
    "THESIS_INVALIDATION": CapabilityExecutionSpec("THESIS_INVALIDATION", ("thesis_invalidation",)),
    "PORTFOLIO_ANALYSIS": CapabilityExecutionSpec("PORTFOLIO_ANALYSIS", ("portfolio_analysis",), ("portfolio_risk",)),
    "MULTIFACTOR_SCREEN": CapabilityExecutionSpec("MULTIFACTOR_SCREEN", ("multifactor_screen",), ("portfolio_data_quality",)),
    "RECOMMENDATION_COUNTERCASE": CapabilityExecutionSpec("RECOMMENDATION_COUNTERCASE", ("recommendation_countercase",), ("thesis_status",)),
    "CASH_ALLOCATION": CapabilityExecutionSpec("CASH_ALLOCATION", ("cash_allocation",), ("portfolio_data_quality",)),
}


def _run_node(node: ExecutionNode, context: NodeExecutionContext,
              outcomes: dict[str, NodeOutcome]) -> NodeExecutionValue:
    # Database calls made by this worker inherit a statement/connect timeout no
    # greater than the node's remaining wait budget.
    try:
        from . import database
        database.set_thread_query_timeout_ms(context.effective_timeout_ms)
        return node.executor(context, outcomes)
    finally:
        try:
            database.clear_thread_query_timeout_ms()
        except Exception:
            pass


def execute_capability_plan(plan: CapabilityExecutionPlan, *, minimum_start_budget_ms: float = 25.0) -> list[NodeOutcome]:
    """Execute one small read-only DAG with bounded per-request concurrency.

    Timed-out running calls are no longer awaited. Their DB work is bounded by
    the thread-local statement/connect timeout; Python thread cancellation is
    deliberately not claimed.
    """
    deadline = DeadlineContext(plan.absolute_deadline_monotonic - plan.initial_budget_ms / 1000,
                               plan.absolute_deadline_monotonic)
    nodes = {node.node_id: node for node in plan.nodes}
    pending = set(nodes)
    outcomes: dict[str, NodeOutcome] = {}
    running: dict[Future[NodeExecutionValue], tuple[ExecutionNode, NodeOutcome, float]] = {}
    pool = ThreadPoolExecutor(max_workers=max(1, min(plan.max_concurrency, 8)), thread_name_prefix="ask-dag")
    try:
        while pending or running:
            progressed = False
            for node_id in list(pending):
                node = nodes[node_id]
                parents = [outcomes.get(parent) for parent in node.depends_on]
                if any(parent is None for parent in parents):
                    continue
                if any(parent.status != NodeStatus.SUCCESS for parent in parents if parent is not None):
                    now = time.monotonic()
                    outcomes[node_id] = NodeOutcome(
                        node_id=node.node_id, dependency_name=node.dependency_name, required=node.required,
                        depends_on=node.depends_on, status=NodeStatus.SKIPPED_DEPENDENCY,
                        completed_monotonic=now, deadline_remaining_at_end_ms=deadline.remaining_ms(),
                        configured_timeout_ms=node.configured_timeout_ms,
                    )
                    pending.remove(node_id); progressed = True
                    continue
                remaining = deadline.remaining_ms()
                if remaining < minimum_start_budget_ms:
                    now = time.monotonic()
                    outcomes[node_id] = NodeOutcome(
                        node_id=node.node_id, dependency_name=node.dependency_name, required=node.required,
                        depends_on=node.depends_on, status=NodeStatus.SKIPPED_DEADLINE,
                        completed_monotonic=now, deadline_remaining_at_end_ms=remaining,
                        configured_timeout_ms=node.configured_timeout_ms, effective_timeout_ms=max(0.0, remaining),
                    )
                    pending.remove(node_id); progressed = True
                    continue
                if len(running) >= plan.max_concurrency:
                    continue
                started = time.monotonic()
                effective = max(1.0, min(node.configured_timeout_ms, deadline.remaining_ms()))
                outcome = NodeOutcome(
                    node_id=node.node_id, dependency_name=node.dependency_name, required=node.required,
                    depends_on=node.depends_on, status=NodeStatus.FAILED, started_monotonic=started,
                    deadline_remaining_at_start_ms=deadline.remaining_ms(), configured_timeout_ms=node.configured_timeout_ms,
                    effective_timeout_ms=effective,
                )
                context = NodeExecutionContext(plan.request_id, plan.capability, node.node_id,
                                               node.dependency_name, deadline, node.configured_timeout_ms,
                                               effective, started)
                future = pool.submit(_run_node, node, context, dict(outcomes))
                running[future] = (node, outcome, started + effective / 1000)
                pending.remove(node_id); progressed = True

            impossible_required = any(outcome.required and outcome.status in {
                NodeStatus.UNAVAILABLE, NodeStatus.FAILED, NodeStatus.TIMED_OUT,
                NodeStatus.SKIPPED_DEADLINE, NodeStatus.SKIPPED_DEPENDENCY,
            } for outcome in outcomes.values())
            if impossible_required:
                now = time.monotonic()
                for node_id in list(pending):
                    node = nodes[node_id]
                    if not node.required:
                        outcomes[node_id] = NodeOutcome(
                            node_id=node.node_id, dependency_name=node.dependency_name, required=False,
                            depends_on=node.depends_on, status=NodeStatus.SKIPPED_DEPENDENCY,
                            completed_monotonic=now, deadline_remaining_at_end_ms=deadline.remaining_ms(),
                            configured_timeout_ms=node.configured_timeout_ms,
                        )
                        pending.remove(node_id)
                for future, (node, outcome, _) in list(running.items()):
                    if not node.required:
                        future.cancel()
                        outcome.status = NodeStatus.TIMED_OUT
                        outcome.completed_monotonic = now
                        outcome.latency_ms = round((now - (outcome.started_monotonic or now)) * 1000, 2)
                        outcome.deadline_remaining_at_end_ms = deadline.remaining_ms()
                        outcomes[node.node_id] = outcome
                        running.pop(future)

            if not running:
                if not progressed and pending:
                    # Invalid/cyclic dependency specs fail closed.
                    now = time.monotonic()
                    for node_id in list(pending):
                        node = nodes[node_id]
                        outcomes[node_id] = NodeOutcome(
                            node_id=node.node_id, dependency_name=node.dependency_name, required=node.required,
                            depends_on=node.depends_on, status=NodeStatus.SKIPPED_DEPENDENCY,
                            completed_monotonic=now, deadline_remaining_at_end_ms=deadline.remaining_ms(),
                            configured_timeout_ms=node.configured_timeout_ms,
                        )
                        pending.remove(node_id)
                continue

            now = time.monotonic()
            next_timeout = min(max(0.0, expires - now) for _, _, expires in running.values())
            remaining_seconds = max(0.0, deadline.remaining_ms() / 1000)
            done, _ = wait(tuple(running), timeout=min(next_timeout, remaining_seconds), return_when=FIRST_COMPLETED)
            now = time.monotonic()
            for future in list(done):
                node, outcome, _ = running.pop(future)
                try:
                    value = future.result()
                    outcome.value = value
                    outcome.status = value.status
                except Exception as exc:
                    outcome.status = NodeStatus.FAILED
                    outcome.error_class = type(exc).__name__
                outcome.completed_monotonic = now
                outcome.latency_ms = round((now - (outcome.started_monotonic or now)) * 1000, 2)
                outcome.deadline_remaining_at_end_ms = deadline.remaining_ms()
                outcomes[node.node_id] = outcome
            for future, (node, outcome, expires) in list(running.items()):
                if now >= expires or deadline.remaining_ms() <= 0:
                    future.cancel()
                    outcome.status = NodeStatus.TIMED_OUT
                    outcome.completed_monotonic = now
                    outcome.latency_ms = round((now - (outcome.started_monotonic or now)) * 1000, 2)
                    outcome.deadline_remaining_at_end_ms = deadline.remaining_ms()
                    outcome.error_class = "TimeoutError"
                    outcomes[node.node_id] = outcome
                    running.pop(future)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return [outcomes[node.node_id] for node in plan.nodes]
