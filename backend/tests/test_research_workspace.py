from __future__ import annotations

from backend.portfolio_diagnostics import build_portfolio_diagnostics
from backend.research_workspace import evidence_bucket, search, theme_summaries


def _row(ticker: str = "AAPL", company: str = "Apple Inc.", confidence: float = 82) -> dict:
    return {
        "ticker": ticker, "company": company, "sector": "Information Technology",
        "industry": "Technology Hardware", "final_score": 72,
        "growth_rating": 68, "valuation_score": 61, "fundamental_score": 78,
        "industry_score": 65, "technical_score": 54, "confidence": confidence,
        "data_quality": "high", "revenue_growth": .12, "net_margin": .24,
        "price_change_1y": .18, "price_as_of": "2026-08-08", "fundamentals_as_of": "2026-06-30",
        "risk_flags": ["valuation_sensitivity"], "prediction_markets": [],
    }


def test_search_finds_aapl_by_symbol_or_company_and_discloses_universe() -> None:
    rows = [_row(), _row("MSFT", "Microsoft Corporation")]
    symbol = search(rows, query="AAPL", holdings=["AAPL"], watchlist=["MSFT"])
    company = search(rows, query="Apple")
    assert [row["ticker"] for row in symbol["results"]] == ["AAPL"]
    assert [row["ticker"] for row in company["results"]] == ["AAPL"]
    assert symbol["universe"]["total"] == 1
    assert symbol["results"][0]["relative_rank"] == 1
    assert "not buy recommendations" in symbol["disclaimer"]


def test_strong_fundamentals_reasonable_valuation_is_deterministic() -> None:
    weak = {**_row("WEAK", "Weak Company"), "fundamental_score": 59, "valuation_score": 90}
    expensive = {**_row("COST", "Costly Company"), "fundamental_score": 85, "valuation_score": 49}
    payload = search([_row(), weak, expensive], fundamentals="strong", valuation="reasonable")
    assert [row["ticker"] for row in payload["results"]] == ["AAPL"]
    assert payload["filters"] == {"fundamentals": "strong", "valuation": "reasonable", "theme": None}


def test_stale_or_weak_evidence_visibly_limits_conclusion() -> None:
    row = {**_row(confidence=30), "data_quality": "low"}
    assert evidence_bucket(row)[0] == "Limited evidence"
    result = search([row])["results"][0]
    assert result["freshness"]["coverage"] == "low"
    assert "Coverage or freshness" in result["bucket_explanation"]


def test_research_separates_peer_valuation_membership_fund_data_and_portfolio_fit() -> None:
    rows = [_row(), {**_row("MSFT", "Microsoft"), "valuation_score": 51}]
    context = {
        "memberships": [{"security_ticker": "AAPL", "collection_type": "index", "collection_name": "S&P 500", "as_of": "2026-08-01", "provider": "fixture"}],
        "funds": [{"ticker": "SPY", "expense_ratio": .0009, "effective_at": "2026-08-01", "provider": "fixture"}],
        "fund_holdings": [{"fund_ticker": "SPY", "constituent_ticker": "AAPL", "weight": .07, "as_of": "2026-08-01", "provider": "fixture"}],
        "containing_funds": [{"fund_ticker": "SPY", "constituent_ticker": "AAPL", "weight": .07, "as_of": "2026-08-01", "provider": "fixture"}],
        "events": [{"event_type": "earnings", "title": "Apple earnings", "starts_at": "2026-10-30T20:00:00Z", "tickers": ["AAPL"], "provider": "fixture"}],
    }
    result = search(rows, query="AAPL", holdings=["AAPL"], context=context)["results"][0]
    assert result["portfolio_fit"].startswith("Existing holding")
    assert result["comparable_valuation"]["peer_count"] == 1
    assert result["classification"]["memberships"][0]["name"] == "S&P 500"
    assert result["etf_overlap"][0]["fund_ticker"] == "SPY"
    assert any(item.get("type") == "earnings" for item in result["catalysts"])


def test_theme_search_discloses_mapping_and_actual_universe() -> None:
    payload = theme_summaries([_row(), {**_row("XLE", "Energy Select Sector SPDR"), "sector": "Energy", "industry": "Sector ETF"}])
    energy = next(item for item in payload["themes"] if item["key"] == "energy")
    assert energy["tickers"] == ["XLE"]
    assert energy["universe"]["total"] == 2
    assert "matched" in energy["mapping_rule"]


def test_portfolio_diagnostics_separates_hypothetical_performance_and_missing_coverage() -> None:
    holdings = [
        {"ticker": "AAPL", "weight": .6, "account_type": "taxable", "cost_basis": 1000},
        {"ticker": "SPY", "weight": .4, "account_type": "roth_ira"},
    ]
    security = {"securities": [
        {"ticker": "AAPL", "sector": "Technology", "industry": "Hardware"},
        {"ticker": "SPY", "sector": "Broad Market", "industry": "ETF"},
    ], "prices": []}
    result = build_portfolio_diagnostics(holdings, security, {"funds": [], "holdings": []})
    assert result["performance_label"].startswith("Hypothetical one-year return")
    assert result["tax_data_completeness"]["status"] == "partial"
    assert result["marginal_risk"]["status"] == "unavailable"
    assert result["holdings_fund_overlap"]["status"] == "unavailable"


def test_missing_components_are_not_substituted_with_neutral_scores() -> None:
    row = {
        **_row("NEW", "New Listing"),
        "component_coverage": {
            "growth": False, "valuation": False, "business_quality": False,
            "industry_position": True, "price_behavior": False,
        },
        "valuation_evidence": {
            "status": "insufficient", "source": "missing", "method": "none",
            "raw_metrics": {}, "components": [], "formula": "none",
            "missing_inputs": ["price"], "limitations": [],
        },
    }
    result = search([row], query="NEW")["results"][0]
    assert result["evidence_bucket"] == "Limited evidence"
    assert result["field_coverage"]["ratio"] == .2
    assert "Valuation" in result["field_coverage"]["missing"]
