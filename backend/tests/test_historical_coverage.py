from backend import historical_coverage


def test_coverage_reports_adjustment_dates_missing_sessions_and_proxy(monkeypatch):
    rows = [
        {"ticker": "AAPL", "provider": "tiingo", "observations": 1260, "explicit_adjusted_observations": 1260, "first_date": "2021-01-04", "last_date": "2026-01-05"},
        {"ticker": "XLK", "provider": "tiingo", "observations": 2520, "explicit_adjusted_observations": 2520, "first_date": "2016-01-04", "last_date": "2026-01-05"},
    ]
    monkeypatch.setattr(historical_coverage.database, "price_coverage_by_symbol", lambda tickers: [row for row in rows if row["ticker"] in tickers])
    result = historical_coverage.build_historical_coverage([{"ticker": "AAPL", "sector": "Technology"}])
    symbol = result["symbols"][0]
    assert symbol["corporate_action_adjusted"] is True
    assert symbol["first_date"] == "2021-01-04"
    assert symbol["last_date"] == "2026-01-05"
    assert symbol["estimated_missing_sessions"] >= 0
    assert symbol["full_cycle_available"] is False
    assert symbol["fallback"]["ticker"] == "XLK"
    assert symbol["fallback"]["available"] is True
    assert symbol["lineage"][0]["dataset_version"] == "adjusted-daily-prices-v1"
    assert result["warnings"]


def test_coverage_warns_when_direct_and_proxy_history_are_missing(monkeypatch):
    monkeypatch.setattr(historical_coverage.database, "price_coverage_by_symbol", lambda _: [])
    result = historical_coverage.build_historical_coverage([{"ticker": "NEW", "sector": "Unclassified"}])
    symbol = result["symbols"][0]
    assert symbol["provider"] is None
    assert symbol["direct_factor_model_eligible"] is False
    assert symbol["fallback"]["ticker"] == "VTI"
    assert symbol["fallback"]["available"] is False
    assert len(symbol["warnings"]) >= 3


def test_attach_coverage_preserves_all_research_fields(monkeypatch):
    monkeypatch.setattr(historical_coverage.database, "price_coverage_by_symbol", lambda _: [])
    source = [{"ticker": "ABC", "company": "ABC Corp", "final_score": 61.0, "sector": "Industrials", "custom": {"kept": True}}]
    enriched, _ = historical_coverage.attach_coverage(source)
    assert enriched[0]["custom"] == {"kept": True}
    assert enriched[0]["historical_coverage"]["ticker"] == "ABC"
