from backend import database
from backend.auth import AuthenticatedUser
from backend.main import (
    _RESEARCH_OVERVIEW_CACHE,
    add_watchlist_security,
    consolidated_research_security_overview,
    remove_watchlist_security,
)


USER = AuthenticatedUser("research-user", "research@example.com")


def test_consolidated_overview_is_portfolio_scoped_cached_and_ai_free(monkeypatch) -> None:
    row = {
        "ticker": "AAPL", "company": "Apple", "confidence": 80,
        "freshness": {"coverage": .8, "price_as_of": "2026-08-18", "fundamentals_as_of": "2026-06-30"},
        "field_coverage": {"missing": []},
    }
    monkeypatch.setattr(database, "list_portfolios", lambda user_id: [
        {"id": "other", "name": "Other", "holdings": [{"ticker": "MSFT", "weight": .5}]},
        {"id": "selected", "name": "Selected", "holdings": [{"ticker": "AAPL", "weight": .2}]},
    ])
    monkeypatch.setattr(database, "load_profile", lambda user_id: {"watchlist": ["AAPL"]})
    monkeypatch.setattr("backend.main._cached_research_detail", lambda ticker: ([row], {}))
    monkeypatch.setattr("backend.main.research_search_payload", lambda rows, *args, **kwargs: {"results": rows, "universe": {}, "method": {}})
    monkeypatch.setattr("backend.main.theses.active_thesis", lambda user_id, ticker: None)
    monkeypatch.setattr("backend.main.theses.decision_contexts", lambda user_id, tickers: {})
    monkeypatch.setattr("backend.main.earnings_intelligence_view", lambda ticker, user: {"status": "AVAILABLE"})
    monkeypatch.setattr("backend.main.forecasting.build_intelligence", lambda *args, **kwargs: {"markets": []})
    monkeypatch.setattr("backend.main.evidence.get_changes", lambda *args, **kwargs: {"changes": []})
    monkeypatch.setattr("backend.main.security_snapshot_overview", lambda ticker: {
        "market": {"price": 201.5, "as_of": "2026-08-18", "price_history": [{"date": "2026-08-18", "close": 201.5}]},
        "fundamentals": {"revenue_growth": .12}, "fundamental_periods": [], "sentiment_summary": {},
    })
    calls = []
    monkeypatch.setattr("backend.main.theses.evidence_draft", lambda ticker, research, allow_ai=True: (
        calls.append(allow_ai) or {"draft": {
            "base_case": "Base paragraph one.\n\nBase paragraph two.",
            "bear_case": "Bear paragraph one.\n\nBear paragraph two.",
            "bull_case": "Bull paragraph one.\n\nBull paragraph two.",
            "assumptions": [], "factors": [],
        }}
    ))
    _RESEARCH_OVERVIEW_CACHE.clear()

    first = consolidated_research_security_overview("aapl", "selected", USER)
    second = consolidated_research_security_overview("AAPL", "selected", USER)

    assert first["portfolio"]["id"] == "selected"
    assert first["membership"] == {"holding": True, "watchlist": True, "holding_detail": {"ticker": "AAPL", "weight": .2}}
    assert first["cases"]["bear"]["full_text"].startswith("Bear paragraph")
    assert first["intelligence"]["version"] == "research-intelligence-v1"
    assert first["intelligence"]["market"]["price"] == 201.5
    assert first["intelligence"]["valuation"]["fair_value"] is None
    assert calls == [False]
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"


def test_watchlist_endpoints_are_normalized_deduplicated_and_persistent(monkeypatch) -> None:
    profile = {"watchlist": ["MSFT", "msft"]}
    saved = []
    monkeypatch.setattr(database, "load_profile", lambda user_id: profile)
    monkeypatch.setattr("backend.main._cached_research_detail", lambda ticker: ([{"ticker": ticker}], {}))
    monkeypatch.setattr(database, "save_profile", lambda payload, user_id: saved.append(payload) or payload)

    added = add_watchlist_security(" aapl ", USER)
    profile.update(saved[-1])
    removed = remove_watchlist_security("MSFT", USER)

    assert added["tickers"] == ["MSFT", "AAPL"]
    assert removed["tickers"] == ["AAPL"]
