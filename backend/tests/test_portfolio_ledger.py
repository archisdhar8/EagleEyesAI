from __future__ import annotations

from backend.portfolio_ledger import calculate_performance, parse_transaction_csv, reconstruct_positions, tax_lot_coverage


def test_flexible_transaction_csv_and_duplicate_review() -> None:
    payload = parse_transaction_csv(
        "Trade Date,Action,Symbol,Shares,Price,Net Amount,Commission,Notes\n"
        "01/02/2025,Deposit,,,,1000,,initial\n"
        "01/03/2025,Buy,AAPL,5,100,,1,first lot\n"
        "01/03/2025,Buy,AAPL,5,100,,1,duplicate\n",
        "Taxable",
    )
    assert payload["valid"] is False
    assert len(payload["rows"]) == 2
    assert "Notes" in payload["unknown_columns"]
    assert any("duplicate" in error for error in payload["errors"])


def test_reconstruction_handles_dividends_fees_and_split() -> None:
    rows = [
        {"trade_date": "2025-01-01", "transaction_type": "deposit", "amount": 1000, "fee": 0},
        {"trade_date": "2025-01-02", "transaction_type": "buy", "ticker": "AAPL", "quantity": 5, "price": 100, "amount": None, "fee": 1},
        {"trade_date": "2025-02-01", "transaction_type": "dividend", "ticker": "AAPL", "amount": 10, "fee": 0},
        {"trade_date": "2025-03-01", "transaction_type": "split", "ticker": "AAPL", "quantity": 2, "fee": 0},
    ]
    result = reconstruct_positions(rows)
    assert result["positions"]["AAPL"] == 10
    assert result["cash"] == 509


def test_time_and_money_weighted_returns_are_separate() -> None:
    transactions = [{"trade_date": "2025-07-01", "transaction_type": "deposit", "amount": 100, "fee": 0}]
    result = calculate_performance(transactions, [
        {"date": "2025-01-01", "value": 100},
        {"date": "2025-07-01", "value": 210},
        {"date": "2026-01-01", "value": 231},
    ])
    assert result["status"] == "ready"
    assert round(result["time_weighted_return"], 4) == 0.21
    assert result["money_weighted_return"] is not None
    assert result["version"] == "account-performance-v1"


def test_tax_coverage_never_claims_wash_sale_completeness() -> None:
    result = tax_lot_coverage([{
        "account_id": "taxable", "trade_date": "2025-01-02", "transaction_type": "buy",
        "ticker": "AAPL", "quantity": 2, "price": 100, "fee": 1,
    }], "US federal only")
    assert result["status"] == "complete"
    assert result["included_lots"][0]["cost_basis"] == 201
    assert result["wash_sale_coverage"].startswith("unavailable")
