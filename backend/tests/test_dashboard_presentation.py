from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend import database
from backend.analytical_contract import (
    AnalysisResult, AnalysisStatus, Coverage, Freshness, JobReference, LineageItem,
    VerificationResult,
)
from backend.dashboard_presentation import (
    DashboardWidgetState, build_dashboard_plan, materialize_verified_dashboard,
    stable_result_id,
)


def result(
    capability: str, data: object, *, status: AnalysisStatus = AnalysisStatus.SUCCESS,
    stale: bool = False, fingerprint: str = "fixture-v1",
) -> AnalysisResult:
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    return AnalysisResult(
        capability=capability, calculation_version=f"{capability}-v1",
        input_fingerprint=fingerprint, status=status, data=data,
        coverage=Coverage(requested_entities=["AAPL"], evaluated_entities=["AAPL"]),
        freshness=Freshness(calculated_at=now, effective_through=now, stale=stale),
        lineage=[LineageItem(domain="portfolio", dataset="verified_fixture", provider="EagleEyes")],
        verification=VerificationResult(passed=True, answer_allowed=True, recommendation_allowed=False),
        job=JobReference(id="job-backtest", kind="BACKTEST") if status == AnalysisStatus.PENDING else None,
    )


def test_every_widget_references_a_canonical_result_and_only_present_fields() -> None:
    canonical = result("portfolio_risk", {
        "sector_exposure": [{"sector": "Technology", "weight": .42}],
        "concentration": {"largest_weight": .21},
    })
    plan = build_dashboard_plan("Build me a risk dashboard", [canonical])
    assert plan.source_result_ids == [stable_result_id(canonical)]
    assert {widget.field_mapping.data_path for widget in plan.widgets} == {"sector_exposure", "concentration"}
    assert all(widget.source_result_id == plan.source_result_ids[0] for widget in plan.widgets)
    assert all(widget.source_capability == "portfolio_risk" for widget in plan.widgets)


def test_widget_ids_are_stable_across_rerenders_and_layout_rebuilds() -> None:
    canonical = result("company_analysis", {"fundamentals": {"revenue": 10}, "valuation": {"pe": 21}})
    first = build_dashboard_plan("Build an MSFT research dashboard", [canonical])
    second = build_dashboard_plan("Build an MSFT research dashboard", [canonical])
    assert [row.widget_id for row in first.widgets] == [row.widget_id for row in second.widgets]
    assert all(row.widget_id.startswith("widget_") for row in first.widgets)


def test_widget_ids_are_stable_when_the_canonical_result_is_refreshed() -> None:
    first = build_dashboard_plan("Show company fundamentals", [result("company_analysis", {"fundamentals": {"revenue": 10}}, fingerprint="before")])
    refreshed = build_dashboard_plan("Show company fundamentals", [result("company_analysis", {"fundamentals": {"revenue": 12}}, fingerprint="after")])
    assert first.widgets[0].widget_id == refreshed.widgets[0].widget_id
    assert first.widgets[0].source_result_id != refreshed.widgets[0].source_result_id


def test_single_widget_visualize_uses_best_supported_existing_field() -> None:
    canonical = result("portfolio_risk", {
        "sector_exposure": [{"sector": "Technology", "weight": .42}],
        "risk_contribution": [{"ticker": "MSFT", "risk_contribution": .18}],
    })
    plan = build_dashboard_plan("Visualize sector exposure", [canonical], single_widget=True)
    assert len(plan.widgets) == 1
    assert plan.widgets[0].field_mapping.data_path == "sector_exposure"


@pytest.mark.parametrize(
    "capability,category",
    [("macro_state", "VERIFIED"), ("portfolio_risk", "MODEL_OUTPUT"),
     ("prediction_markets", "MARKET_IMPLIED"), ("thesis_monitor", "USER_THESIS")],
)
def test_source_classification_is_preserved(capability: str, category: str) -> None:
    plan = build_dashboard_plan("Show this", [result(capability, {"value": 1})], single_widget=True)
    assert plan.widgets[0].source_category == category


@pytest.mark.parametrize(
    "status,stale,expected",
    [
        (AnalysisStatus.SUCCESS, False, DashboardWidgetState.CURRENT),
        (AnalysisStatus.SUCCESS, True, DashboardWidgetState.STALE),
        (AnalysisStatus.PARTIAL, False, DashboardWidgetState.PARTIAL),
        (AnalysisStatus.PENDING, False, DashboardWidgetState.PENDING),
        (AnalysisStatus.UNAVAILABLE, False, DashboardWidgetState.UNAVAILABLE),
        (AnalysisStatus.FAILED, False, DashboardWidgetState.FAILED),
    ],
)
def test_widget_state_tracks_canonical_status(status: AnalysisStatus, stale: bool, expected: DashboardWidgetState) -> None:
    plan = build_dashboard_plan("Show this", [result("portfolio_backtest", {"metrics": {}}, status=status, stale=stale)], single_widget=True)
    assert plan.widgets[0].state == expected


def test_pending_heavy_job_keeps_reference_and_does_not_invent_values() -> None:
    canonical = result("portfolio_backtest", {}, status=AnalysisStatus.PENDING)
    plan = build_dashboard_plan("Add a five-year backtest against SPY", [canonical], single_widget=True)
    assert plan.widgets[0].state == DashboardWidgetState.PENDING
    assert plan.widgets[0].job_reference is not None
    assert {key: plan.widgets[0].job_reference[key] for key in ("id", "status", "kind")} == {"id": "job-backtest", "status": "PENDING", "kind": "BACKTEST"}


def test_partial_dashboard_materializes_usable_widgets_and_unavailable_slot() -> None:
    user = "00000000-0000-0000-0000-000000000001"
    good = result("macro_state", {"regime": {"label": "late cycle"}}, fingerprint="macro")
    missing = result("prediction_markets", {}, status=AnalysisStatus.UNAVAILABLE, fingerprint="predictions")
    plan, draft = materialize_verified_dashboard(user, "conversation-phase8", None, "Build macro risks", [good, missing])
    assert draft["state"] == "PARTIAL_SUCCESS"
    assert len(draft["widget_results"]) == len(plan.widgets)
    assert {row["status"] for row in draft["widget_results"]} == {"READY", "UNAVAILABLE"}


def test_add_widget_merges_into_existing_draft_without_changing_existing_widget_id() -> None:
    user = "00000000-0000-0000-0000-000000000001"
    first, draft = materialize_verified_dashboard(
        user, "conversation-phase8-merge", None, "Visualize concentration",
        [result("portfolio_risk", {"concentration": {"largest_weight": .2}}, fingerprint="risk")],
        single_widget=True,
    )
    existing = first.widgets[0].widget_id
    second, merged = materialize_verified_dashboard(
        user, "conversation-phase8-merge", None, "Add the current market regime",
        [result("market_state", {"broad_market_trend": {"state": "up"}}, fingerprint="market")],
        single_widget=True, resource_type="draft", resource_id=draft["id"],
    )
    assert merged["id"] == draft["id"]
    ids = [row["id"] for row in merged["specification"]["widgets"]]
    assert existing in ids and second.widgets[0].widget_id in ids
    assert len(ids) == 2


def test_materialized_data_is_exact_subtree_of_canonical_result() -> None:
    user = "00000000-0000-0000-0000-000000000001"
    sector_rows = [{"sector": "Technology", "weight": .42}]
    _, draft = materialize_verified_dashboard(
        user, "conversation-phase8-values", None, "Show sector exposure",
        [result("portfolio_risk", {"sector_exposure": sector_rows})], single_widget=True,
    )
    assert draft["widget_results"][0]["data"] == sector_rows
    assert "expected_return" not in str(draft["widget_results"][0]["data"])


def test_saved_view_retains_result_references_and_stable_widget_ids() -> None:
    user = "00000000-0000-0000-0000-000000000001"
    plan, draft = materialize_verified_dashboard(
        user, "conversation-phase8-save", None, "Show sector exposure",
        [result("portfolio_risk", {"sector_exposure": [{"sector": "Tech", "weight": .5}]})],
        single_widget=True,
    )
    saved = database.save_dashboard_view(user, draft["id"], "Portfolio Risk")
    assert saved["layout"][0]["id"] == plan.widgets[0].widget_id
    assert saved["layout"][0]["source_result_id"] == plan.widgets[0].source_result_id
    assert saved["conversation_id"] == "conversation-phase8-save"
