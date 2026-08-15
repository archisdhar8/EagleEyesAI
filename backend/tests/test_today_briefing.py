from backend.today_briefing import build_today_briefing, market_indicator_rows, market_movement_rows


def _prices(ticker: str, start: float, count: int = 22) -> list[dict]:
    return [
        {"ticker": ticker, "date": f"2026-07-{index + 1:02d}", "close": start + index, "fetched_at": "2026-08-01T00:00:00Z"}
        for index in range(count)
    ]


def _payload(portfolio=True):
    return {
        "portfolio": {"name": "Test", "holdings": [{"ticker": "AAPL", "weight": .35}, {"ticker": "SPY", "weight": .65}]} if portfolio else None,
        "research": [
            {"ticker": "AAPL", "sector": "Technology", "confidence": 80, "final_score": 60},
            {"ticker": "SPY", "sector": "Broad Market", "confidence": 90, "final_score": 65},
            {"ticker": "XLV", "sector": "Health Care", "confidence": 75, "final_score": 70, "source": "https://example.com/xlv", "price_as_of": "2026-07-22"},
        ],
        "scenarios": {"scenarios": [
            {"key": "sticky_inflation", "probability": .2, "as_of": "2026-07-22"},
            {"key": "recession_cuts", "probability": .2, "as_of": "2026-07-22"},
            {"key": "oil_shock", "probability": .1, "as_of": "2026-07-22"},
        ]},
        "data_status": {"providers": []}, "latest_analysis": None,
    }


def test_market_rows_compute_explicit_one_five_and_twenty_one_session_changes():
    rows = market_movement_rows(_prices("SPY", 100))
    assert rows[0]["change_1d"] == round(121 / 120 - 1, 6)
    assert rows[0]["change_1w"] == round(121 / 116 - 1, 6)
    assert rows[0]["change_1m"] == round(121 / 100 - 1, 6)
    assert rows[0]["group"] == "index"
    assert rows[0]["as_of"] == "2026-07-22"


def test_market_rows_deduplicate_overlapping_provider_sessions():
    rows = _prices("SPY", 100)
    duplicated = [
        {**row, "provider": "polygon", "fetched_at": "2026-08-02T00:00:00Z"}
        for row in rows
    ] + [
        {**row, "provider": "tiingo", "fetched_at": "2026-08-01T00:00:00Z"}
        for row in rows
    ]
    result = market_movement_rows(duplicated)[0]
    assert result["change_1d"] == round(121 / 120 - 1, 6)
    assert result["change_1w"] == round(121 / 116 - 1, 6)
    assert result["change_1m"] == round(121 / 100 - 1, 6)


def test_cross_asset_rows_keep_units_sources_and_observation_change():
    rows = market_indicator_rows([
        {"series_id": "DGS10", "date": "2026-08-08", "value": 4.2, "provider": "FRED", "source_url": "https://fred/rates"},
        {"series_id": "DGS10", "date": "2026-08-07", "value": 4.1, "provider": "FRED", "source_url": "https://fred/rates"},
    ])
    assert rows[0]["label"] == "10-year Treasury"
    assert rows[0]["change"] == .1
    assert rows[0]["source"] == "https://fred/rates"


def test_today_briefing_prioritizes_at_most_three_items_and_sources_every_claim():
    macro = [{"series_id": "DGS10", "date": "2026-08-08", "value": 4.2, "provider": "FRED", "source_url": "https://fred/rates"}]
    briefing = build_today_briefing(_payload(), _prices("SPY", 100) + _prices("XLK", 90) + _prices("XLV", 80), macro, [])
    assert len(briefing["attention"]) <= 3
    assert briefing["attention"][0]["key"] == "position_concentration"
    assert all(item["evidence"] for item in briefing["attention"])
    assert all(item["evidence"] for item in briefing["portfolio_relevance"])
    assert briefing["version"] == "today-briefing-v2"
    assert "score" not in briefing
    assert briefing["guidance"]["level"] == "Portfolio-Aware Analysis"
    assert all(row["data_status"] in {"end-of-day", "stale"} for row in briefing["market_movement"])
    assert all("minimum_data_requirements" in idea for idea in briefing["research_ideas"])


def test_today_briefing_works_without_portfolio_and_states_no_urgent_change():
    briefing = build_today_briefing(_payload(portfolio=False), _prices("SPY", 100), [], [])
    assert briefing["portfolio_context"]["available"] is False
    assert briefing["attention"] == []
    assert "No urgent portfolio-specific change" in briefing["summary"]
    assert briefing["guidance"]["level"] == "General Market Research"


def test_today_briefing_uses_latest_validated_snapshot_when_prices_are_missing():
    previous = {"market_movement": market_movement_rows(_prices("SPY", 100)), "market_indicators": []}
    briefing = build_today_briefing(_payload(), [], [], [], previous)
    assert briefing["evidence_state"] == "stale_fallback"
    assert briefing["market_movement"]
    assert briefing["market_movement"][0]["data_status"] == "cached"
    assert any("latest validated briefing snapshot" in warning for warning in briefing["warnings"])
