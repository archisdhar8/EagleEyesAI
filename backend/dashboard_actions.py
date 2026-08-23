from __future__ import annotations

import copy
import uuid
from enum import Enum
from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator


ACTION_VERSION = "dashboard-action-v1"
LAYOUT_VERSION = "dashboard-layout-v2"
GRID_COLUMNS = 12
ALLOWED_WIDTHS = {4, 6, 8, 12}
ALLOWED_VISUALIZATIONS = {
    "area", "area_chart", "bar", "bar_chart", "cards", "comparison", "heatmap", "line",
    "line_chart", "list", "scatter_plot", "summary", "table",
}


class DashboardActionType(str, Enum):
    CREATE_WIDGET = "CREATE_WIDGET"
    UPDATE_WIDGET = "UPDATE_WIDGET"
    DELETE_WIDGET = "DELETE_WIDGET"
    MOVE_WIDGET = "MOVE_WIDGET"
    RESIZE_WIDGET = "RESIZE_WIDGET"
    CLEAR_DASHBOARD = "CLEAR_DASHBOARD"
    RENAME_DASHBOARD = "RENAME_DASHBOARD"
    DUPLICATE_WIDGET = "DUPLICATE_WIDGET"
    CHANGE_VISUALIZATION = "CHANGE_VISUALIZATION"
    UPDATE_FILTER = "UPDATE_FILTER"
    UPDATE_DATE_RANGE = "UPDATE_DATE_RANGE"


class DashboardActionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"


class DashboardGrid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0, lt=GRID_COLUMNS)
    y: int = Field(ge=0, le=10_000)
    w: int
    h: int = Field(ge=2, le=6)

    @model_validator(mode="after")
    def validate_grid(self) -> "DashboardGrid":
        if self.w not in ALLOWED_WIDTHS:
            raise ValueError("Widget width must be 4, 6, 8, or 12")
        if self.x + self.w > GRID_COLUMNS:
            raise ValueError("Widget layout exceeds the 12-column dashboard grid")
        return self


class DashboardFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=80)
    operator: Literal["eq", "neq", "contains", "in"] = "eq"
    value: str | list[str]


class DashboardDataBinding(BaseModel):
    """Refreshable, lineage-preserving description of a widget's approved data."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=2, max_length=80)
    portfolio: str | None = Field(default="current", max_length=120)
    benchmark: str | None = Field(default=None, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9.-]{0,9}$")
    period: str = Field(default="1Y", pattern=r"^(?:1M|3M|6M|1Y|3Y|5Y|7Y|10Y|20Y)$")
    tickers: list[str] = Field(default_factory=list, max_length=50)
    filters: list[DashboardFilter] = Field(default_factory=list, max_length=12)


class DashboardWidget(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = Field(default=None, min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=120)
    widget_type: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    visualization: str = Field(min_length=2, max_length=80)
    grid: DashboardGrid
    binding: DashboardDataBinding | None = None
    source_result_id: str | None = Field(default=None, pattern=r"^(?:result|composed)_[a-f0-9]{16,20}$")
    source_capability: str | None = Field(default=None, min_length=2, max_length=100)
    source_category: Literal["VERIFIED", "MODEL_OUTPUT", "MARKET_IMPLIED", "USER_THESIS"] | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "DashboardWidget":
        if self.widget_type == "canonical_result" and (not self.source_result_id or not self.source_capability):
            raise ValueError("Canonical result widgets require a verified result reference and capability")
        return self


class DashboardWidgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    visualization: str | None = Field(default=None, min_length=2, max_length=80)
    binding: DashboardDataBinding | None = None

    @model_validator(mode="after")
    def require_change(self) -> "DashboardWidgetUpdate":
        if self.title is None and self.visualization is None and self.binding is None:
            raise ValueError("UPDATE_WIDGET requires at least one changed field")
        return self


class CreateWidgetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.CREATE_WIDGET]
    widget: DashboardWidget


class UpdateWidgetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.UPDATE_WIDGET]
    widget_id: str = Field(min_length=1, max_length=120)
    changes: DashboardWidgetUpdate


class DeleteWidgetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.DELETE_WIDGET]
    widget_id: str = Field(min_length=1, max_length=120)


class MoveWidgetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.MOVE_WIDGET]
    widget_id: str = Field(min_length=1, max_length=120)
    to_index: int | None = Field(default=None, ge=0, le=500)
    position: "DashboardPosition | None" = None

    @model_validator(mode="after")
    def require_destination(self) -> "MoveWidgetAction":
        if self.to_index is None and self.position is None:
            raise ValueError("MOVE_WIDGET requires a target index or grid position")
        return self


class DashboardPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, lt=GRID_COLUMNS)
    y: int = Field(ge=0, le=10_000)


class ResizeWidgetAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.RESIZE_WIDGET]
    widget_id: str = Field(min_length=1, max_length=120)
    width: int
    height: int = Field(ge=2, le=6)


class ChangeVisualizationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.CHANGE_VISUALIZATION]
    widget_id: str = Field(min_length=1, max_length=120)
    visualization: str = Field(min_length=2, max_length=80)


class UpdateFilterAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.UPDATE_FILTER]
    widget_id: str = Field(min_length=1, max_length=120)
    filters: list[DashboardFilter] = Field(max_length=12)


class UpdateDateRangeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.UPDATE_DATE_RANGE]
    widget_id: str = Field(min_length=1, max_length=120)
    period: str = Field(pattern=r"^(?:1M|3M|6M|1Y|3Y|5Y|7Y|10Y|20Y)$")


class ClearDashboardAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.CLEAR_DASHBOARD]


class RenameDashboardAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[DashboardActionType.RENAME_DASHBOARD]
    name: str = Field(min_length=1, max_length=120)


DashboardAction = Annotated[
    CreateWidgetAction | UpdateWidgetAction | DeleteWidgetAction | MoveWidgetAction |
    ResizeWidgetAction | ChangeVisualizationAction | UpdateFilterAction | UpdateDateRangeAction |
    ClearDashboardAction | RenameDashboardAction,
    Field(discriminator="type"),
]
DASHBOARD_ACTION_ADAPTER = TypeAdapter(DashboardAction)


class DashboardActionResult(BaseModel):
    version: str = ACTION_VERSION
    status: DashboardActionStatus
    action: dict[str, Any] | None = None
    dashboard: dict[str, Any] | None = None
    revision: dict[str, Any] | None = None
    error: str | None = None


def _failure(status: DashboardActionStatus, error: str, action: Any = None) -> DashboardActionResult:
    payload = action if isinstance(action, dict) else None
    return DashboardActionResult(status=status, action=payload, error=error)


def parse_dashboard_action(value: Any) -> DashboardAction | DashboardActionResult:
    action_type = value.get("type") if isinstance(value, dict) else None
    if action_type in {
        DashboardActionType.DUPLICATE_WIDGET.value,
    }:
        return _failure(DashboardActionStatus.UNSUPPORTED, f"{action_type} is reserved but not supported in Phase 2", value)
    try:
        return DASHBOARD_ACTION_ADAPTER.validate_python(value)
    except ValidationError as exc:
        return _failure(DashboardActionStatus.INVALID, str(exc), value)


def _widget_index(widgets: list[dict[str, Any]], widget_id: str) -> int:
    return next((index for index, widget in enumerate(widgets) if str(widget.get("id")) == widget_id), -1)


def _normalize_widget(widget: DashboardWidget, widgets: list[dict[str, Any]]) -> dict[str, Any]:
    payload = widget.model_dump(mode="json", exclude_none=True)
    payload["id"] = payload.get("id") or f"widget-{uuid.uuid4()}"
    if _widget_index(widgets, payload["id"]) >= 0:
        raise ValueError(f"Widget ID {payload['id']} already exists")
    return payload


VISUALIZATIONS_BY_WIDGET: dict[str, set[str]] = {
    "portfolio_performance": {"line", "line_chart", "area", "area_chart", "bar", "bar_chart"},
    "security_performance": {"line", "line_chart", "area", "area_chart", "bar", "bar_chart"},
    "allocation": {"bar", "bar_chart", "table"},
    "sector_exposure": {"bar", "bar_chart", "table"},
    "security_comparison": {"table", "bar", "bar_chart"},
    "candidate_ranking": {"table", "bar", "bar_chart"},
}


def _visualization_supported(widget_type: str, visualization: str) -> bool:
    supported = VISUALIZATIONS_BY_WIDGET.get(widget_type)
    return visualization in (supported or ALLOWED_VISUALIZATIONS)


def apply_dashboard_action(
    state: dict[str, Any],
    action_value: DashboardAction | dict[str, Any],
    *,
    allowed_widget_types: set[str],
    available_task_ids: set[str] | None = None,
) -> DashboardActionResult:
    parsed = action_value if isinstance(action_value, BaseModel) else parse_dashboard_action(action_value)
    if isinstance(parsed, DashboardActionResult):
        return parsed
    action = parsed
    action_payload = action.model_dump(mode="json")
    next_state = copy.deepcopy(state)
    widgets = [dict(item) for item in next_state.get("widgets") or []]
    try:
        if isinstance(action, CreateWidgetAction):
            if action.widget.widget_type not in allowed_widget_types:
                return _failure(DashboardActionStatus.INVALID, f"Unsupported widget type: {action.widget.widget_type}", action_payload)
            if action.widget.visualization not in ALLOWED_VISUALIZATIONS or not _visualization_supported(action.widget.widget_type, action.widget.visualization):
                return _failure(DashboardActionStatus.INVALID, f"Unsupported visualization: {action.widget.visualization}", action_payload)
            if available_task_ids is not None and action.widget.task_id not in available_task_ids:
                return _failure(DashboardActionStatus.INVALID, f"Unknown data binding: {action.widget.task_id}", action_payload)
            widgets.append(_normalize_widget(action.widget, widgets))
        elif isinstance(action, UpdateWidgetAction):
            index = _widget_index(widgets, action.widget_id)
            if index < 0:
                return _failure(DashboardActionStatus.INVALID, f"Widget not found: {action.widget_id}", action_payload)
            changes = action.changes.model_dump(exclude_none=True)
            if "visualization" in changes and not _visualization_supported(str(widgets[index].get("widget_type")), changes["visualization"]):
                return _failure(DashboardActionStatus.UNSUPPORTED, "That visualization is not supported for this widget", action_payload)
            widgets[index] = {**widgets[index], **changes}
        elif isinstance(action, DeleteWidgetAction):
            index = _widget_index(widgets, action.widget_id)
            if index < 0:
                return _failure(DashboardActionStatus.INVALID, f"Widget not found: {action.widget_id}", action_payload)
            widgets.pop(index)
        elif isinstance(action, MoveWidgetAction):
            index = _widget_index(widgets, action.widget_id)
            if index < 0:
                return _failure(DashboardActionStatus.INVALID, f"Widget not found: {action.widget_id}", action_payload)
            if action.position is not None:
                current_grid = widgets[index].get("grid") or {}
                positioned = DashboardGrid.model_validate({**current_grid, **action.position.model_dump()}).model_dump(mode="json")
                widgets[index] = {**widgets[index], "grid": positioned}
            if action.to_index is not None:
                if action.to_index >= len(widgets):
                    return _failure(DashboardActionStatus.INVALID, "Target widget index is outside the dashboard", action_payload)
                widget = widgets.pop(index)
                widgets.insert(action.to_index, widget)
        elif isinstance(action, ResizeWidgetAction):
            index = _widget_index(widgets, action.widget_id)
            if index < 0:
                return _failure(DashboardActionStatus.INVALID, f"Widget not found: {action.widget_id}", action_payload)
            grid = {**(widgets[index].get("grid") or {}), "w": action.width, "h": action.height}
            validated = DashboardGrid.model_validate(grid).model_dump(mode="json")
            widgets[index] = {**widgets[index], "grid": validated}
        elif isinstance(action, ChangeVisualizationAction):
            index = _widget_index(widgets, action.widget_id)
            if index < 0:
                return _failure(DashboardActionStatus.INVALID, f"Widget not found: {action.widget_id}", action_payload)
            if action.visualization not in ALLOWED_VISUALIZATIONS or not _visualization_supported(str(widgets[index].get("widget_type")), action.visualization):
                return _failure(DashboardActionStatus.UNSUPPORTED, "That visualization is not supported for this widget", action_payload)
            widgets[index] = {**widgets[index], "visualization": action.visualization}
        elif isinstance(action, (UpdateFilterAction, UpdateDateRangeAction)):
            index = _widget_index(widgets, action.widget_id)
            if index < 0:
                return _failure(DashboardActionStatus.INVALID, f"Widget not found: {action.widget_id}", action_payload)
            binding = widgets[index].get("binding")
            if not isinstance(binding, dict):
                return _failure(DashboardActionStatus.UNSUPPORTED, "Changing data scope requires a new verified analysis", action_payload)
            if isinstance(action, UpdateFilterAction):
                binding = {**binding, "filters": [row.model_dump(mode="json") for row in action.filters]}
            else:
                binding = {**binding, "period": action.period}
            widgets[index] = {**widgets[index], "binding": DashboardDataBinding.model_validate(binding).model_dump(mode="json")}
        elif isinstance(action, ClearDashboardAction):
            widgets = []
        elif isinstance(action, RenameDashboardAction):
            next_state["name"] = action.name.strip()
        else:
            return _failure(DashboardActionStatus.UNSUPPORTED, f"Unsupported dashboard action: {action.type}", action_payload)
    except (ValueError, ValidationError) as exc:
        return _failure(DashboardActionStatus.INVALID, str(exc), action_payload)
    next_state["widgets"] = widgets
    next_state["layout_version"] = LAYOUT_VERSION
    return DashboardActionResult(status=DashboardActionStatus.SUCCESS, action=action_payload, dashboard=next_state)


def execute_dashboard_action(
    user_id: str,
    resource_type: Literal["draft", "view"],
    resource_id: str,
    action_value: dict[str, Any] | DashboardAction,
    *,
    allowed_widget_types: set[str],
) -> DashboardActionResult:
    from . import database

    try:
        if resource_type == "draft":
            resource = database.get_dashboard_job(resource_id, user_id)
            if resource.get("state") not in {"COMPLETE", "PARTIAL_SUCCESS", "FAILED", "CANCELLED", "EXPIRED"} or not resource.get("specification"):
                return _failure(DashboardActionStatus.INVALID, "Dashboard layout can be edited after widget calculation finishes")
            specification = copy.deepcopy(resource["specification"])
            state = {"name": specification.get("title"), "widgets": specification.get("widgets") or [], "layout_version": specification.get("layout_version")}
            before_widgets = copy.deepcopy(state["widgets"])
            before_name = state.get("name")
            task_ids = {str(item.get("widget_id")) for item in resource.get("widget_results") or []}
            result = apply_dashboard_action(state, action_value, allowed_widget_types=allowed_widget_types, available_task_ids=task_ids)
            if result.status != DashboardActionStatus.SUCCESS:
                return result
            assert result.dashboard is not None
            specification = {**specification, "widgets": result.dashboard["widgets"], "layout_version": LAYOUT_VERSION}
            if result.dashboard.get("name"):
                specification["title"] = result.dashboard["name"]
            action_payload = result.action or {}
            target_id = str(action_payload.get("widget_id") or ((action_payload.get("widget") or {}).get("id")) or "")
            target_task_id = next((
                str(item.get("task_id")) for item in before_widgets if str(item.get("id")) == target_id
            ), target_id)
            affected_results = [
                copy.deepcopy(item) for item in resource.get("widget_results") or []
                if target_id and str(item.get("widget_id")) == target_task_id
            ]
            history = list(specification.get("draft_action_history") or [])
            history.append({
                "action": action_payload,
                "before_name": before_name,
                "before_widgets": before_widgets,
                "affected_results": affected_results,
            })
            specification["draft_action_history"] = history[-12:]
            visible_task_ids = {str(item.get("task_id")) for item in result.dashboard["widgets"]}
            widget_results = [item for item in resource.get("widget_results") or [] if str(item.get("widget_id")) in visible_task_ids]
            updated = database.update_dashboard_job(resource_id, user_id, specification=specification, widget_results=widget_results)
            result.dashboard = updated
            return result
        if resource_type == "view":
            resource = database.get_dashboard_view(resource_id, user_id)
            state = {"name": resource.get("name"), "widgets": resource.get("layout") or [], "layout_version": resource.get("layout_version")}
            latest_results = (resource.get("latest_run") or {}).get("widget_results") or []
            task_ids = {str(item.get("widget_id")) for item in latest_results}
            result = apply_dashboard_action(state, action_value, allowed_widget_types=allowed_widget_types, available_task_ids=task_ids)
            if result.status != DashboardActionStatus.SUCCESS:
                return result
            assert result.dashboard is not None
            specification = copy.deepcopy(resource.get("specification") or {})
            specification["widgets"] = result.dashboard["widgets"]
            specification["layout_version"] = LAYOUT_VERSION
            if result.dashboard.get("name"):
                specification["title"] = result.dashboard["name"]
            updated, revision = database.persist_dashboard_action(
                resource_id, user_id,
                name=result.dashboard.get("name"),
                layout=result.dashboard["widgets"],
                specification=specification,
                revision_type=f"action_{str(result.action['type']).lower()}",
            )
            result.dashboard = updated
            result.revision = revision
            return result
        return _failure(DashboardActionStatus.UNSUPPORTED, f"Unsupported dashboard resource: {resource_type}")
    except KeyError:
        return _failure(DashboardActionStatus.INVALID, f"Dashboard {resource_type} not found: {resource_id}")
    except Exception as exc:
        return _failure(DashboardActionStatus.FAILED, str(exc))


def undo_dashboard_action(
    user_id: str,
    resource_type: Literal["draft", "view"],
    resource_id: str,
    *,
    widget_id: str | None = None,
) -> DashboardActionResult:
    """Undo through draft staging history or the saved-view revision ledger."""
    from . import database

    try:
        if resource_type == "view":
            dashboard, revision = database.restore_previous_dashboard_revision(resource_id, user_id, widget_id)
            return DashboardActionResult(
                status=DashboardActionStatus.SUCCESS,
                action={"type": "UNDO_DASHBOARD", "widget_id": widget_id},
                dashboard=dashboard,
                revision=revision,
            )
        if resource_type != "draft":
            return _failure(DashboardActionStatus.UNSUPPORTED, f"Unsupported dashboard resource: {resource_type}")
        resource = database.get_dashboard_job(resource_id, user_id)
        specification = copy.deepcopy(resource.get("specification") or {})
        history = list(specification.get("draft_action_history") or [])
        if not history:
            return _failure(DashboardActionStatus.INVALID, "There is no draft change to undo")
        history_index = len(history) - 1
        if widget_id:
            history_index = next((
                index for index in range(len(history) - 1, -1, -1)
                if widget_id == str((history[index].get("action") or {}).get("widget_id") or
                                    (((history[index].get("action") or {}).get("widget") or {}).get("id")) or "")
            ), -1)
            if history_index < 0:
                return _failure(DashboardActionStatus.INVALID, "No draft change affected that widget")
        entry = history.pop(history_index)
        specification["widgets"] = copy.deepcopy(entry.get("before_widgets") or [])
        specification["title"] = entry.get("before_name") or specification.get("title")
        specification["draft_action_history"] = history
        restored_ids = {str(item.get("task_id")) for item in specification["widgets"]}
        current_results = {
            str(item.get("widget_id")): item for item in resource.get("widget_results") or []
            if str(item.get("widget_id")) in restored_ids
        }
        for item in entry.get("affected_results") or []:
            if str(item.get("widget_id")) in restored_ids:
                current_results[str(item.get("widget_id"))] = item
        updated = database.update_dashboard_job(
            resource_id, user_id, specification=specification, widget_results=list(current_results.values()),
        )
        return DashboardActionResult(
            status=DashboardActionStatus.SUCCESS,
            action={"type": "UNDO_DASHBOARD", "widget_id": widget_id},
            dashboard=updated,
        )
    except KeyError:
        return _failure(DashboardActionStatus.INVALID, f"Dashboard {resource_type} not found: {resource_id}")
    except ValueError as exc:
        return _failure(DashboardActionStatus.INVALID, str(exc))
    except Exception as exc:
        return _failure(DashboardActionStatus.FAILED, str(exc))
