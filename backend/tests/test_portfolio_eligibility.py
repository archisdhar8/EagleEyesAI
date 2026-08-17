from backend.portfolio_eligibility import analysis_exclusion_reason, equity_analysis_holdings
from backend.portfolio_import import parse_portfolio_csv


def test_equity_analysis_keeps_stocks_and_etfs_only() -> None:
    holdings = [
        {"ticker": "AAPL", "weight": 0.25},
        {"ticker": "QQQ", "weight": 0.25},
        {"ticker": "GLIFX", "weight": 0.20},
        {"ticker": "PONPX", "weight": 0.20},
        {"ticker": "CASH", "weight": 0.10},
    ]
    eligible, excluded = equity_analysis_holdings(holdings)
    assert [row["ticker"] for row in eligible] == ["AAPL", "QQQ"]
    assert [(row["ticker"], row["reason"]) for row in excluded] == [
        ("GLIFX", "mutual_fund"),
        ("PONPX", "mutual_fund"),
        ("CASH", "cash"),
    ]
    assert analysis_exclusion_reason("BND") is None


def test_csv_keeps_non_equity_positions_but_marks_them_out_of_analysis() -> None:
    result = parse_portfolio_csv(
        "ticker,market_value\nAAPL,5000\nGLIFX,2000\nPONPX,2000\nCASH,1000\n",
        "Mixed account",
    )
    assert [row["ticker"] for row in result["holdings"]] == ["AAPL", "GLIFX", "PONPX", "CASH"]
    assert [row["ticker"] for row in result["analysis_exclusions"]] == ["GLIFX", "PONPX", "CASH"]
    assert any("excluded them from stock/ETF analysis" in warning for warning in result["warnings"])
