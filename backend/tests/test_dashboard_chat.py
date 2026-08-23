from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import dashboard_chat, database
from backend.dashboard_actions import DashboardActionResult, DashboardActionStatus
from backend.dashboard_chat import DashboardChatExecution, DashboardChatIntent, DashboardChatRequest, interpret_dashboard_request, resolve_widget_reference
from backend.main import app
from backend.dashboard_workspace import compile_spec, deterministic_plan


def widget(widget_id: str, title: str, widget_type: str, visualization: str, x: int, y: int) -> dict:
    return {
        "id": widget_id, "task_id": widget_id, "title": title,
        "widget_type": widget_type, "visualization": visualization,
        "grid": {"x": x, "y": y, "w": 6, "h": 2},
        "binding": {"metric": widget_type, "portfolio": "current", "period": "1Y", "tickers": [], "filters": []},
    }


PERFORMANCE = widget("performance", "Portfolio Performance", "portfolio_performance", "line_chart", 0, 0)
VALUATION = widget("valuation", "Valuation and Fundamentals", "security_comparison", "table", 6, 0)
SECTORS = widget("sectors", "Sector Exposure", "sector_exposure", "bar_chart", 0, 2)
WIDGETS = [PERFORMANCE, VALUATION, SECTORS]


@pytest.mark.parametrize(
    "question,widget_type,visualization",
    [
        ("Show my sector exposure as a chart.", "sector_exposure", "bar_chart"),
        ("Add my one-year performance against SPY.", "portfolio_performance", "line_chart"),
        ("Add a valuation table for my holdings.", "security_comparison", "table"),
        ("Show my portfolio performance over five years.", "portfolio_performance", "line_chart"),
    ],
)
def test_create_widget_language(question: str, widget_type: str, visualization: str) -> None:
    request = interpret_dashboard_request(question, [])
    assert request.intent == DashboardChatIntent.CREATE_WIDGET
    assert request.widget_type == widget_type
    assert request.visualization == visualization


def test_create_binding_preserves_period_and_benchmark() -> None:
    request = interpret_dashboard_request("Add my one-year performance against SPY.", [])
    assert request.binding is not None
    assert request.binding.period == "1Y"
    assert request.binding.benchmark == "SPY"


@pytest.mark.parametrize(
    "question,intent,expected",
    [
        ("Make that a bar chart.", DashboardChatIntent.UPDATE_WIDGET, "performance"),
        ("Change that to five years.", DashboardChatIntent.UPDATE_WIDGET, "performance"),
        ("Compare against QQQ instead.", DashboardChatIntent.UPDATE_WIDGET, "performance"),
        ("Show only semiconductor holdings.", DashboardChatIntent.UPDATE_WIDGET, "performance"),
        ("Remove that chart.", DashboardChatIntent.DELETE_WIDGET, "performance"),
        ("Make that chart wider.", DashboardChatIntent.RESIZE_WIDGET, "performance"),
    ],
)
def test_follow_up_language_uses_last_action_widget(question: str, intent: DashboardChatIntent, expected: str) -> None:
    request = interpret_dashboard_request(question, WIDGETS, {"dashboard_widget_id": "performance"})
    assert request.intent == intent
    assert request.widget_id == expected
    assert request.clarification is None


def test_update_binding_preserves_existing_metric() -> None:
    request = interpret_dashboard_request("Change that to five years.", WIDGETS, {"dashboard_widget_id": "performance"})
    assert request.binding is not None
    assert request.binding.metric == "portfolio_performance"
    assert request.binding.period == "5Y"


def test_filter_becomes_typed_binding_not_freeform_widget_data() -> None:
    request = interpret_dashboard_request("Show only semiconductor holdings.", WIDGETS, {"dashboard_widget_id": "valuation"})
    assert request.widget_id == "valuation"
    assert request.binding is not None
    assert request.binding.filters[0].field == "classification"
    assert request.binding.filters[0].value == "semiconductor"


def test_move_resolves_source_and_named_destination() -> None:
    request = interpret_dashboard_request("Move it below the valuation table.", WIDGETS, {"dashboard_widget_id": "sectors"})
    assert request.intent == DashboardChatIntent.MOVE_WIDGET
    assert request.widget_id == "sectors"
    assert request.relative_to_widget_id == "valuation"
    assert request.relation == "after"
    assert request.clarification is None


def test_ambiguous_delete_asks_clarifying_question() -> None:
    request = interpret_dashboard_request("Delete the chart.", WIDGETS)
    assert request.intent == DashboardChatIntent.DELETE_WIDGET
    assert request.widget_id is None
    assert request.clarification is not None
    assert "Which chart" in request.clarification


def test_positional_references_are_deterministic() -> None:
    right_chart = widget("right", "Benchmark Return", "portfolio_performance", "bar_chart", 6, 0)
    right, clarification = resolve_widget_reference("the chart on the top right", [PERFORMANCE, right_chart, SECTORS])
    assert clarification is None
    assert right is not None and right["id"] == "right"
    bottom, clarification = resolve_widget_reference("the chart at the bottom", WIDGETS)
    assert clarification is None
    assert bottom is not None and bottom["id"] == "sectors"


def test_mixed_analysis_and_visual_request_is_marked_mixed() -> None:
    request = interpret_dashboard_request("Where is my portfolio concentrated? Show it visually.", [])
    assert request.intent == DashboardChatIntent.CREATE_WIDGET
    assert request.widget_type == "sector_exposure"
    assert request.mixed_answer is True


def test_normal_financial_question_does_not_modify_dashboard() -> None:
    request = interpret_dashboard_request("Why did MSFT margins decline last quarter?", WIDGETS)
    assert request.intent == DashboardChatIntent.NORMAL_ANSWER


@pytest.mark.parametrize(
    "question,intent,name",
    [
        ("Save this.", DashboardChatIntent.SAVE_DASHBOARD, None),
        ("Save this as Portfolio Overview.", DashboardChatIntent.SAVE_DASHBOARD, "Portfolio Overview"),
        ("Call this AI Exposure Monitor.", DashboardChatIntent.RENAME_DASHBOARD, "AI Exposure Monitor"),
        ("Rename this Portfolio Risk.", DashboardChatIntent.RENAME_DASHBOARD, "Portfolio Risk"),
        ("Make a copy.", DashboardChatIntent.DUPLICATE_DASHBOARD, None),
        ("Duplicate this for my retirement portfolio.", DashboardChatIntent.DUPLICATE_DASHBOARD, "My Retirement Portfolio copy"),
        ("Undo last change.", DashboardChatIntent.UNDO_DASHBOARD, None),
    ],
)
def test_phase_five_dashboard_language(question: str, intent: DashboardChatIntent, name: str | None) -> None:
    request = interpret_dashboard_request(question, WIDGETS, {"dashboard_widget_id": "performance"})
    assert request.intent == intent
    assert request.dashboard_name == name


def test_widget_scoped_revert_resolves_named_active_widget() -> None:
    request = interpret_dashboard_request("Revert the sector chart change.", WIDGETS)
    assert request.intent == DashboardChatIntent.UNDO_DASHBOARD
    assert request.widget_id == "sectors"
    assert request.clarification is None


def test_visual_suggestion_never_mutates_without_explicit_request() -> None:
    suggestion = dashboard_chat.visual_suggestion_for("How concentrated am I?")
    assert suggestion == {
        "label": "Visualize concentration",
        "prompt": "Add a sector exposure chart to this dashboard.",
    }
    assert interpret_dashboard_request("How concentrated am I?", WIDGETS).intent == DashboardChatIntent.NORMAL_ANSWER


def test_phase8_conversational_flow_separates_chat_visual_and_new_analysis() -> None:
    prior = {"dashboard_widget_id": "sectors", "intent": "PORTFOLIO_RISK", "analytical_context": {
        "active_capabilities": ["portfolio_risk"], "recent_result_ids": ["result_1234567890abcdef"],
    }}
    assert interpret_dashboard_request("Where am I most concentrated?", WIDGETS, prior).intent == DashboardChatIntent.NORMAL_ANSWER
    visualize = interpret_dashboard_request("Visualize that.", WIDGETS, prior)
    assert visualize.intent == DashboardChatIntent.CREATE_WIDGET and visualize.requires_new_analysis
    risk = interpret_dashboard_request("Add my largest risk contributors.", WIDGETS, prior)
    assert risk.intent == DashboardChatIntent.CREATE_WIDGET and risk.requires_new_analysis
    market = interpret_dashboard_request("Compare against the current market regime.", WIDGETS, prior)
    assert market.intent == DashboardChatIntent.CREATE_WIDGET and market.requires_new_analysis
    backtest = interpret_dashboard_request("Add a five-year backtest against SPY.", WIDGETS, prior)
    assert backtest.intent == DashboardChatIntent.CREATE_WIDGET and backtest.requires_new_analysis
    refresh = interpret_dashboard_request("Refresh this analysis using the latest verified data.", WIDGETS, prior)
    assert refresh.intent == DashboardChatIntent.CREATE_WIDGET and refresh.requires_new_analysis


def _ready_dashboard_draft() -> dict:
    plan = deterministic_plan("Show portfolio return and drawdown")
    specification = compile_spec(plan)
    draft = database.create_dashboard_job(
        "00000000-0000-0000-0000-000000000001",
        "Show portfolio return and drawdown",
    )
    return database.update_dashboard_job(
        draft["id"],
        "00000000-0000-0000-0000-000000000001",
        state="COMPLETE",
        progress=100,
        plan=plan.model_dump(mode="json"),
        specification=specification,
        widget_results=[],
    )


def test_phase_five_chat_save_duplicate_rename_and_undo_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = "00000000-0000-0000-0000-000000000001"
    conversation_id = "conversation-phase-five"
    monkeypatch.setattr(database, "link_conversation_artifact", lambda *_args, **_kwargs: {})
    draft = _ready_dashboard_draft()

    rename = dashboard_chat.execute_dashboard_chat_request(
        user_id,
        interpret_dashboard_request("Call this Working Overview.", draft["specification"]["widgets"]),
        "draft",
        draft["id"],
        portfolio_id=None,
        conversation_id=conversation_id,
    )
    assert rename.response == "Renamed it Working Overview."
    assert rename.action_result is not None and rename.action_result.status == DashboardActionStatus.SUCCESS

    undo = dashboard_chat.execute_dashboard_chat_request(
        user_id,
        interpret_dashboard_request("Undo that.", rename.action_result.dashboard["specification"]["widgets"]),
        "draft",
        draft["id"],
        portfolio_id=None,
        conversation_id=conversation_id,
    )
    assert undo.action_result is not None and undo.action_result.status == DashboardActionStatus.SUCCESS
    assert undo.action_result.dashboard["specification"]["title"] != "Working Overview"

    save = dashboard_chat.execute_dashboard_chat_request(
        user_id,
        interpret_dashboard_request("Save this as Portfolio Overview.", draft["specification"]["widgets"]),
        "draft",
        draft["id"],
        portfolio_id=None,
        conversation_id=conversation_id,
    )
    assert save.resource_type == "view"
    assert save.action_result is not None and save.action_result.status == DashboardActionStatus.SUCCESS
    assert save.action_result.dashboard["name"] == "Portfolio Overview"

    duplicate = dashboard_chat.execute_dashboard_chat_request(
        user_id,
        interpret_dashboard_request("Make a copy.", save.action_result.dashboard["layout"]),
        "view",
        save.resource_id,
        portfolio_id=None,
        conversation_id=conversation_id,
    )
    assert duplicate.action_result is not None and duplicate.action_result.status == DashboardActionStatus.SUCCESS
    assert duplicate.resource_id != save.resource_id
    assert duplicate.action_result.dashboard["name"] == "Portfolio Overview copy"


@pytest.mark.parametrize(
    "question",
    [
        "Build me a dashboard for monitoring my portfolio.",
        "Create a dashboard for researching NVDA.",
        "Make me a risk dashboard.",
        "Show me everything important about semiconductor exposure in my portfolio.",
        "/design AAPL versus MSFT dashboard",
    ],
)
def test_multi_widget_dashboard_language_routes_to_planner(question: str) -> None:
    request = interpret_dashboard_request(question, WIDGETS)
    assert request.intent == DashboardChatIntent.CREATE_DASHBOARD
    assert request.dashboard_prompt


def test_vague_dashboard_request_uses_portfolio_overview_goal() -> None:
    request = interpret_dashboard_request("Build me a dashboard.", [])
    assert request.intent == DashboardChatIntent.CREATE_DASHBOARD
    assert request.dashboard_prompt == "Build me a dashboard."


def test_dashboard_generation_starts_new_draft_even_when_dashboard_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend import dashboard_workspace

    request = interpret_dashboard_request("Build me a risk dashboard.", WIDGETS)
    monkeypatch.setattr(
        dashboard_workspace, "create_draft",
        lambda _user, payload, _source=None: {
            "id": "generated-draft", "prompt": payload.prompt, "state": "PLANNING", "progress": 2,
            "widget_results": [], "warnings": [],
        },
    )
    result = dashboard_chat.execute_dashboard_chat_request(
        "user-1", request, "view", "existing-view", portfolio_id="portfolio-1", conversation_id="conversation-1",
    )
    assert result.handled is True
    assert result.intent == DashboardChatIntent.CREATE_DASHBOARD
    assert result.resource_type == "draft"
    assert result.resource_id == "generated-draft"
    assert result.action_result is not None and result.action_result.status == DashboardActionStatus.SUCCESS
    assert result.action_result.dashboard["state"] == "PLANNING"


def test_failed_data_preparation_does_not_execute_or_claim_success(monkeypatch: pytest.MonkeyPatch) -> None:
    request = interpret_dashboard_request("Show my sector exposure as a chart.", [])
    monkeypatch.setattr(dashboard_chat, "dashboard_resource_widgets", lambda *_args: [])
    from backend import dashboard_workspace

    monkeypatch.setattr(
        dashboard_workspace,
        "create_empty_dashboard_draft",
        lambda *_args: {"id": "draft-1"},
    )
    monkeypatch.setattr(
        dashboard_workspace,
        "dashboard_resource_state",
        lambda *_args: {"widgets": []},
    )
    monkeypatch.setattr(
        dashboard_workspace,
        "prepare_conversational_widget",
        lambda *_args: (_ for _ in ()).throw(ValueError("missing approved data")),
    )
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("executor must not run")

    monkeypatch.setattr(dashboard_workspace, "run_dashboard_action", fail_if_called)
    result = dashboard_chat.execute_dashboard_chat_request(
        "user-1", request, None, None, portfolio_id="portfolio-1", conversation_id="conversation-1",
    )
    assert called is False
    assert result.action_result is None
    assert result.response is not None and "didn't change" in result.response
    assert "Added" not in result.response


def test_successful_create_uses_typed_executor_and_persists_stable_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend import dashboard_workspace

    request = interpret_dashboard_request("Add my one-year performance against SPY.", [])
    monkeypatch.setattr(
        dashboard_workspace,
        "prepare_conversational_widget",
        lambda _user, _portfolio, _binding, task_id: {
            "widget_id": task_id, "status": "READY", "as_of": "2026-08-20",
            "data": {"total_return": .12, "series": []}, "lineage": [],
            "calculation": {"method": "portfolio_performance", "version": "fixture"},
            "presentation": {"chart": "line", "x_axis": "Date", "y_axis": "Return", "unit": "%", "frequency": "Daily", "timeframe": "1y"},
            "quality": {"data_quality": "high", "reasons": ["fixture"]},
            "assumptions": [], "warnings": [], "how_calculated": "fixture",
        },
    )
    result = dashboard_chat.execute_dashboard_chat_request(
        "00000000-0000-0000-0000-000000000001", request, None, None,
        portfolio_id=None, conversation_id="conversation-1",
    )
    assert result.action_result is not None
    assert result.action_result.status.value == "SUCCESS"
    assert result.resource_type == "draft"
    assert result.widget_id is not None and result.widget_id.startswith("chat-portfolio_performance-")
    created = result.action_result.dashboard["specification"]["widgets"][0]
    assert created["id"] == result.widget_id
    assert created["grid"]["w"] == 12
    assert created["binding"]["benchmark"] == "SPY"
    assert created["binding"]["period"] == "1Y"
    assert result.response == "Added Portfolio Performance."


def test_chat_endpoint_returns_typed_dashboard_operation_without_financial_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    request_row = {}
    monkeypatch.setattr(database, "reserve_ask_request", lambda _user, request_id, question_hash: request_row.setdefault(
        "row", {"request_id": request_id, "question_hash": question_hash, "state": "RECEIVED"},
    ))
    monkeypatch.setattr(database, "bind_ask_request_turn", lambda _user, _request, conversation_id, *_args: request_row["row"].update(
        {"conversation_id": conversation_id, "state": "EXECUTING"},
    ) or request_row["row"])
    monkeypatch.setattr(database, "stage_ask_request_result", lambda _user, _request, staged: request_row["row"].update(
        {"staged_result": staged, "state": "EXECUTED"},
    ) or request_row["row"])

    def complete_request(_user, _request, final_state="COMPLETED"):
        staged = request_row["row"]["staged_result"]
        return {"conversation_id": request_row["row"]["conversation_id"], "message": {
            "id": "message-1", "role": "assistant", "content": staged["answer"],
            "structured_content": staged["structured_content"], "model": staged["model"],
        }, "sources": staged["sources"], "tool_results": staged["tool_results"]}

    monkeypatch.setattr(database, "complete_ask_request", complete_request)
    monkeypatch.setattr(database, "fail_ask_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://fixture")
    monkeypatch.setattr(database, "initialize", lambda: None)
    monkeypatch.setattr(database, "get_conversation", lambda *_args: {
        "id": "conversation-1", "title": "Dashboard chat", "workspace": "research",
        "portfolio_id": None, "summary": "", "summary_message_count": 0,
    })
    monkeypatch.setattr(database, "conversation_messages", lambda *_args: [])
    monkeypatch.setattr(database, "save_chat_message", lambda _user, _conversation, role, content, structured=None, model=None: {
        "id": "message-1", "role": role, "content": content,
        "structured_content": structured or {}, "model": model,
    })
    monkeypatch.setattr(dashboard_chat, "dashboard_resource_widgets", lambda *_args: [PERFORMANCE])
    monkeypatch.setattr(dashboard_chat, "interpret_dashboard_request", lambda *_args: DashboardChatRequest(
        intent=DashboardChatIntent.UPDATE_WIDGET, widget_id="performance", visualization="bar_chart",
    ))
    monkeypatch.setattr(dashboard_chat, "execute_dashboard_chat_request", lambda *_args, **_kwargs: DashboardChatExecution(
        handled=True, intent=DashboardChatIntent.UPDATE_WIDGET, response="Updated Portfolio Performance.",
        resource_type="draft", resource_id="draft-1", widget_id="performance",
        action_result=DashboardActionResult(status=DashboardActionStatus.SUCCESS, dashboard={"id": "draft-1"}),
    ))
    with TestClient(app) as client:
        response = client.post("/api/chat/messages", json={
            "question": "Make that a bar chart.", "conversation_id": "conversation-1", "workspace": "research",
            "page_context": {"dashboard_resource_type": "draft", "dashboard_resource_id": "draft-1"},
        })
    assert response.status_code == 200
    message = response.json()["message"]
    assert message["content"] == "Updated Portfolio Performance."
    assert message["structured_content"]["dashboard_operation"]["action_result"]["status"] == "SUCCESS"
    assert message["structured_content"]["analysis_context"]["dashboard_widget_id"] == "performance"
    assert message["model"] == "deterministic-dashboard-actions-v1"
