from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import attention, database, decision_journal, theses
from backend.models import InvestmentDecisionPayload, InvestmentThesisPayload


USER_A = "00000000-0000-4000-8000-00000000000a"
USER_B = "00000000-0000-4000-8000-00000000000b"
NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)


def _thesis() -> InvestmentThesisPayload:
    return InvestmentThesisPayload.model_validate({
        "ticker": "MSFT", "summary": "Cloud demand supports durable growth.", "status": "ACTIVE",
        "horizon_end_date": "2027-08-16",
        "assumptions": [{"description": "Revenue growth remains above 15%", "category": "GROWTH",
                         "importance": "HIGH", "metric": "revenue_growth", "operator": ">=", "target_value": .15}],
        "factors": [
            {"factor_type": "RISK", "description": "Enterprise demand weakens"},
            {"factor_type": "CATALYST", "description": "AI revenue accelerates"},
            {"factor_type": "BREAKER", "description": "Cloud growth falls below the saved floor"},
        ],
    })


def _record(monkeypatch, *, decision_date: datetime = NOW - timedelta(days=100)) -> tuple[dict, dict]:
    monkeypatch.setattr(decision_journal, "_forecast_snapshot", lambda *args: [{"title": "AI adoption", "probability": .7}])
    monkeypatch.setattr(decision_journal, "_market_snapshot", lambda *args: [{"title": "Rates", "probability": .4}])
    monkeypatch.setattr(decision_journal, "_portfolio_context", lambda *args: {"status": "AVAILABLE", "normalized_weight": .18})
    thesis = theses.create_thesis(USER_A, _thesis())
    decision = theses.record_decision(USER_A, InvestmentDecisionPayload(
        ticker="MSFT", thesis_id=thesis["id"], decision_type="BUY", decision_date=decision_date,
        user_confidence=4, expected_outcome="Revenue growth remains above 15%.", review_horizon_days=90,
        comparison_benchmark="SPY", notes="Evidence supported the saved base case.",
    ))
    return thesis, decision


def test_decision_snapshot_is_immutable_complete_and_owner_scoped(monkeypatch) -> None:
    thesis, decision = _record(monkeypatch)
    original = decision_journal.get_snapshot(USER_A, decision["id"])["snapshot"]
    assert original["thesis"]["summary"] == "Cloud demand supports durable growth."
    assert original["expected_outcome"].startswith("Revenue growth")
    assert original["portfolio"]["normalized_weight"] == .18
    assert original["forecasts"][0]["probability"] == .7
    assert original["prediction_markets"][0]["probability"] == .4
    assert original["review_horizon_days"] == 90
    revised = _thesis(); revised.summary = "A later thesis edit that must not rewrite history."
    theses.update_thesis(USER_A, thesis["id"], revised)
    assert decision_journal.get_snapshot(USER_A, decision["id"])["snapshot"] == original
    with pytest.raises(KeyError):
        decision_journal.get_snapshot(USER_B, decision["id"])


def test_assumption_risk_catalyst_and_breaker_outcomes_are_structured() -> None:
    snapshot = {"thesis": {"assumptions": [{"description": "Revenue growth remains above 15%", "category": "GROWTH",
        "importance": "HIGH", "metric": "revenue_growth", "operator": ">=", "target_value": .15}],
        "factors": [{"factor_type": "RISK", "description": "Enterprise demand weakens"},
                    {"factor_type": "CATALYST", "description": "AI revenue accelerates"},
                    {"factor_type": "BREAKER", "description": "Cloud growth falls below the saved floor"}]}}
    reviews = [{"reviewed_at": NOW.isoformat(), "monitoring_result": {
        "risk_results": [{"description": "Enterprise demand weakens", "state": "MATERIALIZED", "evidence": ["r"]}],
        "catalyst_results": [{"description": "AI revenue accelerates", "state": "DEVELOPING", "evidence": ["c"]}],
        "thesis_breaker_results": [{"description": "Cloud growth falls below the saved floor", "state": "WARNING", "evidence": ["b"]}],
    }}]
    result = decision_journal._outcomes(snapshot, [{"metric": "revenue_growth", "current_value": .12}], reviews, NOW)
    assert result["assumptions"][0]["status"] == "INVALIDATED"
    assert result["risks"][0]["status"] == "MATERIALIZED"
    assert result["catalysts"][0]["status"] == "PARTIALLY_REALIZED"
    assert result["breakers"][0]["status"] == "WARNING"


def test_market_outcome_keeps_benchmark_and_process_methodology_separate(monkeypatch) -> None:
    monkeypatch.setattr(database, "security_data", lambda *args, **kwargs: {"prices": [
        {"ticker": "MSFT", "date": "2026-01-01", "close": 100}, {"ticker": "MSFT", "date": "2026-04-01", "close": 120},
        {"ticker": "SPY", "date": "2026-01-01", "close": 200}, {"ticker": "SPY", "date": "2026-04-01", "close": 210},
    ]})
    result = decision_journal._price_outcome("MSFT", "SPY", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 4, 1, tzinfo=timezone.utc))
    assert result["security_return"] == pytest.approx(.20)
    assert result["benchmark_return"] == pytest.approx(.05)
    assert result["relative_return"] == pytest.approx(.15)
    assert "not realized account P&L" in result["methodology"]


def test_missing_market_data_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(database, "security_data", lambda *args, **kwargs: {"prices": []})
    result = decision_journal._price_outcome("MSFT", "SPY", NOW - timedelta(days=30), NOW)
    assert result["status"] == "UNAVAILABLE"
    assert result["security_return"] is None and result["relative_return"] is None


def test_retrospectives_are_append_only_across_horizons(monkeypatch) -> None:
    _, decision = _record(monkeypatch)
    base = {"horizon": {"key": "30D", "start": "2026-01-01T00:00:00+00:00", "end": "2026-01-31T00:00:00+00:00"}, "thesis_outcomes": {"assumptions": []}}
    first = decision_journal.save_retrospective(USER_A, decision["id"], base, "First review")
    second_result = {**base, "horizon": {**base["horizon"], "key": "90D", "end": "2026-04-01T00:00:00+00:00"}}
    second = decision_journal.save_retrospective(USER_A, decision["id"], second_result, "Later review")
    rows = decision_journal.get_retrospectives(USER_A, decision["id"])
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert {row["user_notes"] for row in rows} == {"First review", "Later review"}
    assert decision_journal.get_retrospectives(USER_B, decision["id"]) == []


def test_pattern_detection_uses_unique_decisions_and_minimum_sample(monkeypatch) -> None:
    rows = [{"decision_id": f"d-{index}", "window_start": "2026-01-01", "window_end": "2026-04-01",
             "structured_result": {"thesis_outcomes": {"assumptions": [{"category": "GROWTH", "status": "INVALIDATED"}]}}}
            for index in range(4)]
    monkeypatch.setattr(decision_journal, "get_retrospectives", lambda user_id: rows)
    assert decision_journal.patterns(USER_A)["status"] == "INSUFFICIENT_SAMPLE"
    rows.append({**rows[-1], "decision_id": "d-5"})
    result = decision_journal.patterns(USER_A)
    assert result["status"] == "ESTABLISHED"
    assert result["patterns"][0]["established"] is True
    assert result["patterns"][0]["sample_size"] == 5


def test_forecast_calibration_is_deterministic_and_sample_guarded(monkeypatch) -> None:
    rows = [{"probability": .8, "resolved_outcome": 1.0}, {"probability": .7, "resolved_outcome": 0.0}]
    monkeypatch.setattr(database, "list_user_forecasts", lambda user_id: rows)
    small = decision_journal.forecast_calibration(USER_A)
    assert small["brier_score"] == pytest.approx((.04 + .49) / 2)
    assert small["status"] == "INSUFFICIENT_SAMPLE"
    monkeypatch.setattr(database, "list_user_forecasts", lambda user_id: rows * 5)
    assert decision_journal.forecast_calibration(USER_A)["status"] == "ESTABLISHED"


def test_due_decision_review_is_a_today_item() -> None:
    decision = {"id": "decision-1", "ticker": "MSFT", "decision_type": "HOLD", "decision_date": "2026-04-01T00:00:00+00:00",
                "thesis_id": "thesis-1", "created_at": "2026-04-01T00:00:00+00:00"}
    result = attention.compose_attention(holdings=[{"ticker": "MSFT", "weight": 1}], thesis_workspace={"active_theses": []},
        monitoring_results=[], forecasting_payload={"markets": [], "warnings": []}, events=[], diagnostics={}, research=[], watchlist=[],
        movements=[], states={}, decision_reviews=[{"decision": decision, "due_at": "2026-07-01T00:00:00+00:00", "horizon_days": 90}], now=NOW)
    item = result["items"][0]
    assert item["type"] == "UPCOMING_REVIEW"
    assert item["linked_decision_id"] == "decision-1"
    assert item["action_target"] == "/decisions?journal=decision-1"
