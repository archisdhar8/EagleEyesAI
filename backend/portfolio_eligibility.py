from __future__ import annotations

import re
from typing import Any


MUTUAL_FUND_SYMBOL = re.compile(r"^[A-Z]{4}X$")
CUSIP_LIKE_IDENTIFIER = re.compile(r"^[A-Z0-9]{9}$")
CASH_SYMBOLS = {"CASH", "CASHXX", "USD", "US DOLLAR"}


def analysis_exclusion_reason(ticker: str) -> str | None:
    """Classify positions that do not belong in the stock/ETF optimizer.

    U.S. open-end mutual funds conventionally use five-letter symbols ending
    in X. Nine-character alphanumeric identifiers are treated as CUSIP-like
    instruments unless a future instrument master explicitly maps them.
    """
    normalized = str(ticker or "").strip().upper()
    if normalized in CASH_SYMBOLS:
        return "cash"
    if MUTUAL_FUND_SYMBOL.fullmatch(normalized):
        return "mutual_fund"
    if CUSIP_LIKE_IDENTIFIER.fullmatch(normalized):
        return "fixed_income_or_unverified_identifier"
    return None


def equity_analysis_holdings(holdings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for holding in holdings:
        reason = analysis_exclusion_reason(str(holding.get("ticker") or ""))
        if reason is None:
            eligible.append(holding)
            continue
        excluded.append({
            "ticker": str(holding.get("ticker") or "").strip().upper(),
            "reason": reason,
            "market_value": holding.get("market_value"),
            "weight": holding.get("weight"),
        })
    return eligible, excluded
