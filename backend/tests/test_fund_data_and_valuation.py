from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from backend.analysis import _valuation_evidence
from backend.fund_data import _ark_snapshot, _safe_provider_error, _state_street_snapshot, ensure_fund_data, holdings_freshness, refresh_etf_catalog


def test_transparent_valuation_reports_raw_multiples_and_threshold_effects() -> None:
    result = _valuation_evidence(
        imported_score=None,
        price=100,
        metrics={
            "shares_diluted": 10,
            "revenue": 100,
            "eps_diluted": 2,
            "free_cash_flow": 20,
        },
        fiscal_period="FY",
    )
    assert result["status"] == "available"
    assert result["raw_metrics"]["pe"] == 50
    assert result["raw_metrics"]["price_to_sales"] == 10
    assert result["raw_metrics"]["free_cash_flow_yield"] == .02
    assert result["score"] == 33
    assert result["method"] == "transparent-multiples-v1"


def test_transparent_valuation_refuses_to_claim_a_range_with_thin_inputs() -> None:
    result = _valuation_evidence(imported_score=None, price=100, metrics={}, fiscal_period="Q2")
    assert result["status"] == "insufficient"
    assert result["score"] is None
    assert "diluted share count" in result["missing_inputs"]


def test_ark_parser_converts_percent_points_to_fractional_weights() -> None:
    response = Mock()
    response.text = "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n08/10/2026,ARKK,TESLA,TSLA,x,1,$1,9.23%\n"
    response.raise_for_status.return_value = None
    with patch("backend.fund_data.requests.get", return_value=response):
        result = _ark_snapshot("ARKK")
    assert result["provider"] == "ARK Invest"
    assert result["holdings"][0]["ticker"] == "TSLA"
    assert result["holdings"][0]["weight"] == pytest.approx(.0923)
    assert result["holdings"][0]["as_of"] == "2026-08-10"


def test_etf_provider_failure_is_visible_instead_of_becoming_zero_holdings() -> None:
    with (
        patch("backend.fund_data.database.fund_reference_data", return_value={"funds": [], "holdings": []}),
        patch("backend.fund_data._massive_snapshot", side_effect=PermissionError("ETF plan missing")),
        patch("backend.fund_data._invesco_snapshot", side_effect=PermissionError("sponsor blocked request")),
    ):
        result = ensure_fund_data("QQQ")
    assert result["status"] == "missing"
    assert "ETF plan missing" in result["reason"]
    assert "sponsor blocked request" in result["reason"]


def test_provider_errors_never_include_api_query_strings() -> None:
    response = Mock(status_code=403)
    error = requests.HTTPError("403 for url: https://provider.test/data?apiKey=secret", response=response)
    assert _safe_provider_error(error) == "Provider returned HTTP 403"
    assert "secret" not in _safe_provider_error(error)


def test_holdings_freshness_distinguishes_daily_delayed_stale_and_unavailable(monkeypatch) -> None:
    class FixedDate:
        @classmethod
        def today(cls):
            return __import__("datetime").date(2026, 8, 10)
    monkeypatch.setattr("backend.fund_data.date", FixedDate)
    assert holdings_freshness("2026-08-10", "daily")["status"] == "daily"
    assert holdings_freshness("2026-08-01")["status"] == "delayed"
    assert holdings_freshness("2026-01-01")["status"] == "stale"
    assert holdings_freshness(None)["status"] == "unavailable"


def test_catalog_refresh_pages_reference_etfs_and_infers_issuer() -> None:
    first = Mock()
    first.raise_for_status.return_value = None
    first.json.return_value = {"results": [{"ticker": "IVV", "name": "iShares Core S&P 500 ETF", "type": "ETF", "active": True}], "next_url": "https://api.massive.com/v3/reference/tickers?cursor=next"}
    second = Mock()
    second.raise_for_status.return_value = None
    second.json.return_value = {"results": [{"ticker": "VOO", "name": "Vanguard S&P 500 ETF", "type": "ETF", "active": True}]}
    empty = Mock()
    empty.raise_for_status.return_value = None
    empty.json.return_value = {"results": []}
    with (
        patch.dict("os.environ", {"POLYGON_API_KEY": "test-key"}),
        patch("backend.fund_data.requests.get", side_effect=[first, second, empty]),
        patch("backend.fund_data.database.upsert_etf_catalog", return_value=2) as upsert,
        patch("backend.fund_data.database.record_etf_refresh"),
    ):
        result = refresh_etf_catalog()
    assert result == {"status": "success", "count": 2, "provider": "Massive Reference"}
    rows = upsert.call_args_list[0].args[0]
    assert [row["ticker"] for row in rows] == ["IVV", "VOO"]
    assert [row["issuer"] for row in rows] == ["iShares", "Vanguard"]


def test_state_street_parser_reads_complete_dated_percent_weights() -> None:
    import io
    import openpyxl
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(("Fund Name:", "Fixture SPDR"))
    sheet.append(("Ticker Symbol:", "SPY"))
    sheet.append(("Holdings:", "As of 07-Aug-2026"))
    sheet.append(())
    sheet.append(("Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"))
    sheet.append(("Apple", "AAPL", "x", "x", 6.5, "Technology", 1, "USD"))
    content = io.BytesIO()
    workbook.save(content)
    response = Mock(content=content.getvalue())
    response.raise_for_status.return_value = None
    with patch("backend.fund_data.requests.get", return_value=response):
        result = _state_street_snapshot("SPY")
    assert result["provider"] == "State Street SPDR"
    assert result["as_of"] == "2026-08-07"
    assert result["holdings"][0]["weight"] == pytest.approx(.065)
