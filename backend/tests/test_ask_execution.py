from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from backend import ask_execution, database


def _plan(nodes, budget=.8, request_id="request-1"):
    started = time.monotonic()
    return ask_execution.CapabilityExecutionPlan(
        request_id=request_id, capability="TEST", absolute_deadline_monotonic=started + budget,
        initial_budget_ms=budget * 1000, nodes=tuple(nodes), max_concurrency=3,
    )


def _sleep_node(node_id: str, seconds: float, *, required: bool = True,
                depends_on=(), timeout_ms=1000, intervals=None, status=ask_execution.NodeStatus.SUCCESS):
    def execute(*_):
        began = time.monotonic()
        time.sleep(seconds)
        ended = time.monotonic()
        if intervals is not None:
            intervals[node_id] = (began, ended)
        return ask_execution.NodeExecutionValue(status=status)
    return ask_execution.ExecutionNode(
        node_id=node_id, dependency_name=node_id, required=required, depends_on=tuple(depends_on),
        configured_timeout_ms=timeout_ms, executor=execute,
    )


def test_independent_nodes_overlap_instead_of_taking_sequential_sum():
    intervals = {}
    nodes = [_sleep_node(name, .5, intervals=intervals) for name in ("a", "b", "c")]
    started = time.monotonic()
    outcomes = ask_execution.execute_capability_plan(_plan(nodes, budget=1.2))
    elapsed = time.monotonic() - started
    assert elapsed < 1.0
    assert all(row.status == ask_execution.NodeStatus.SUCCESS for row in outcomes)
    assert max(start for start, _ in intervals.values()) < min(end for _, end in intervals.values())


def test_unrelated_fast_request_is_not_blocked_by_slow_request():
    slow_plan = _plan([_sleep_node("slow", .8)], budget=1.2, request_id="slow-request")
    fast_plan = _plan([_sleep_node("fast", .03)], budget=.5, request_id="fast-request")
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(ask_execution.execute_capability_plan, slow_plan)
        time.sleep(.05)
        fast_started = time.monotonic()
        fast = pool.submit(ask_execution.execute_capability_plan, fast_plan)
        assert fast.result(timeout=.4)[0].status == ask_execution.NodeStatus.SUCCESS
        assert time.monotonic() - fast_started < .3
        assert not slow.done()
        assert slow.result(timeout=1)[0].status == ask_execution.NodeStatus.SUCCESS


def test_dependent_node_timeout_is_capped_by_remaining_absolute_deadline():
    observed = {}
    first = _sleep_node("a", .18, timeout_ms=500)

    def second(context, _):
        observed["effective"] = context.effective_timeout_ms
        time.sleep(.5)
        return ask_execution.NodeExecutionValue()

    dependent = ask_execution.ExecutionNode(
        node_id="b", dependency_name="b", required=True, depends_on=("a",),
        configured_timeout_ms=5000, executor=second,
    )
    started = time.monotonic()
    outcomes = ask_execution.execute_capability_plan(_plan([first, dependent], budget=.25))
    elapsed = time.monotonic() - started
    assert outcomes[0].status == ask_execution.NodeStatus.SUCCESS
    assert outcomes[1].status in {ask_execution.NodeStatus.TIMED_OUT, ask_execution.NodeStatus.SKIPPED_DEADLINE}
    assert observed.get("effective", 0) <= 90
    assert elapsed < .4


def test_optional_timeout_does_not_kill_successful_required_node():
    outcomes = ask_execution.execute_capability_plan(_plan([
        _sleep_node("required", .02, required=True),
        _sleep_node("optional", .3, required=False, timeout_ms=50),
    ], budget=.4))
    assert outcomes[0].status == ask_execution.NodeStatus.SUCCESS
    assert outcomes[1].status == ask_execution.NodeStatus.TIMED_OUT


def test_required_timeout_does_not_erase_completed_optional_context():
    outcomes = ask_execution.execute_capability_plan(_plan([
        _sleep_node("required", .3, required=True, timeout_ms=60),
        _sleep_node("optional", .02, required=False),
    ], budget=.4))
    assert outcomes[0].status == ask_execution.NodeStatus.TIMED_OUT
    assert outcomes[1].status == ask_execution.NodeStatus.SUCCESS


def test_failed_parent_skips_dependent_without_calling_it():
    called = threading.Event()
    parent = _sleep_node("a", .01, status=ask_execution.NodeStatus.UNAVAILABLE)
    child = ask_execution.ExecutionNode(
        node_id="b", dependency_name="b", required=True, depends_on=("a",),
        executor=lambda *_: (called.set(), ask_execution.NodeExecutionValue())[1],
    )
    outcomes = ask_execution.execute_capability_plan(_plan([parent, child]))
    assert outcomes[0].status == ask_execution.NodeStatus.UNAVAILABLE
    assert outcomes[1].status == ask_execution.NodeStatus.SKIPPED_DEPENDENCY
    assert not called.is_set()


def test_idempotent_lifecycle_replays_one_logical_turn():
    request_id = "logical-request-123"
    first = database.reserve_ask_request("user-a", request_id, "question-hash")
    second = database.reserve_ask_request("user-a", request_id, "question-hash")
    assert first["request_id"] == second["request_id"]
    bound1 = database.bind_ask_request_turn("user-a", request_id, "conversation-a", "Question?", {})
    bound2 = database.bind_ask_request_turn("user-a", request_id, "conversation-a", "Question?", {})
    assert bound1["user_message_id"] == bound2["user_message_id"]
    database.stage_ask_request_result("user-a", request_id, {
        "answer": "Answer", "structured_content": {"request_id": request_id}, "model": "deterministic",
        "sources": [], "tool_results": [], "artifacts": [], "final_state": "COMPLETED",
    })
    response1 = database.complete_ask_request("user-a", request_id, final_state="COMPLETED")
    response2 = database.complete_ask_request("user-a", request_id, final_state="COMPLETED")
    assert response1 == response2
    assert response1["message"]["id"] == response2["message"]["id"]
    assert database.get_ask_request("user-a", request_id)["state"] == "COMPLETED"


def test_staged_result_recovers_after_late_persistence_failure():
    request_id = "logical-request-failure"
    database.reserve_ask_request("user-a", request_id, "question-hash")
    database.bind_ask_request_turn("user-a", request_id, "conversation-a", "Question?", {})
    database.stage_ask_request_result("user-a", request_id, {
        "answer": "Recovered answer", "structured_content": {}, "model": "deterministic",
        "sources": [], "tool_results": [], "artifacts": [], "final_state": "PARTIAL",
    })
    database.fail_ask_request("user-a", request_id, "OperationalError", persistence=True)
    failed = database.get_ask_request("user-a", request_id)
    assert failed["state"] == "PERSISTENCE_FAILED"
    assert failed["staged_result"]["answer"] == "Recovered answer"
    recovered = database.complete_ask_request("user-a", request_id, final_state="PARTIAL")
    assert recovered["message"]["content"] == "Recovered answer"
    assert database.get_ask_request("user-a", request_id)["state"] == "PARTIAL"
