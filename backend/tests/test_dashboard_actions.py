from __future__ import annotations

from fastapi.testclient import TestClient

from backend import database
from backend.dashboard_actions import (
    DashboardActionStatus,
    apply_dashboard_action,
    execute_dashboard_action,
    undo_dashboard_action,
)
from backend.dashboard_workspace import CALCULATION_VERSION, compile_spec, deterministic_plan
from backend.main import app


USER_ID = "00000000-0000-0000-0000-000000000001"
ALLOWED = {"portfolio_performance", "allocation", "drawdown"}


def widget(widget_id: str, task_id: str, title: str, *, x: int = 0, y: int = 0,
           width: int = 4, height: int = 2) -> dict:
    return {
        "id": widget_id,
        "task_id": task_id,
        "widget_type": "portfolio_performance",
        "title": title,
        "visualization": "line",
        "grid": {"x": x, "y": y, "w": width, "h": height},
    }


def apply(state: dict, action: dict) -> dict:
    result = apply_dashboard_action(state, action, allowed_widget_types=ALLOWED)
    assert result.status == DashboardActionStatus.SUCCESS, result.error
    assert result.dashboard is not None
    return result.dashboard


def saved_view() -> dict:
    plan = deterministic_plan("Show portfolio return and drawdown")
    spec = compile_spec(plan)
    job = database.create_dashboard_job(USER_ID, "Show portfolio return and drawdown")
    results = [
        {"widget_id": item["task_id"], "status": "READY", "data": {"fixture": item["id"]},
         "lineage": [], "calculation": {"method": item["widget_type"], "version": CALCULATION_VERSION}}
        for item in spec["widgets"]
    ]
    database.update_dashboard_job(
        job["id"], USER_ID, state="COMPLETE", progress=100,
        plan=plan.model_dump(mode="json"), specification=spec, widget_results=results,
    )
    return database.save_dashboard_view(USER_ID, job["id"], "Action fixture")


def test_all_phase_two_actions_and_stable_widget_id() -> None:
    state = {"name": "Board", "widgets": [], "layout_version": "dashboard-layout-v2"}
    state = apply(state, {"type": "CREATE_WIDGET", "widget": widget("stable-a", "task-a", "A")})
    state = apply(state, {"type": "CREATE_WIDGET", "widget": widget("stable-b", "task-b", "B", x=4)})
    state = apply(state, {"type": "UPDATE_WIDGET", "widget_id": "stable-a", "changes": {"title": "Updated A"}})
    state = apply(state, {"type": "MOVE_WIDGET", "widget_id": "stable-b", "to_index": 0})
    state = apply(state, {"type": "RESIZE_WIDGET", "widget_id": "stable-a", "width": 8, "height": 4})
    state = apply(state, {"type": "RENAME_DASHBOARD", "name": "Renamed"})
    assert state["name"] == "Renamed"
    assert [item["id"] for item in state["widgets"]] == ["stable-b", "stable-a"]
    assert state["widgets"][1]["title"] == "Updated A"
    assert state["widgets"][1]["grid"]["w"] == 8
    assert state["widgets"][1]["grid"]["h"] == 4
    state = apply(state, {"type": "DELETE_WIDGET", "widget_id": "stable-b"})
    assert [item["id"] for item in state["widgets"]] == ["stable-a"]
    state = apply(state, {"type": "CLEAR_DASHBOARD"})
    assert state["widgets"] == []


def test_generated_widget_id_is_assigned_once_and_survives_later_actions() -> None:
    generated = widget("temporary", "task-a", "Generated")
    generated.pop("id")
    state = apply({"name": "Board", "widgets": []}, {"type": "CREATE_WIDGET", "widget": generated})
    stable_id = state["widgets"][0]["id"]
    assert stable_id.startswith("widget-")
    state = apply(state, {"type": "UPDATE_WIDGET", "widget_id": stable_id, "changes": {"title": "Still stable"}})
    state = apply(state, {"type": "RESIZE_WIDGET", "widget_id": stable_id, "width": 8, "height": 3})
    assert state["widgets"][0]["id"] == stable_id


def test_exact_sequential_action_contract() -> None:
    state = {"name": "Sequence", "widgets": []}
    actions = [
        {"type": "CREATE_WIDGET", "widget": widget("A", "task-a", "Alpha")},
        {"type": "CREATE_WIDGET", "widget": widget("B", "task-b", "Beta", x=4)},
        {"type": "MOVE_WIDGET", "widget_id": "A", "to_index": 1},
        {"type": "RESIZE_WIDGET", "widget_id": "B", "width": 8, "height": 3},
        {"type": "UPDATE_WIDGET", "widget_id": "A", "changes": {"title": "Alpha updated"}},
        {"type": "DELETE_WIDGET", "widget_id": "B"},
    ]
    for action in actions:
        state = apply(state, action)
    assert state == {
        "name": "Sequence",
        "widgets": [{
            "id": "A", "task_id": "task-a", "widget_type": "portfolio_performance",
            "title": "Alpha updated", "visualization": "line",
            "grid": {"x": 0, "y": 0, "w": 4, "h": 2},
        }],
        "layout_version": "dashboard-layout-v2",
    }


def test_invalid_widget_action_layout_and_binding_return_typed_statuses() -> None:
    state = {"name": "Board", "widgets": [widget("A", "task-a", "Alpha")]}
    missing = apply_dashboard_action(state, {"type": "DELETE_WIDGET", "widget_id": "missing"}, allowed_widget_types=ALLOWED)
    malformed = apply_dashboard_action(state, {"type": "NOT_AN_ACTION"}, allowed_widget_types=ALLOWED)
    layout = apply_dashboard_action(state, {"type": "RESIZE_WIDGET", "widget_id": "A", "width": 5, "height": 2}, allowed_widget_types=ALLOWED)
    binding = apply_dashboard_action(
        {"name": "Board", "widgets": []},
        {"type": "CREATE_WIDGET", "widget": widget("B", "unknown", "Beta")},
        allowed_widget_types=ALLOWED, available_task_ids={"known"},
    )
    future = apply_dashboard_action(state, {"type": "CHANGE_VISUALIZATION", "widget_id": "A"}, allowed_widget_types=ALLOWED)
    chart_change = apply_dashboard_action(
        state, {"type": "UPDATE_WIDGET", "widget_id": "A", "changes": {"visualization": "bar"}},
        allowed_widget_types=ALLOWED,
    )
    widget_type = apply_dashboard_action(
        {"name": "Board", "widgets": []},
        {"type": "CREATE_WIDGET", "widget": {**widget("B", "task-b", "Beta"), "widget_type": "not_supported"}},
        allowed_widget_types=ALLOWED,
    )
    assert missing.status == DashboardActionStatus.INVALID
    assert malformed.status == DashboardActionStatus.INVALID
    assert layout.status == DashboardActionStatus.INVALID
    assert binding.status == DashboardActionStatus.INVALID
    assert future.status == DashboardActionStatus.UNSUPPORTED
    assert chart_change.status == DashboardActionStatus.SUCCESS
    assert chart_change.dashboard["widgets"][0]["visualization"] == "bar"
    assert widget_type.status == DashboardActionStatus.INVALID
    assert state["widgets"][0]["grid"]["w"] == 4


def test_saved_view_action_creates_one_revision_and_updates_spec_and_layout() -> None:
    view = saved_view()
    target = view["layout"][0]
    before_count = len(database.list_dashboard_revisions(view["id"], USER_ID))
    result = execute_dashboard_action(
        USER_ID, "view", view["id"],
        {"type": "RESIZE_WIDGET", "widget_id": target["id"], "width": 12, "height": 4},
        allowed_widget_types=ALLOWED | {target["widget_type"]},
    )
    assert result.status == DashboardActionStatus.SUCCESS
    assert result.revision is not None
    updated = database.get_dashboard_view(view["id"], USER_ID)
    assert len(database.list_dashboard_revisions(view["id"], USER_ID)) == before_count + 1
    assert updated["layout"][0]["grid"]["w"] == 12
    assert updated["specification"]["widgets"][0]["grid"]["w"] == 12
    assert updated["layout"][0]["id"] == target["id"]


def test_saved_view_undo_restores_existing_revision_and_records_revert() -> None:
    view = saved_view()
    target = view["layout"][0]
    original_width = target["grid"]["w"]
    changed = execute_dashboard_action(
        USER_ID, "view", view["id"],
        {"type": "RESIZE_WIDGET", "widget_id": target["id"], "width": 12, "height": 4},
        allowed_widget_types=ALLOWED | {target["widget_type"]},
    )
    assert changed.status == DashboardActionStatus.SUCCESS
    undone = undo_dashboard_action(USER_ID, "view", view["id"])
    assert undone.status == DashboardActionStatus.SUCCESS
    assert undone.revision is not None
    assert undone.dashboard["layout"][0]["grid"]["w"] == original_width
    assert database.list_dashboard_revisions(view["id"], USER_ID)[0]["revision_type"].startswith("reverted_to_")


def test_draft_delete_and_undo_restore_widget_and_result() -> None:
    plan = deterministic_plan("Show portfolio return and drawdown")
    spec = compile_spec(plan)
    target = spec["widgets"][0]
    result_row = {
        "widget_id": target["task_id"], "status": "READY", "data": {"fixture": target["id"]},
        "lineage": [], "calculation": {"method": target["widget_type"], "version": CALCULATION_VERSION},
    }
    job = database.create_dashboard_job(USER_ID, "Draft undo")
    database.update_dashboard_job(
        job["id"], USER_ID, state="COMPLETE", progress=100,
        plan=plan.model_dump(mode="json"), specification=spec, widget_results=[result_row],
    )
    deleted = execute_dashboard_action(
        USER_ID, "draft", job["id"], {"type": "DELETE_WIDGET", "widget_id": target["id"]},
        allowed_widget_types=ALLOWED | {target["widget_type"]},
    )
    assert deleted.status == DashboardActionStatus.SUCCESS
    undone = undo_dashboard_action(USER_ID, "draft", job["id"])
    assert undone.status == DashboardActionStatus.SUCCESS
    assert undone.dashboard["specification"]["widgets"][0]["id"] == target["id"]
    assert undone.dashboard["widget_results"][0]["widget_id"] == target["task_id"]


def test_widget_result_refresh_appends_a_view_run_without_rewriting_history() -> None:
    view = saved_view()
    before = database.get_dashboard_view(view["id"], USER_ID)
    before_run_id = before["latest_run"]["id"]
    prior_results = before["latest_run"]["widget_results"]
    refreshed = {
        "widget_id": "conversation-widget", "status": "READY", "data": {"value": 42},
        "lineage": [{"provider": "fixture", "dataset": "approved"}], "warnings": [],
        "calculation": {"method": "fixture", "version": "v1"},
    }
    updated = database.persist_dashboard_widget_results(view["id"], USER_ID, refreshed)
    assert updated["latest_run"]["id"] != before_run_id
    assert len(updated["latest_run"]["widget_results"]) == len(prior_results) + 1
    assert updated["latest_run"]["widget_results"][-1]["widget_id"] == "conversation-widget"


def test_action_api_returns_typed_invalid_instead_of_silent_ignore() -> None:
    view = saved_view()
    with TestClient(app) as client:
        response = client.post(
            f"/api/dashboard/views/{view['id']}/actions",
            json={"type": "DELETE_WIDGET", "widget_id": "does-not-exist"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "INVALID"
    assert "does-not-exist" in response.json()["error"]
