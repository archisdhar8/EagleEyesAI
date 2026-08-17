from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend import attention, database


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)


def _thesis(thesis_id: str = "thesis-nvda", review_date: str | None = None) -> dict:
    return {"id": thesis_id, "ticker": "NVDA", "status": "ACTIVE", "review_date": review_date,
            "updated_at": (NOW - timedelta(days=1)).isoformat()}


def _monitor(status: str = "THESIS_BREAKER_TRIGGERED") -> dict:
    return {
        "thesis_id": "thesis-nvda", "thesis_version": 1, "ticker": "NVDA",
        "overall_status": status, "requires_review": status != "STRENGTHENING",
        "evaluated_at": NOW.isoformat(), "created_at": NOW.isoformat(),
        "evidence_quality": "HIGH", "freshness": "HIGH",
        "assumption_results": [{"assumption_id": "a1", "description": "Export restrictions do not materially tighten",
            "importance": "HIGH", "state": "CONTRADICTS", "explanation": "Verified policy evidence contradicts the assumption.",
            "evidence": [{"label": "Export restriction probability", "metric": "prediction.probability",
                "source": "Kalshi", "current_as_of": NOW.isoformat(), "source_references": ["https://example.test/market"]}]}],
        "thesis_breaker_results": [{"factor_id": "b1", "description": "Export restrictions tighten",
            "state": "TRIGGERED" if status == "THESIS_BREAKER_TRIGGERED" else "NOT_TRIGGERED",
            "evidence": []}],
    }


def _market(*, quality: str = "HIGH", holdings: list[str] | None = None,
            theses: list[dict] | None = None, points: float = 25) -> dict:
    return {
        "provider": "Kalshi", "market_id": "fed-1", "event_key": "INTEREST_RATES",
        "title": "Fed cuts rates by September", "probability": {"probability": .67, "as_of": NOW.isoformat()},
        "quality": {"level": quality, "stale": quality == "LOW"},
        "change": {"previous_probability": .42, "percentage_point_change": points,
                   "materiality": "HIGH" if abs(points) >= 15 else "MEDIUM"},
        "affected_holdings": holdings or [], "affected_theses": theses or [],
        "exposures": [{"factor": "INTEREST_RATES", "mechanism": "duration-sensitive valuation"}],
        "source_url": "https://example.test/fed",
    }


def _compose(**overrides):
    values = {
        "holdings": [{"ticker": "NVDA", "weight": .40}, {"ticker": "SPY", "weight": .60}],
        "thesis_workspace": {"active_theses": []}, "monitoring_results": [],
        "forecasting_payload": {"markets": [], "warnings": []}, "events": [], "diagnostics": {},
        "research": [], "watchlist": [], "movements": [], "states": {}, "warnings": [], "now": NOW,
    }
    values.update(overrides)
    return attention.compose_attention(**values)


def test_breaker_has_explicit_priority_over_other_attention() -> None:
    result = _compose(
        thesis_workspace={"active_theses": [_thesis()]}, monitoring_results=[_monitor()],
        forecasting_payload={"markets": [_market(holdings=["NVDA"])], "warnings": []},
    )
    first = result["items"][0]
    assert first["type"] == "THESIS_BREAKER_TRIGGERED"
    assert first["materiality"] == "CRITICAL"
    assert first["ranking_inputs"]["breaker_override"] == "YES"


def test_prediction_market_move_with_large_exposure_outranks_low_quality_weak_relevance() -> None:
    strong = _market(quality="HIGH", holdings=["NVDA"])
    weak = {**_market(quality="LOW", holdings=["TINY"]), "market_id": "low-1", "event_key": "LOW_EVENT",
            "title": "Low quality distant event"}
    result = _compose(forecasting_payload={"markets": [weak, strong], "warnings": []})
    assert result["items"][0]["entity_key"] == "INTEREST_RATES"
    assert result["items"][0]["portfolio_relevance"] == "HIGH"


def test_related_thesis_and_market_developments_are_grouped() -> None:
    result = _compose(
        thesis_workspace={"active_theses": [_thesis()]}, monitoring_results=[_monitor("WEAKENING")],
        forecasting_payload={"markets": [_market(holdings=["NVDA"], theses=[{"thesis_id": "thesis-nvda", "ticker": "NVDA"}])], "warnings": []},
    )
    assert len(result["items"]) == 1
    assert "related development" in result["items"][0]["summary"]
    assert any(detail.get("related_type") == "PREDICTION_MARKET_CHANGE" for detail in result["items"][0]["details"])


def test_price_only_move_is_context_not_attention() -> None:
    result = _compose(movements=[{"ticker": "NVDA", "change_1d": -.05}])
    assert result["items"] == []
    assert result["no_material_change"] is True
    assert result["price_context"][0]["evidence_status"] == "NO_MATERIAL_EVIDENCE_CHANGE"
    assert "No material change" in result["price_context"][0]["message"]


def test_no_material_change_state_is_explicit_and_grounded() -> None:
    result = _compose()
    assert result["no_material_change"] is True
    assert result["material_item_count"] == 0
    assert "No material changes were detected" in result["daily_brief"]["text"]
    assert result["daily_brief"]["claim_item_ids"] == []


def test_upcoming_earnings_for_large_holding_is_prioritized() -> None:
    event = {"id": "earnings-1", "event_type": "earnings", "title": "NVDA earnings",
             "starts_at": (NOW + timedelta(days=3)).isoformat(), "tickers": ["NVDA"],
             "provider": "Nasdaq", "verified_at": NOW.isoformat(), "source_url": "https://example.test/event"}
    result = _compose(events=[event])
    item = result["items"][0]
    assert item["type"] == "UPCOMING_EARNINGS"
    assert item["urgency"] == "SOON"
    assert item["linked_portfolio_exposure"]["portfolio_weight"] == .4


def test_watchlist_threshold_is_a_research_prompt_not_buy_signal() -> None:
    result = _compose(
        research=[{"ticker": "CRM", "final_score": 82, "confidence": 88,
                   "fundamentals_as_of": NOW.isoformat(), "data_source": "stored research"}],
        watchlist=["CRM"],
    )
    item = result["items"][0]
    assert item["type"] == "WATCHLIST_THRESHOLD"
    assert item["action_label"] == "Review research"
    assert "not a buy signal" in item["why_it_matters"]


def test_missing_provider_is_warning_not_neutral_probability() -> None:
    result = _compose(warnings=["Prediction-market provider unavailable."])
    item = result["items"][0]
    assert item["type"] == "DATA_QUALITY_WARNING"
    assert item["evidence_quality"] == "INSUFFICIENT_DATA"
    assert "not interpreted as no risk" in item["why_it_matters"]


def test_attention_state_is_owner_scoped_and_does_not_delete_evidence() -> None:
    item_id = "a" * 32
    database.save_attention_state("user-a", item_id, "DISMISSED")
    database.save_attention_state("user-b", item_id, "READ")
    assert database.attention_states("user-a")[item_id]["state"] == "DISMISSED"
    assert database.attention_states("user-b")[item_id]["state"] == "READ"
    database.delete_attention_state("user-a", item_id)
    assert item_id not in database.attention_states("user-a")
    assert item_id in database.attention_states("user-b")


def test_daily_brief_claims_reference_only_structured_items() -> None:
    result = _compose(forecasting_payload={"markets": [_market(holdings=["NVDA"])], "warnings": []})
    ids = {item["id"] for item in result["items"]}
    assert set(result["daily_brief"]["claim_item_ids"]).issubset(ids)
    assert result["daily_brief"]["methodology"].startswith("Template synthesis")
