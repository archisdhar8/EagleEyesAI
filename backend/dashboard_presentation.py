from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import database
from .analytical_contract import AnalysisResult, AnalysisStatus, stable_fingerprint


DASHBOARD_PLAN_VERSION = "dashboard-plan-v1"
DASHBOARD_WIDGET_PLAN_VERSION = "dashboard-widget-plan-v1"
DASHBOARD_SPEC_VERSION = "dashboard-spec-v3"
DASHBOARD_LAYOUT_VERSION = "dashboard-layout-v2"
DASHBOARD_COMPILER_VERSION = "verified-result-dashboard-compiler-v1"


class DashboardWidgetState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REFRESHING = "REFRESHING"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    PENDING = "PENDING"


class VisualizationType(StrEnum):
    METRIC = "metric"
    CARDS = "cards"
    BAR = "bar_chart"
    LINE = "line_chart"
    HEATMAP = "heatmap"
    TABLE = "table"
    TIMELINE = "timeline"
    HISTOGRAM = "histogram"


class DashboardFieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_path: str = Field(min_length=1, max_length=160)
    shape: Literal["scalar", "category", "time_series", "matrix", "records", "distribution"]
    label_field: str | None = Field(default=None, max_length=80)
    value_field: str | None = Field(default=None, max_length=80)
    time_field: str | None = Field(default=None, max_length=80)


class DashboardWidgetLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0, le=10_000)
    w: Literal[4, 6, 8, 12] = 6
    h: int = Field(default=2, ge=2, le=6)

    @model_validator(mode="after")
    def fits_grid(self) -> "DashboardWidgetLayout":
        if self.x + self.w > 12:
            raise ValueError("Widget exceeds the 12-column dashboard grid")
        return self


class DashboardWidgetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = DASHBOARD_WIDGET_PLAN_VERSION
    widget_id: str = Field(pattern=r"^widget_[a-f0-9]{16}$")
    purpose: str = Field(min_length=2, max_length=240)
    source_result_id: str = Field(pattern=r"^(?:result|composed)_[a-f0-9]{16,20}$")
    source_capability: str = Field(min_length=2, max_length=100)
    source_category: Literal["VERIFIED", "MODEL_OUTPUT", "MARKET_IMPLIED", "USER_THESIS"]
    visualization_type: VisualizationType
    field_mapping: DashboardFieldMapping
    title: str = Field(min_length=1, max_length=160)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    date_range: str | None = Field(default=None, max_length=30)
    layout: DashboardWidgetLayout
    state: DashboardWidgetState
    job_reference: dict[str, Any] | None = None


class DashboardPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = DASHBOARD_PLAN_VERSION
    goal: str = Field(min_length=2, max_length=500)
    title: str = Field(min_length=1, max_length=120)
    source_result_ids: list[str] = Field(min_length=1, max_length=8)
    widgets: list[DashboardWidgetPlan] = Field(min_length=1, max_length=8)
    layout: Literal["responsive_12_column"] = "responsive_12_column"

    @model_validator(mode="after")
    def validate_references(self) -> "DashboardPlan":
        sources = set(self.source_result_ids)
        if any(widget.source_result_id not in sources for widget in self.widgets):
            raise ValueError("Every widget must reference a declared verified result")
        if len({widget.widget_id for widget in self.widgets}) != len(self.widgets):
            raise ValueError("Widget IDs must be stable and unique")
        return self


class WidgetTemplate(BaseModel):
    title: str
    purpose: str
    path: str
    shape: Literal["scalar", "category", "time_series", "matrix", "records", "distribution"]
    visualization: VisualizationType
    label_field: str | None = None
    value_field: str | None = None
    time_field: str | None = None


_MAPPING: dict[str, tuple[WidgetTemplate, ...]] = {
    "portfolio_risk": (
        WidgetTemplate(title="Sector Exposure", purpose="Show verified sector concentration", path="sector_exposure", shape="category", visualization=VisualizationType.BAR, label_field="sector", value_field="weight"),
        WidgetTemplate(title="Largest Risk Contributors", purpose="Show verified holding risk contribution", path="risk_contribution", shape="category", visualization=VisualizationType.BAR, label_field="ticker", value_field="risk_contribution"),
        WidgetTemplate(title="Concentration", purpose="Summarize verified portfolio concentration", path="concentration", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Correlation Clusters", purpose="Show the verified correlation structure", path="correlation", shape="matrix", visualization=VisualizationType.HEATMAP),
        WidgetTemplate(title="Theme Exposure", purpose="Show verified thematic exposure", path="theme_exposure", shape="category", visualization=VisualizationType.BAR, label_field="theme", value_field="weight"),
    ),
    "company_analysis": (
        WidgetTemplate(title="Fundamentals", purpose="Present verified company fundamentals", path="fundamentals", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Valuation", purpose="Present verified valuation evidence", path="valuation", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Profitability", purpose="Present verified profitability evidence", path="profitability", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Momentum", purpose="Present verified price momentum", path="momentum", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Earnings State", purpose="Present verified earnings evidence", path="earnings_state", shape="records", visualization=VisualizationType.TABLE),
        WidgetTemplate(title="EagleEyes Score", purpose="Present the existing verified score", path="eagleeyes_score", shape="scalar", visualization=VisualizationType.METRIC),
    ),
    "company_comparison": (
        WidgetTemplate(title="Valuation Comparison", purpose="Compare verified valuation fields", path="valuation_comparison", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Growth Comparison", purpose="Compare verified growth fields", path="growth_comparison", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Profitability Comparison", purpose="Compare verified profitability fields", path="profitability_comparison", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Company Evidence", purpose="Show the verified company comparison rows", path="companies", shape="records", visualization=VisualizationType.TABLE),
    ),
    "macro_state": (
        WidgetTemplate(title="Macro Factor States", purpose="Present observed macro factor states", path="factor_states", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Macro Regime", purpose="Present the observed macro regime", path="regime", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Macro Changes", purpose="Show verified historical factor changes", path="changes", shape="records", visualization=VisualizationType.TABLE),
        WidgetTemplate(title="Portfolio Macro Exposure", purpose="Show mapped portfolio exposure without causal inference", path="portfolio_exposures", shape="records", visualization=VisualizationType.TABLE),
    ),
    "market_state": (
        WidgetTemplate(title="Sector Leadership", purpose="Show verified sector leadership", path="sector_leadership", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Market Trend", purpose="Present the verified broad-market trend", path="broad_market_trend", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Volatility", purpose="Present verified volatility state", path="volatility_state", shape="records", visualization=VisualizationType.CARDS),
        WidgetTemplate(title="Breadth", purpose="Present supported market breadth evidence", path="breadth", shape="records", visualization=VisualizationType.CARDS),
    ),
    "prediction_markets": (
        WidgetTemplate(title="Prediction-Market Odds", purpose="Show current market-implied probabilities", path="markets", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Probability Changes", purpose="Show verified changes in market-implied odds", path="changes", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Portfolio-Relevant Events", purpose="Show event relevance and mapped exposure", path="markets", shape="records", visualization=VisualizationType.TABLE),
    ),
    "portfolio_scenario": (
        WidgetTemplate(title="Scenario Outcomes", purpose="Show the existing scenario output", path="outcomes", shape="records", visualization=VisualizationType.TABLE),
        WidgetTemplate(title="Affected Holdings", purpose="Show holdings affected in the verified scenario", path="affected_holdings", shape="category", visualization=VisualizationType.BAR),
        WidgetTemplate(title="Factor Support", purpose="Show supported and unsupported scenario factors", path="factor_support", shape="records", visualization=VisualizationType.TABLE),
    ),
    "portfolio_backtest": (
        WidgetTemplate(title="Portfolio vs Benchmark", purpose="Show canonical historical paths", path="series", shape="time_series", visualization=VisualizationType.LINE, time_field="date", value_field="value"),
        WidgetTemplate(title="Drawdown", purpose="Show canonical drawdown history", path="drawdown", shape="time_series", visualization=VisualizationType.LINE, time_field="date", value_field="value"),
        WidgetTemplate(title="Backtest Metrics", purpose="Present canonical backtest metrics", path="metrics", shape="records", visualization=VisualizationType.CARDS),
    ),
}

_ALIASES = {
    "prediction_market_intelligence": "prediction_markets",
    "prediction_market_state": "prediction_markets",
    "scenario_analysis": "portfolio_scenario",
    "backtest": "portfolio_backtest",
    "company_research": "company_analysis",
}

_VISUALS_BY_SHAPE = {
    "scalar": {VisualizationType.METRIC, VisualizationType.CARDS},
    "category": {VisualizationType.BAR, VisualizationType.TABLE},
    "time_series": {VisualizationType.LINE, VisualizationType.TABLE},
    "matrix": {VisualizationType.HEATMAP, VisualizationType.TABLE},
    "records": {VisualizationType.TABLE, VisualizationType.CARDS},
    "distribution": {VisualizationType.HISTOGRAM, VisualizationType.TABLE},
}


def stable_result_id(result: AnalysisResult) -> str:
    return f"result_{stable_fingerprint({'capability': result.capability, 'fingerprint': result.input_fingerprint})[:16]}"


def _value_at(data: Any, path: str) -> Any:
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _source_category(capability: str) -> Literal["VERIFIED", "MODEL_OUTPUT", "MARKET_IMPLIED", "USER_THESIS"]:
    value = capability.lower()
    if "prediction" in value:
        return "MARKET_IMPLIED"
    if "thesis" in value or "decision_journal" in value:
        return "USER_THESIS"
    if any(term in value for term in ("risk", "scenario", "score", "ranking", "backtest", "intelligence")):
        return "MODEL_OUTPUT"
    return "VERIFIED"


def _state(result: AnalysisResult) -> DashboardWidgetState:
    if result.status == AnalysisStatus.PENDING:
        return DashboardWidgetState.PENDING
    if result.status == AnalysisStatus.PARTIAL:
        return DashboardWidgetState.PARTIAL
    if result.status == AnalysisStatus.UNAVAILABLE:
        return DashboardWidgetState.UNAVAILABLE
    if result.status == AnalysisStatus.FAILED:
        return DashboardWidgetState.FAILED
    if result.freshness.stale:
        return DashboardWidgetState.STALE
    return DashboardWidgetState.CURRENT


def _templates(result: AnalysisResult) -> list[WidgetTemplate]:
    capability = _ALIASES.get(result.capability, result.capability)
    supported = list(_MAPPING.get(capability, ()))
    present = [template for template in supported if _value_at(result.data, template.path) is not None]
    if present:
        return present
    return [WidgetTemplate(
        title=result.capability.replace("_", " ").title(),
        purpose="Present the canonical capability result without deriving new values",
        path="$", shape="records", visualization=VisualizationType.TABLE,
    )]


def _title(question: str, results: list[AnalysisResult]) -> str:
    lower = question.lower()
    if "ai exposure" in lower:
        return "AI Exposure Monitor"
    if "risk" in lower:
        return "Portfolio Risk"
    if "macro" in lower and "prediction" in lower:
        return "Macro & Prediction Risks"
    if len(results) == 1:
        return _ALIASES.get(results[0].capability, results[0].capability).replace("_", " ").title()
    return "EagleEyes Analysis"


def build_dashboard_plan(question: str, results: list[AnalysisResult], *, single_widget: bool = False) -> DashboardPlan:
    if not results:
        raise ValueError("Dashboard planning requires at least one canonical analytical result")
    widgets: list[DashboardWidgetPlan] = []
    result_ids = [stable_result_id(result) for result in results]
    candidates: list[tuple[AnalysisResult, WidgetTemplate]] = [
        (result, template) for result in results for template in _templates(result)
    ]
    if single_widget:
        terms = set(re.findall(r"[a-z]+", question.lower()))
        candidates.sort(key=lambda item: -len(terms & set(re.findall(r"[a-z]+", f"{item[1].title} {item[1].purpose}".lower()))))
        candidates = candidates[:1]
    else:
        candidates = candidates[:8]
    for index, (result, template) in enumerate(candidates):
        if template.visualization not in _VISUALS_BY_SHAPE[template.shape]:
            raise ValueError(f"Unsupported visualization {template.visualization} for {template.shape}")
        source_id = stable_result_id(result)
        widget_id = f"widget_{stable_fingerprint({'capability': result.capability, 'path': template.path, 'title': template.title})[:16]}"
        width = 12 if template.visualization in {VisualizationType.LINE, VisualizationType.HEATMAP} else 6
        x = 0 if width == 12 or index % 2 == 0 else 6
        y = sum(1 for prior in widgets if prior.layout.x == x) * 2
        widgets.append(DashboardWidgetPlan(
            widget_id=widget_id, purpose=template.purpose, source_result_id=source_id,
            source_capability=result.capability, source_category=_source_category(result.capability),
            visualization_type=template.visualization,
            field_mapping=DashboardFieldMapping(
                data_path=template.path, shape=template.shape, label_field=template.label_field,
                value_field=template.value_field, time_field=template.time_field,
            ),
            title=template.title, layout=DashboardWidgetLayout(x=x, y=y, w=width, h=2),
            state=_state(result), job_reference=result.job.model_dump(mode="json") if result.job else None,
        ))
    return DashboardPlan(goal=question, title=_title(question, results), source_result_ids=result_ids, widgets=widgets)


def _widget_result(widget: DashboardWidgetPlan, result: AnalysisResult) -> dict[str, Any]:
    data = result.data if widget.field_mapping.data_path == "$" else _value_at(result.data, widget.field_mapping.data_path)
    ui_status = {
        DashboardWidgetState.CURRENT: "READY", DashboardWidgetState.STALE: "STALE",
        DashboardWidgetState.REFRESHING: "LOADING", DashboardWidgetState.PARTIAL: "PARTIAL",
        DashboardWidgetState.UNAVAILABLE: "UNAVAILABLE", DashboardWidgetState.FAILED: "FAILED",
        DashboardWidgetState.PENDING: "PENDING",
    }[widget.state]
    return {
        "widget_id": widget.widget_id, "status": ui_status,
        "source_result_id": widget.source_result_id, "source_capability": widget.source_capability,
        "source_category": widget.source_category, "state": widget.state,
        "data": data, "as_of": (result.freshness.effective_through or result.freshness.calculated_at).isoformat(),
        "lineage": [{"provider": row.provider or row.domain, "dataset": row.dataset,
                     "retrieved_at": result.freshness.calculated_at.isoformat(),
                     "effective_through": row.effective_at.isoformat() if row.effective_at else None,
                     "symbols": result.coverage.evaluated_entities, "cache_status": "canonical_result",
                     "dataset_version": row.source_version} for row in result.lineage],
        "calculation": {"method": result.capability, "version": result.calculation_version,
                        "parameters": {"source_result_id": widget.source_result_id}},
        "presentation": {"chart": widget.visualization_type, "x_axis": widget.field_mapping.label_field or widget.field_mapping.time_field or "Category",
                         "y_axis": widget.field_mapping.value_field or "Verified value", "unit": "See canonical result",
                         "frequency": "Canonical result", "timeframe": "Latest verified"},
        "quality": {"data_quality": "high" if result.verification.passed else "limited",
                    "reasons": [check.message for check in result.verification.checks]},
        "assumptions": [row.reason for row in result.prerequisites],
        "warnings": [*result.warnings, *result.limitations],
        "how_calculated": f"Rendered from {widget.source_result_id}; the dashboard performed no financial calculation.",
        "job_reference": widget.job_reference,
    }


def materialize_verified_dashboard(
    user_id: str, conversation_id: str, portfolio_id: str | None, question: str,
    results: list[AnalysisResult], *, single_widget: bool = False,
    resource_type: Literal["draft", "view"] | None = None, resource_id: str | None = None,
) -> tuple[DashboardPlan, dict[str, Any]]:
    plan = build_dashboard_plan(question, results, single_widget=single_widget)
    by_id = {stable_result_id(result): result for result in results}
    spec_widgets = [{
        "id": widget.widget_id, "task_id": widget.widget_id, "widget_type": "canonical_result",
        "title": widget.title, "visualization": widget.visualization_type,
        "grid": widget.layout.model_dump(mode="json"),
        "source_result_id": widget.source_result_id, "source_capability": widget.source_capability,
        "source_category": widget.source_category, "field_mapping": widget.field_mapping.model_dump(mode="json"),
        "state": widget.state, "job_reference": widget.job_reference,
        "binding": None,
    } for widget in plan.widgets]
    results_payload = [_widget_result(widget, by_id[widget.source_result_id]) for widget in plan.widgets]
    usable = [row for row in results_payload if row["status"] not in {"FAILED", "UNAVAILABLE"}]
    state = "COMPLETE" if len(usable) == len(results_payload) else "PARTIAL_SUCCESS" if usable else "FAILED"
    specification: dict[str, Any] = {
        "version": DASHBOARD_SPEC_VERSION, "spec_version": DASHBOARD_SPEC_VERSION,
        "layout_version": DASHBOARD_LAYOUT_VERSION, "title": plan.title,
        "description": plan.goal, "compiler_version": DASHBOARD_COMPILER_VERSION,
        "source_result_ids": plan.source_result_ids, "dashboard_plan": plan.model_dump(mode="json"),
        "widgets": spec_widgets,
    }
    prior_results: list[dict[str, Any]] = []
    source_view_id: str | None = None
    if resource_type == "draft" and resource_id:
        prior = database.get_dashboard_job(resource_id, user_id)
        prior_spec = prior.get("specification") or {}
        prior_widgets = list(prior_spec.get("widgets") or [])
        incoming = {str(widget["id"]): widget for widget in spec_widgets}
        spec_widgets = [
            {**widget, **incoming.pop(str(widget.get("id")), {}), "grid": widget.get("grid")}
            for widget in prior_widgets
        ] + list(incoming.values())
        prior_results = list(prior.get("widget_results") or [])
        prior_sources = list(prior_spec.get("source_result_ids") or [])
        specification = {**prior_spec, **specification, "widgets": spec_widgets,
                         "source_result_ids": list(dict.fromkeys([*prior_sources, *plan.source_result_ids]))}
        draft = prior
    elif resource_type == "view" and resource_id:
        prior_view = database.get_dashboard_view(resource_id, user_id)
        prior_spec = prior_view.get("specification") or {}
        prior_widgets = list(prior_view.get("layout") or prior_spec.get("widgets") or [])
        incoming = {str(widget["id"]): widget for widget in spec_widgets}
        spec_widgets = [
            {**widget, **incoming.pop(str(widget.get("id")), {}), "grid": widget.get("grid")}
            for widget in prior_widgets
        ] + list(incoming.values())
        prior_results = list((prior_view.get("latest_run") or {}).get("widget_results") or [])
        prior_sources = list(prior_spec.get("source_result_ids") or [])
        specification = {**prior_spec, **specification, "widgets": spec_widgets,
                         "source_result_ids": list(dict.fromkeys([*prior_sources, *plan.source_result_ids]))}
        source_view_id = resource_id
        draft = database.create_dashboard_job(user_id, question, portfolio_id, source_view_id=source_view_id, conversation_id=conversation_id)
    else:
        draft = database.create_dashboard_job(user_id, question, portfolio_id, conversation_id=conversation_id)
    result_map = {str(row.get("widget_id")): row for row in prior_results}
    result_map.update({str(row.get("widget_id")): row for row in results_payload})
    results_payload = list(result_map.values())
    usable = [row for row in results_payload if row["status"] not in {"FAILED", "UNAVAILABLE"}]
    state = "COMPLETE" if len(usable) == len(results_payload) else "PARTIAL_SUCCESS" if usable else "FAILED"
    draft = database.update_dashboard_job(
        draft["id"], user_id, state=state, progress=100,
        plan=plan.model_dump(mode="json"), specification=specification,
        widget_results=results_payload,
        warnings=[warning for result in results for warning in [*result.warnings, *result.limitations]],
        narrative=f"This view presents {len(results_payload)} verified analytical result widget{'s' if len(results_payload) != 1 else ''}.",
    )
    return plan, draft
