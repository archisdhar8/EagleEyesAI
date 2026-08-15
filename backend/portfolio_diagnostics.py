from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .quant import dynamic_covariance


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    values = [_number(row.get("market_value")) for row in holdings]
    if sum(values) > 0:
        return {str(row["ticker"]).upper(): value / sum(values) for row, value in zip(holdings, values)}
    raw = [_number(row.get("weight")) for row in holdings]
    total = sum(raw)
    return {str(row["ticker"]).upper(): value / total for row, value in zip(holdings, raw)} if total else {}


def _group_exposure(weights: dict[str, float], security_rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    lookup = {str(row.get("ticker") or "").upper(): str(row.get(field) or "Unclassified") for row in security_rows}
    grouped: dict[str, float] = defaultdict(float)
    for ticker, weight in weights.items():
        grouped["Cash" if ticker == "CASH" else lookup.get(ticker, "Unclassified")] += weight
    return [{field: key, "weight": value} for key, value in sorted(grouped.items(), key=lambda item: item[1], reverse=True)]


def _risk_contribution(weights: dict[str, float], prices: list[dict[str, Any]]) -> dict[str, Any]:
    tickers = [ticker for ticker in weights if ticker != "CASH"]
    if len(tickers) < 2:
        return {"status": "unavailable", "positions": [], "reason": "At least two non-cash holdings with history are required."}
    frame = pd.DataFrame(prices)
    if frame.empty:
        return {"status": "unavailable", "positions": [], "reason": "Adjusted-price history is unavailable."}
    pivot = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()
    returns = pivot.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    estimate = dynamic_covariance(returns, tickers)
    vector = np.array([weights[ticker] for ticker in tickers], dtype=float)
    vector /= vector.sum()
    marginal = estimate.matrix @ vector
    variance = float(vector @ marginal)
    if variance <= 0:
        return {"status": "unavailable", "positions": [], "reason": "Portfolio variance could not be estimated."}
    shares = vector * marginal / variance
    positions = [{
        "ticker": ticker, "portfolio_weight": float(vector[index]),
        "risk_contribution": float(shares[index]), "marginal_variance": float(marginal[index]),
    } for index, ticker in enumerate(tickers)]
    positions.sort(key=lambda row: row["risk_contribution"], reverse=True)
    return {
        "status": "ready", "positions": positions,
        "method": "Marginal contribution to variance using dynamically shrunk covariance.",
        "sample_count": estimate.diagnostics.get("sample_count"),
        "model_details": estimate.diagnostics,
    }


def build_portfolio_diagnostics(
    holdings: list[dict[str, Any]], security_data: dict[str, Any], fund_data: dict[str, Any],
    implementation_paths: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    weights = _weights(holdings)
    security_rows = security_data.get("securities", [])
    fund_rows = fund_data.get("funds", [])
    fund_holdings = fund_data.get("holdings", [])
    account_exposure: dict[str, float] = defaultdict(float)
    for row in holdings:
        account_exposure[str(row.get("account_type") or "unknown")] += weights.get(str(row.get("ticker") or "").upper(), 0)

    direct = set(weights)
    overlaps = []
    by_fund: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fund_holdings:
        if row.get("constituent_ticker") in direct:
            by_fund[str(row.get("fund_ticker"))].append(row)
    for fund, members in by_fund.items():
        overlaps.append({
            "fund": fund,
            "direct_holdings_also_inside_fund": [row["constituent_ticker"] for row in members],
            "look_through_weight": sum(_number(row.get("weight")) for row in members),
            "as_of": max((row.get("as_of") for row in members), default=None),
        })

    portfolio_value = sum(_number(row.get("market_value")) for row in holdings)
    fund_costs = []
    known_cost = 0.0
    for row in fund_rows:
        ticker = str(row.get("ticker") or "")
        expense = _number(row.get("expense_ratio"))
        annual = portfolio_value * weights.get(ticker, 0) * expense if portfolio_value else None
        known_cost += annual or 0
        fund_costs.append({"ticker": ticker, "expense_ratio": expense, "estimated_annual_cost": annual, "provider": row.get("provider"), "effective_at": row.get("effective_at")})

    taxable = [row for row in holdings if row.get("account_type") == "taxable" and str(row.get("ticker") or "").upper() != "CASH"]
    cost_basis_known = sum(row.get("cost_basis") is not None for row in taxable)
    dates_known = sum(bool(row.get("acquisition_date")) for row in taxable)
    tax_status = "complete" if taxable and cost_basis_known == len(taxable) and dates_known == len(taxable) else "partial" if cost_basis_known or dates_known else "unavailable"

    warnings = []
    if not fund_rows:
        warnings.append("Fund expense-ratio coverage is unavailable for the saved holdings.")
    if any(item.get("sector") == "Unclassified" for item in _group_exposure(weights, security_rows, "sector")):
        warnings.append("Some holdings lack sector classification and are shown as unclassified.")
    return {
        "as_of": now,
        "sector_exposure": _group_exposure(weights, security_rows, "sector"),
        "industry_exposure": _group_exposure(weights, security_rows, "industry"),
        "account_allocation": [{"account_type": key, "weight": value} for key, value in sorted(account_exposure.items(), key=lambda item: item[1], reverse=True)],
        "marginal_risk": _risk_contribution(weights, security_data.get("prices", [])),
        "holdings_fund_overlap": {"status": "ready" if fund_holdings else "unavailable", "items": overlaps, "reason": None if fund_holdings else "No current ETF constituent dataset is stored."},
        "known_fund_costs": {"status": "ready" if fund_rows else "unavailable", "items": fund_costs, "estimated_annual_dollars": known_cost if fund_rows and portfolio_value else None, "portfolio_value_basis": portfolio_value or None},
        "tax_data_completeness": {"status": tax_status, "taxable_positions": len(taxable), "cost_basis_known": cost_basis_known, "acquisition_dates_known": dates_known, "missing_information": (["Aggregate cost basis"] if cost_basis_known < len(taxable) else []) + (["Acquisition dates"] if dates_known < len(taxable) else [])},
        "implementation_paths": implementation_paths or [],
        "performance_label": "Hypothetical one-year return using current holdings and weights",
        "warnings": warnings,
        "lineage": [
            {"provider": "saved portfolio", "dataset": "holdings", "effective_through": now, "symbols": sorted(weights)},
            {"provider": "stored market data", "dataset": "adjusted daily prices", "effective_through": max((row.get("date") for row in security_data.get("prices", [])), default=None), "symbols": sorted(weights)},
        ],
        "calculation": {"method": "portfolio-diagnostics", "version": "portfolio-diagnostics-v1"},
        "assumptions": ["Current saved holdings and normalized current weights are used.", "This is research analysis and does not reconstruct actual account performance or submit trades."],
    }
