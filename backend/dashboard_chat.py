from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .dashboard_actions import DashboardActionResult, DashboardActionStatus, DashboardDataBinding


class DashboardChatIntent(str, Enum):
    NORMAL_ANSWER = "NORMAL_ANSWER"
    CREATE_DASHBOARD = "CREATE_DASHBOARD"
    CREATE_WIDGET = "CREATE_WIDGET"
    UPDATE_WIDGET = "UPDATE_WIDGET"
    DELETE_WIDGET = "DELETE_WIDGET"
    MOVE_WIDGET = "MOVE_WIDGET"
    RESIZE_WIDGET = "RESIZE_WIDGET"
    SAVE_DASHBOARD = "SAVE_DASHBOARD"
    RENAME_DASHBOARD = "RENAME_DASHBOARD"
    DUPLICATE_DASHBOARD = "DUPLICATE_DASHBOARD"
    UNDO_DASHBOARD = "UNDO_DASHBOARD"


class DashboardChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: DashboardChatIntent
    mixed_answer: bool = False
    widget_type: str | None = None
    title: str | None = Field(default=None, max_length=160)
    widget_id: str | None = None
    visualization: str | None = None
    binding: DashboardDataBinding | None = None
    relation: Literal["before", "after"] | None = None
    relative_to_widget_id: str | None = None
    width: int | None = None
    height: int | None = None
    clarification: str | None = None
    dashboard_prompt: str | None = Field(default=None, min_length=3, max_length=3000)
    dashboard_name: str | None = Field(default=None, min_length=1, max_length=120)
    requires_new_analysis: bool = False


class DashboardChatExecution(BaseModel):
    handled: bool = False
    mixed_answer: bool = False
    intent: DashboardChatIntent = DashboardChatIntent.NORMAL_ANSWER
    response: str | None = None
    clarification: str | None = None
    resource_type: Literal["draft", "view"] | None = None
    resource_id: str | None = None
    widget_id: str | None = None
    action_result: DashboardActionResult | None = None


def dashboard_resource_widgets(
    user_id: str,
    resource_type: Literal["draft", "view"],
    resource_id: str,
) -> list[dict[str, Any]]:
    """Load only the owned resource state used by deterministic reference resolution."""
    from .dashboard_workspace import dashboard_resource_state

    return list(dashboard_resource_state(user_id, resource_type, resource_id).get("widgets") or [])


_PERIODS = {
    "one month": "1M", "three months": "3M", "six months": "6M",
    "one year": "1Y", "1 year": "1Y", "1y": "1Y",
    "three years": "3Y", "3 years": "3Y", "3y": "3Y",
    "five years": "5Y", "5 years": "5Y", "5y": "5Y",
    "seven years": "7Y", "7 years": "7Y", "7y": "7Y",
    "ten years": "10Y", "10 years": "10Y", "10y": "10Y",
    "twenty years": "20Y", "20 years": "20Y", "20y": "20Y",
}


def _period(question: str) -> str | None:
    lower = question.lower()
    return next((value for phrase, value in _PERIODS.items() if phrase in lower), None)


def _visualization(question: str) -> str | None:
    lower = question.lower()
    if "bar chart" in lower or "bar graph" in lower:
        return "bar_chart"
    if "line chart" in lower or "line graph" in lower:
        return "line_chart"
    if "area chart" in lower:
        return "area_chart"
    if "table" in lower:
        return "table"
    if "heatmap" in lower or "heat map" in lower:
        return "heatmap"
    return None


def _widget_kind(question: str) -> tuple[str | None, str | None, str | None]:
    lower = question.lower()
    visualization = _visualization(question)
    if "sector" in lower and any(term in lower for term in ("exposure", "allocation", "concentrat")):
        return "sector_exposure", visualization or "bar_chart", "Sector Exposure"
    if any(term in lower for term in ("concentrated", "concentration")):
        return "sector_exposure", visualization or "bar_chart", "Sector Exposure"
    if "risk contributor" in lower:
        return "portfolio_risk", visualization or "bar_chart", "Largest Risk Contributors"
    if any(term in lower for term in ("performance", "return")) and any(term in lower for term in ("portfolio", "my ", "against", "benchmark")):
        return "portfolio_performance", visualization or "line_chart", "Portfolio Performance"
    if "allocation" in lower:
        return "allocation", visualization or "bar_chart", "Current Allocation"
    if "correlation" in lower or "heatmap" in lower or "heat map" in lower:
        return "correlation_matrix", visualization or "heatmap", "Return Correlations"
    if "valuation" in lower and "table" in lower:
        return "security_comparison", "table", "Valuation and Fundamentals"
    if any(term in lower for term in ("research table", "holdings table", "stock table", "securities table")):
        return "security_comparison", visualization or "table", "Security Research"
    return None, visualization, None


def visual_suggestion_for(question: str) -> dict[str, str] | None:
    """Offer one explicit, non-mutating visualization follow-up when useful."""
    lower = question.lower()
    if any(term in lower for term in ("concentrat", "sector exposure", "sector allocation")):
        return {"label": "Visualize concentration", "prompt": "Add a sector exposure chart to this dashboard."}
    if any(term in lower for term in ("performance", "return", "against spy")):
        return {"label": "Chart performance", "prompt": "Add portfolio performance against SPY to this dashboard."}
    if any(term in lower for term in ("correlation", "overlap", "diversif")):
        return {"label": "Visualize correlations", "prompt": "Add a holdings correlation heatmap to this dashboard."}
    return None


def _is_chart(widget: dict[str, Any]) -> bool:
    return str(widget.get("visualization") or "").lower() not in {"table", "list", "summary", "cards"}


def _candidate_label(widget: dict[str, Any]) -> str:
    return str(widget.get("title") or widget.get("widget_type") or widget.get("id"))


def resolve_widget_reference(
    question: str,
    widgets: list[dict[str, Any]],
    previous_context: dict[str, Any] | None = None,
    *,
    exclude_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    candidates = [widget for widget in widgets if str(widget.get("id")) != exclude_id]
    if not candidates:
        return None, "There isn't a widget on the canvas to change yet."
    lower = question.lower()
    previous_id = str((previous_context or {}).get("dashboard_widget_id") or "")

    # Named references are safest and take precedence over pronouns and position.
    aliases = {
        "sector": ("sector",), "performance": ("performance", "return"),
        "allocation": ("allocation",), "news": ("news",), "correlation": ("correlation",),
        "research": ("research",), "holdings": ("holdings", "securities"),
        "valuation": ("valuation",),
    }
    named: list[dict[str, Any]] = []
    for key, terms in aliases.items():
        if not any(term in lower for term in terms):
            continue
        matches = [widget for widget in candidates if key in " ".join(
            str(widget.get(field) or "") for field in ("title", "widget_type", "visualization")
        ).lower()]
        named.extend(matches)
    named = list({str(widget.get("id")): widget for widget in named}.values())
    if len(named) == 1:
        return named[0], None
    if len(named) > 1:
        labels = " or ".join(_candidate_label(widget) for widget in named[:4])
        return None, f"Which widget do you mean: {labels}?"

    charts = [widget for widget in candidates if _is_chart(widget)]
    tables = [widget for widget in candidates if str(widget.get("visualization")).lower() == "table"]
    pool = tables if "table" in lower else charts if "chart" in lower or "graph" in lower else candidates
    implicit_follow_up = lower.startswith(("show only", "compare against", "benchmark against", "change to"))
    if (any(term in lower for term in ("that", " it", "this widget", "instead")) or implicit_follow_up) and previous_id:
        previous = next((widget for widget in pool if str(widget.get("id")) == previous_id), None)
        if previous:
            return previous, None
    if "last chart" in lower:
        return (charts[-1], None) if charts else (None, "There isn't a chart on the canvas yet.")
    if "bottom" in lower:
        ranked = sorted(pool, key=lambda item: (int((item.get("grid") or {}).get("y", 0)), int((item.get("grid") or {}).get("x", 0))), reverse=True)
        return ranked[0], None
    if "top right" in lower or "on the right" in lower or "right chart" in lower:
        ranked = sorted(pool, key=lambda item: (int((item.get("grid") or {}).get("x", 0)), -int((item.get("grid") or {}).get("y", 0))), reverse=True)
        if len(ranked) > 1 and (ranked[0].get("grid") or {}).get("x") == (ranked[1].get("grid") or {}).get("x"):
            return None, f"Which widget do you mean: {_candidate_label(ranked[0])} or {_candidate_label(ranked[1])}?"
        return ranked[0], None
    if len(pool) == 1:
        return pool[0], None
    labels = " or ".join(_candidate_label(widget) for widget in pool[:4])
    noun = "chart" if pool is charts else "table" if pool is tables else "widget"
    return None, f"Which {noun} do you mean: {labels}?"


def _binding_for(question: str, metric: str, prior: dict[str, Any] | None = None) -> DashboardDataBinding:
    lower = question.lower()
    prior_binding = (prior or {}).get("binding") if isinstance((prior or {}).get("binding"), dict) else {}
    period = _period(question) or str(prior_binding.get("period") or "1Y")
    benchmark_match = re.search(r"(?:against|versus|vs\.?|benchmark(?:ed)?\s+(?:against|to)?)\s+([A-Z]{1,10})\b", question, re.I)
    benchmark = benchmark_match.group(1).upper() if benchmark_match else prior_binding.get("benchmark")
    filters = list(prior_binding.get("filters") or [])
    only_match = re.search(r"show\s+only\s+(.+?)(?:\s+in\s+that|\s+in\s+the|$)", lower)
    if only_match:
        value = re.sub(r"\s+(?:holdings|stocks|securities)$", "", only_match.group(1).strip(" ."))
        filters = [{"field": "classification", "operator": "contains", "value": value}]
    return DashboardDataBinding(metric=metric, period=period, benchmark=benchmark, filters=filters)


def interpret_dashboard_request(
    question: str,
    widgets: list[dict[str, Any]],
    previous_context: dict[str, Any] | None = None,
) -> DashboardChatRequest:
    lower = " ".join(question.lower().split())
    save_match = re.fullmatch(r"save (?:this|the)(?: dashboard)?(?: as (.+?))?[.!]?", question.strip(), re.I)
    if save_match:
        name = save_match.group(1).strip(" .") if save_match.group(1) else None
        return DashboardChatRequest(intent=DashboardChatIntent.SAVE_DASHBOARD, dashboard_name=name)
    rename_match = re.fullmatch(r"(?:call|rename) (?:this|the dashboard)(?: as)? (.+?)[.!]?", question.strip(), re.I)
    if rename_match:
        return DashboardChatRequest(intent=DashboardChatIntent.RENAME_DASHBOARD, dashboard_name=rename_match.group(1).strip(" ."))
    duplicate_match = re.fullmatch(r"(?:duplicate (?:this|the dashboard)|make (?:a )?copy)(?: for (.+?))?[.!]?", question.strip(), re.I)
    if duplicate_match:
        suffix = duplicate_match.group(1).strip(" .") if duplicate_match.group(1) else None
        name = f"{suffix.title()} copy" if suffix else None
        return DashboardChatRequest(intent=DashboardChatIntent.DUPLICATE_DASHBOARD, dashboard_name=name)
    undo_match = re.fullmatch(r"(?:undo (?:that|(?:the )?last change)|revert (?:the )?(.+?) change)[.!]?", question.strip(), re.I)
    if undo_match:
        widget_id = None
        clarification = None
        if undo_match.group(1):
            target, clarification = resolve_widget_reference(undo_match.group(1), widgets, previous_context)
            widget_id = str(target.get("id")) if target else None
        return DashboardChatRequest(intent=DashboardChatIntent.UNDO_DASHBOARD, widget_id=widget_id, clarification=clarification)
    forced_design = lower.startswith("/design")
    dashboard_build = forced_design or bool(re.search(r"\b(?:build|create|make|generate|design)\b.{0,40}\bdashboard\b", lower))
    dashboard_build = dashboard_build or (
        "show me everything important" in lower
        and any(term in lower for term in ("portfolio", "exposure", "stock", "company", "risk"))
    )
    if dashboard_build:
        prompt = re.sub(r"^/design\s*", "", question, flags=re.I).strip()
        return DashboardChatRequest(intent=DashboardChatIntent.CREATE_DASHBOARD, dashboard_prompt=prompt or "Build a portfolio overview dashboard", requires_new_analysis=True)
    if widgets and re.search(r"\brefresh\b.*\b(?:analysis|data|view|dashboard|verified)\b|\b(?:analysis|data|view|dashboard)\b.*\brefresh\b", lower):
        return DashboardChatRequest(
            intent=DashboardChatIntent.CREATE_WIDGET,
            mixed_answer=True,
            requires_new_analysis=True,
        )
    if "backtest" in lower and any(term in lower for term in ("add", "show", "chart", "dashboard")):
        return DashboardChatRequest(intent=DashboardChatIntent.CREATE_WIDGET, mixed_answer=True, widget_type="portfolio_backtest", title="Portfolio Backtest", visualization="line_chart", requires_new_analysis=True)
    if "market regime" in lower and any(term in lower for term in ("compare", "add", "show")):
        return DashboardChatRequest(intent=DashboardChatIntent.CREATE_WIDGET, mixed_answer=True, widget_type="market_state", title="Current Market Regime", visualization="cards", requires_new_analysis=True)
    visual_word = any(term in lower for term in ("chart", "graph", "table", "heatmap", "heat map", "visually", "widget"))
    create_word = any(re.search(pattern, lower) for pattern in (r"\badd\b", r"\bshow\b", r"\bdisplay\b", r"\bvisualize\b", r"\bplot\b"))
    delete_word = any(term in lower for term in ("remove", "delete"))
    move_word = any(term in lower for term in ("move ", "put ")) and any(term in lower for term in ("above", "below", "before", "after"))
    resize_word = any(term in lower for term in ("wider", "narrower", "full width", "larger", "smaller", "resize"))
    update_word = any(term in lower for term in ("change ", "make ", "show only", "compare against", "benchmark against", "instead"))

    if delete_word and visual_word:
        target, clarification = resolve_widget_reference(question, widgets, previous_context)
        return DashboardChatRequest(intent=DashboardChatIntent.DELETE_WIDGET, widget_id=str(target.get("id")) if target else None, clarification=clarification)
    if move_word:
        target_phrase = re.split(r"\s+(?:below|above|before|after)\s+", question, maxsplit=1, flags=re.I)[0]
        target, clarification = resolve_widget_reference(target_phrase, widgets, previous_context)
        relation = "after" if any(term in lower for term in ("below", "after")) else "before"
        relative_parts = re.split(r"\s+(?:below|above|before|after)\s+", question, maxsplit=1, flags=re.I)
        relative_phrase = relative_parts[1] if len(relative_parts) == 2 else question
        relative, relative_clarification = resolve_widget_reference(relative_phrase, widgets, previous_context, exclude_id=str(target.get("id")) if target else None)
        return DashboardChatRequest(
            intent=DashboardChatIntent.MOVE_WIDGET,
            widget_id=str(target.get("id")) if target else None,
            relation=relation,
            relative_to_widget_id=str(relative.get("id")) if relative else None,
            clarification=clarification or relative_clarification,
        )
    if resize_word:
        target, clarification = resolve_widget_reference(question, widgets, previous_context)
        current_width = int(((target or {}).get("grid") or {}).get("w", 6))
        widths = [4, 6, 8, 12]
        if "full width" in lower:
            width = 12
        elif any(term in lower for term in ("wider", "larger")):
            width = next((value for value in widths if value > current_width), 12)
        else:
            width = next((value for value in reversed(widths) if value < current_width), 4)
        return DashboardChatRequest(intent=DashboardChatIntent.RESIZE_WIDGET, widget_id=str(target.get("id")) if target else None, width=width, height=int(((target or {}).get("grid") or {}).get("h", 2)), clarification=clarification)
    if update_word and (visual_word or "show only" in lower or _period(question) or re.search(r"(?:against|versus|vs\.?|benchmark)\s+[A-Z]", question, re.I)):
        target, clarification = resolve_widget_reference(question, widgets, previous_context)
        prior = target or {}
        metric = str((prior.get("binding") or {}).get("metric") or prior.get("widget_type") or "")
        binding = _binding_for(question, metric, prior) if metric else None
        requested_visual = _visualization(question)
        requires_analysis = bool(_period(question) or "show only" in lower or re.search(r"(?:against|versus|vs\.?|benchmark)\s+[A-Z]", question, re.I))
        return DashboardChatRequest(intent=DashboardChatIntent.UPDATE_WIDGET, widget_id=str(target.get("id")) if target else None, visualization=requested_visual, binding=binding, clarification=clarification, requires_new_analysis=requires_analysis)
    if create_word and (visual_word or "exposure" in lower or "performance" in lower or "risk contributor" in lower):
        widget_type, visualization, title = _widget_kind(question)
        if not widget_type:
            return DashboardChatRequest(intent=DashboardChatIntent.CREATE_WIDGET, clarification="What should the new widget show?")
        mixed = any(term in lower for term in ("where ", "what ", "why ", "analyze", "explain")) and "show" in lower
        return DashboardChatRequest(intent=DashboardChatIntent.CREATE_WIDGET, mixed_answer=mixed, widget_type=widget_type, title=title, visualization=visualization, binding=_binding_for(question, widget_type), requires_new_analysis=True)
    if create_word and any(term in lower for term in ("visualize", "visually", "plot")):
        return DashboardChatRequest(intent=DashboardChatIntent.CREATE_WIDGET, mixed_answer=True, requires_new_analysis=True)
    return DashboardChatRequest(intent=DashboardChatIntent.NORMAL_ANSWER)


def execute_dashboard_chat_request(
    user_id: str,
    request: DashboardChatRequest,
    resource_type: Literal["draft", "view"] | None,
    resource_id: str | None,
    *,
    portfolio_id: str | None,
    conversation_id: str,
) -> DashboardChatExecution:
    if request.intent == DashboardChatIntent.NORMAL_ANSWER:
        return DashboardChatExecution()
    if request.clarification:
        return DashboardChatExecution(handled=True, intent=request.intent, clarification=request.clarification, response=request.clarification)
    from . import dashboard_workspace
    from . import database

    try:
        if request.intent == DashboardChatIntent.CREATE_DASHBOARD:
            prompt = request.dashboard_prompt or "Build a portfolio overview dashboard"
            draft = dashboard_workspace.create_draft(
                user_id,
                dashboard_workspace.DraftRequest(
                    prompt=prompt, portfolio_id=portfolio_id, conversation_id=conversation_id,
                ),
            )
            result = DashboardActionResult(
                status=DashboardActionStatus.SUCCESS,
                action={"type": "CREATE_DASHBOARD", "goal": prompt},
                dashboard=draft,
            )
            return DashboardChatExecution(
                handled=True, intent=request.intent,
                response="I’m building a focused dashboard from approved EagleEyes data. Valid widgets will appear on the canvas as their calculations finish.",
                resource_type="draft", resource_id=str(draft["id"]), action_result=result,
            )
        if request.intent == DashboardChatIntent.SAVE_DASHBOARD:
            if not resource_type or not resource_id:
                return DashboardChatExecution(handled=True, intent=request.intent, response="There isn't a dashboard on the canvas to save yet.")
            if resource_type == "view":
                saved = database.get_dashboard_view(resource_id, user_id)
                if request.dashboard_name and request.dashboard_name != saved.get("name"):
                    result = dashboard_workspace.run_dashboard_action(
                        user_id, "view", resource_id,
                        {"type": "RENAME_DASHBOARD", "name": request.dashboard_name},
                    )
                    if result.status != DashboardActionStatus.SUCCESS:
                        return DashboardChatExecution(
                            handled=True,
                            intent=request.intent,
                            response=f"I couldn't save that name: {result.error}",
                            resource_type="view",
                            resource_id=resource_id,
                            action_result=result,
                        )
                    saved = result.dashboard or saved
                else:
                    result = DashboardActionResult(status=DashboardActionStatus.SUCCESS, action={"type": "SAVE_DASHBOARD"}, dashboard=saved)
                return DashboardChatExecution(handled=True, intent=request.intent, response=f"Saved as {saved['name']}.", resource_type="view", resource_id=resource_id, action_result=result)
            draft = database.get_dashboard_job(resource_id, user_id)
            if draft.get("state") not in {"COMPLETE", "PARTIAL_SUCCESS"}:
                return DashboardChatExecution(handled=True, intent=request.intent, response="The dashboard is still loading. Save it when the available widgets finish.", resource_type="draft", resource_id=resource_id)
            saved = database.save_dashboard_view(user_id, resource_id, request.dashboard_name)
            database.link_conversation_artifact(
                user_id, conversation_id, "dashboard_view", saved["id"], saved.get("name") or "Saved dashboard",
                metadata={"job_id": resource_id},
            )
            result = DashboardActionResult(status=DashboardActionStatus.SUCCESS, action={"type": "SAVE_DASHBOARD"}, dashboard=saved)
            return DashboardChatExecution(handled=True, intent=request.intent, response=f"Saved as {saved['name']}.", resource_type="view", resource_id=str(saved["id"]), action_result=result)
        if request.intent == DashboardChatIntent.RENAME_DASHBOARD:
            if not resource_type or not resource_id:
                return DashboardChatExecution(handled=True, intent=request.intent, response="There isn't a dashboard on the canvas to rename yet.")
            result = dashboard_workspace.run_dashboard_action(
                user_id, resource_type, resource_id,
                {"type": "RENAME_DASHBOARD", "name": request.dashboard_name},
            )
            if result.status != DashboardActionStatus.SUCCESS:
                return DashboardChatExecution(handled=True, intent=request.intent, response=f"I couldn't rename the dashboard: {result.error}", resource_type=resource_type, resource_id=resource_id, action_result=result)
            return DashboardChatExecution(handled=True, intent=request.intent, response=f"Renamed it {request.dashboard_name}.", resource_type=resource_type, resource_id=resource_id, action_result=result)
        if request.intent == DashboardChatIntent.DUPLICATE_DASHBOARD:
            if not resource_type or not resource_id:
                return DashboardChatExecution(handled=True, intent=request.intent, response="There isn't a dashboard on the canvas to duplicate yet.")
            if resource_type == "draft":
                return DashboardChatExecution(handled=True, intent=request.intent, response="Save this draft first, then I can make a persistent copy without silently saving it for you.", resource_type=resource_type, resource_id=resource_id)
            duplicated = database.duplicate_dashboard_view(resource_id, user_id, request.dashboard_name)
            database.link_conversation_artifact(
                user_id, conversation_id, "dashboard_view", duplicated["id"], duplicated.get("name") or "Dashboard copy",
                metadata={"source_view_id": resource_id},
            )
            result = DashboardActionResult(status=DashboardActionStatus.SUCCESS, action={"type": "DUPLICATE_DASHBOARD"}, dashboard=duplicated)
            return DashboardChatExecution(handled=True, intent=request.intent, response=f"Created {duplicated['name']}.", resource_type="view", resource_id=str(duplicated["id"]), action_result=result)
        if request.intent == DashboardChatIntent.UNDO_DASHBOARD:
            if not resource_type or not resource_id:
                return DashboardChatExecution(handled=True, intent=request.intent, response="There isn't an active dashboard change to undo.")
            from .dashboard_actions import undo_dashboard_action
            result = undo_dashboard_action(user_id, resource_type, resource_id, widget_id=request.widget_id)
            if result.status != DashboardActionStatus.SUCCESS:
                return DashboardChatExecution(handled=True, intent=request.intent, response=f"I couldn't undo that change: {result.error}", resource_type=resource_type, resource_id=resource_id, action_result=result)
            return DashboardChatExecution(handled=True, intent=request.intent, response="Undid the last matching dashboard change.", resource_type=resource_type, resource_id=resource_id, widget_id=request.widget_id, action_result=result)
        if not resource_type or not resource_id:
            if request.intent != DashboardChatIntent.CREATE_WIDGET:
                return DashboardChatExecution(handled=True, intent=request.intent, response="There isn't a dashboard on the canvas to change yet.")
            empty = dashboard_workspace.create_empty_dashboard_draft(user_id, portfolio_id, conversation_id)
            resource_type, resource_id = "draft", str(empty["id"])
        state = dashboard_workspace.dashboard_resource_state(user_id, resource_type, resource_id)
        widgets = state.get("widgets") or []
        action: dict[str, Any]
        prepared_result: dict[str, Any] | None = None
        if request.intent == DashboardChatIntent.CREATE_WIDGET:
            assert request.widget_type and request.binding
            task_id = dashboard_workspace.new_conversational_task_id(request.widget_type)
            prepared_result = dashboard_workspace.prepare_conversational_widget(user_id, portfolio_id, request.binding, task_id)
            dashboard_workspace.persist_prepared_widget_result(user_id, resource_type, resource_id, prepared_result)
            meta = dashboard_workspace.widget_meta(request.widget_type)
            action = {"type": "CREATE_WIDGET", "widget": {
                "id": task_id, "task_id": task_id, "widget_type": request.widget_type,
                "title": request.title or meta[0], "visualization": request.visualization or meta[1],
                "grid": dashboard_workspace.next_widget_grid(widgets, meta[2], meta[3]),
                "binding": request.binding.model_dump(mode="json"),
            }}
        else:
            target = next((widget for widget in widgets if str(widget.get("id")) == request.widget_id), None)
            if not target:
                return DashboardChatExecution(handled=True, intent=request.intent, response="I couldn't find that widget, so I didn't change the dashboard.")
            if request.intent == DashboardChatIntent.UPDATE_WIDGET:
                changes: dict[str, Any] = {}
                if request.visualization and request.visualization != target.get("visualization"):
                    changes["visualization"] = request.visualization
                prior_binding = DashboardDataBinding.model_validate(
                    target.get("binding") or {"metric": target.get("widget_type"), "period": "1Y"}
                ).model_dump(mode="json")
                if request.binding and request.binding.model_dump(mode="json") != prior_binding:
                    changes["binding"] = request.binding.model_dump(mode="json")
                    prepared_result = dashboard_workspace.prepare_conversational_widget(
                        user_id, portfolio_id, request.binding, str(target.get("task_id")),
                    )
                if not changes:
                    return DashboardChatExecution(handled=True, intent=request.intent, response=f"{_candidate_label(target)} already uses those settings.", resource_type=resource_type, resource_id=resource_id, widget_id=str(target.get("id")))
                action = {"type": "UPDATE_WIDGET", "widget_id": request.widget_id, "changes": changes}
            elif request.intent == DashboardChatIntent.DELETE_WIDGET:
                action = {"type": "DELETE_WIDGET", "widget_id": request.widget_id}
            elif request.intent == DashboardChatIntent.RESIZE_WIDGET:
                action = {"type": "RESIZE_WIDGET", "widget_id": request.widget_id, "width": request.width, "height": request.height}
            else:
                relative_index = next((index for index, widget in enumerate(widgets) if str(widget.get("id")) == request.relative_to_widget_id), -1)
                if relative_index < 0:
                    return DashboardChatExecution(handled=True, intent=request.intent, response="I couldn't find the destination widget, so I didn't move anything.")
                destination = relative_index + (1 if request.relation == "after" else 0)
                moving_index = next(index for index, widget in enumerate(widgets) if str(widget.get("id")) == request.widget_id)
                if moving_index < destination:
                    destination -= 1
                action = {"type": "MOVE_WIDGET", "widget_id": request.widget_id, "to_index": max(0, min(destination, len(widgets) - 1))}
        result = dashboard_workspace.run_dashboard_action(user_id, resource_type, resource_id, action)
        if result.status != DashboardActionStatus.SUCCESS:
            return DashboardChatExecution(handled=True, intent=request.intent, response=f"I couldn't update the dashboard: {result.error}", resource_type=resource_type, resource_id=resource_id, action_result=result)
        if prepared_result is not None and request.intent == DashboardChatIntent.UPDATE_WIDGET:
            dashboard_workspace.persist_prepared_widget_result(user_id, resource_type, resource_id, prepared_result)
            result.dashboard = dashboard_workspace.dashboard_resource_state(user_id, resource_type, resource_id).get("resource")
        updated_widgets = dashboard_workspace.dashboard_resource_state(user_id, resource_type, resource_id).get("widgets") or []
        changed = next((widget for widget in updated_widgets if str(widget.get("id")) == str((result.action or {}).get("widget_id") or ((result.action or {}).get("widget") or {}).get("id"))), None)
        original_target = target if "target" in locals() else None
        title = _candidate_label(changed or original_target or {})
        responses = {
            DashboardChatIntent.CREATE_WIDGET: f"Added {title}.",
            DashboardChatIntent.UPDATE_WIDGET: f"Updated {title}.",
            DashboardChatIntent.DELETE_WIDGET: f"Removed {title}.",
            DashboardChatIntent.MOVE_WIDGET: f"Moved {title}.",
            DashboardChatIntent.RESIZE_WIDGET: f"Resized {title}.",
        }
        return DashboardChatExecution(
            handled=True, mixed_answer=request.mixed_answer, intent=request.intent,
            response=responses[request.intent], resource_type=resource_type, resource_id=resource_id,
            widget_id=str((changed or {}).get("id") or request.widget_id or "") or None,
            action_result=result,
        )
    except Exception:
        noun = "data" if request.intent in {DashboardChatIntent.CREATE_WIDGET, DashboardChatIntent.UPDATE_WIDGET} else "dashboard change"
        return DashboardChatExecution(handled=True, intent=request.intent, response=f"I couldn't load the required {noun}, so I didn't change the dashboard.")
