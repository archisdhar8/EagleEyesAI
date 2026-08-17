from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import database, forecasting
from backend.main import _forecasting_chat_tools, app


NOW = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)


def test_probability_change_uses_points_and_quality_adjusts_attention() -> None:
    history = [{"probability": .42, "observed_at": (NOW - timedelta(days=1)).isoformat()}]
    high = forecasting.probability_change(history, .67, NOW, "HIGH")
    low = forecasting.probability_change(history, .67, NOW, "LOW")
    assert high["percentage_point_change"] == 25
    assert high["relative_percent_change"] == 59.52
    assert high["quality_adjusted_attention"] == "HIGH"
    assert low["quality_adjusted_attention"] == "MEDIUM"


def test_market_quality_distinguishes_high_stale_and_missing() -> None:
    high = forecasting.assess_market_quality(observed_at=NOW - timedelta(hours=1), volume=50_000,
        bid=.62, ask=.65, resolution_criteria="Official Federal Reserve decision", provider="Kalshi", now=NOW)
    stale = forecasting.assess_market_quality(observed_at=NOW - timedelta(days=5), volume=100,
        bid=.50, ask=.75, resolution_criteria=None, provider="Polymarket", now=NOW)
    missing = forecasting.assess_market_quality(observed_at=None, provider="Unknown", now=NOW)
    assert high.level == "HIGH"
    assert stale.level == "LOW" and stale.stale is True
    assert missing.level == "INSUFFICIENT_DATA"


def test_event_mapping_is_reusable_and_explains_company_exposure() -> None:
    category, factors = forecasting.classify_market("US adds advanced-chip export restrictions")
    mappings = forecasting.map_exposures("US adds advanced-chip export restrictions")
    assert category == "INDUSTRY"
    assert factors == ["SEMICONDUCTOR_EXPORT_RESTRICTION"]
    assert "NVDA" in mappings[0].linked_companies
    assert mappings[0].mechanism == "China revenue and advanced-chip sales exposure"
    assert mappings[0].direction == "NEGATIVE"


def test_intelligence_maps_market_to_portfolio_and_thesis(monkeypatch) -> None:
    monkeypatch.setattr(database, "prediction_market_observations", lambda limit=200: [{
        "provider": "Kalshi", "market_id": "chips-1", "title": "US adds advanced-chip export restrictions",
        "probability": .39, "observed_at": NOW.isoformat(), "volume": 20_000, "bid": .37, "ask": .40,
        "resolution_criteria": "Resolves yes on an official published restriction", "history": [
            {"probability": .18, "observed_at": (NOW - timedelta(days=7)).isoformat()}],
        "source_url": "https://example.test/chips"}])
    monkeypatch.setattr(database, "list_portfolios", lambda user_id: [{"holdings": [{"ticker": "NVDA"}]}])
    monkeypatch.setattr(forecasting.theses, "list_theses", lambda user_id: [{
        "id": "thesis-1", "ticker": "NVDA", "assumptions": [{"id": "a1",
        "description": "Export restrictions do not materially tighten", "category": "REGULATORY"}]}])
    market = forecasting.build_intelligence("user-1")["markets"][0]
    assert market["probability"]["source_type"] == "MARKET_IMPLIED"
    assert market["change"]["percentage_point_change"] == 21
    assert market["affected_holdings"] == ["NVDA"]
    assert market["affected_theses"][0]["thesis_id"] == "thesis-1"


def test_conflicting_providers_are_not_averaged(monkeypatch) -> None:
    rows = [{"provider": provider, "market_id": provider, "title": "Fed cuts rates by September",
             "canonical_scenario": "recession_cuts", "probability": probability,
             "observed_at": NOW.isoformat(), "volume": 20_000, "bid": probability-.01,
             "ask": probability+.01, "resolution_criteria": "Official Fed decision", "history": []}
            for provider, probability in (("Kalshi", .64), ("Polymarket", .51))]
    monkeypatch.setattr(database, "prediction_market_observations", lambda limit=200: rows)
    monkeypatch.setattr(database, "list_portfolios", lambda user_id: [])
    monkeypatch.setattr(forecasting.theses, "list_theses", lambda user_id: [])
    result = forecasting.build_intelligence("user-1")
    assert [item["probability"]["probability"] for item in result["markets"]] == [.64, .51]
    assert result["disagreements"][0]["agreement"] == "LOW"
    assert "No aggregation" in result["disagreements"][0]["methodology"]


def test_user_forecasts_are_append_only_compared_and_resolved() -> None:
    first = database.save_user_forecast("user-a", {"event_key": "recession_cuts", "title": "Recession",
        "probability": .45, "market_probability_at_entry": .24, "reasoning": "Credit weakening"})
    second = database.save_user_forecast("user-a", {"event_key": "recession_cuts", "title": "Recession",
        "probability": .40, "market_probability_at_entry": .26, "reasoning": "Labor resilient"})
    database.save_user_forecast("user-b", {"event_key": "recession_cuts", "title": "Recession", "probability": .10})
    rows = database.list_user_forecasts("user-a", "recession_cuts")
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert forecasting.compare_probabilities(.45, .24)["user_vs_market_points"] == 21
    database.save_forecast_resolution("recession_cuts", 1, NOW.isoformat(), reference="official release")
    assert all(row["resolved_outcome"] == 1 for row in database.list_user_forecasts("user-a", "recession_cuts"))


def test_user_probability_changes_scenario_assumption_not_market(monkeypatch) -> None:
    monkeypatch.setattr(forecasting, "build_intelligence", lambda user_id, limit=200: {"markets": [{
        "event_key": "recession_cuts", "probability": {"probability": .24, "as_of": NOW.isoformat()},
        "provider": "Kalshi", "affected_holdings": ["AAPL"], "affected_theses": [], "exposures": []}]})
    monkeypatch.setattr(forecasting, "get_forecast", lambda target, horizon: {"status": "AVAILABLE",
        "forecast_type": "COMPOSITE", "point_estimate": .27, "input_data_as_of": NOW.isoformat(),
        "methodology": "test composite"})
    monkeypatch.setattr(database, "latest_analysis", lambda user_id: {})
    response = TestClient(app).post("/api/forecasting/portfolio-scenarios",
                                    json={"event_key": "recession_cuts", "user_probability": .45})
    assert response.status_code == 200
    body = response.json()
    assert body["market_probability"]["probability"] == .24
    assert body["effective_probability"]["source_type"] == "USER_DEFINED"
    assert body["effective_probability"]["probability"] == .45
    assert body["comparison"]["user_vs_market_points"] == 21


def test_forecast_interface_does_not_invent_missing_target(monkeypatch) -> None:
    monkeypatch.setattr(database, "latest_scenario_snapshot", lambda: {"scenarios": []})
    result = forecasting.get_forecast("unsupported_target", "12 months")
    assert result["status"] == "UNAVAILABLE"
    assert "no approved model output" in result["message"]


def test_ask_forecasting_tool_returns_structured_sourced_facts(monkeypatch) -> None:
    monkeypatch.setattr(forecasting, "build_intelligence", lambda user_id, ticker=None, limit=12: {
        "as_of": NOW.isoformat(), "disagreements": [], "markets": [{
            "provider": "Kalshi", "market_id": "fed-1", "event_key": "INTEREST_RATES",
            "title": "Fed cuts rates by September", "source_url": "https://example.test/fed",
            "probability": {"probability": .67, "as_of": NOW.isoformat()},
            "change": {"percentage_point_change": 25}, "quality": {"level": "HIGH"},
            "affected_holdings": ["MSFT"], "affected_theses": [],
            "exposures": [{"factor": "INTEREST_RATES", "mechanism": "duration-sensitive valuation"}],
        }]})
    tools, evidence_rows = _forecasting_chat_tools("user-1", "What is the market pricing for a Fed cut?")
    assert tools[0]["tool_name"] == "prediction_market_intelligence"
    assert evidence_rows[0]["data"]["probability_type"] == "MARKET_IMPLIED"
    assert evidence_rows[0]["data"]["probability"] == .67
    assert evidence_rows[0]["data"]["change"]["percentage_point_change"] == 25
