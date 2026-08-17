from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from . import database
from .analysis import security_research
from .models import ETFAllocationRequest, StockBasketRequest


ETF_VERSION = "etf-allocation-builder-v1.0.0"
STOCK_VERSION = "stock-basket-builder-v1.0.0"


def _monthly_returns(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    rows = database.price_history(tickers, 10000)
    if not rows:
        return pd.DataFrame(), {}
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None)
    providers = frame.groupby("ticker")["provider"].last().to_dict()
    prices = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    returns = prices.resample("ME").last().pct_change(fill_method=None).dropna(how="all")
    return returns, providers


def _metrics(returns: pd.DataFrame, weights: np.ndarray) -> dict[str, float | None]:
    clean = returns.dropna()
    if clean.empty or len(weights) != clean.shape[1]:
        return {"annual_return": None, "volatility": None, "sharpe_ratio": None, "maximum_drawdown": None}
    series = pd.Series(clean.to_numpy() @ weights, index=clean.index)
    annual_return = float((1 + series).prod() ** (12 / len(series)) - 1)
    volatility = float(series.std(ddof=1) * math.sqrt(12)) if len(series) > 1 else None
    wealth = (1 + series).cumprod()
    drawdown = float((wealth / wealth.cummax() - 1).min())
    return {
        "annual_return": round(annual_return, 4), "volatility": round(volatility, 4) if volatility is not None else None,
        "sharpe_ratio": round((annual_return - .04) / volatility, 3) if volatility else None,
        "maximum_drawdown": round(drawdown, 4),
    }


def _optimize(
    returns: pd.DataFrame,
    max_weight: float,
    objective: str,
    costs: np.ndarray | None = None,
    group_limits: list[tuple[list[int], float, str]] | None = None,
    research_signal: np.ndarray | None = None,
) -> tuple[np.ndarray, list[str]]:
    clean = returns.dropna()
    n = clean.shape[1]
    if n == 0:
        return np.array([]), ["No common monthly history is available."]
    if max_weight * n < .999:
        return np.repeat(1 / n, n), [f"Maximum weight {max_weight:.0%} is infeasible for {n} eligible securities."]
    mean = clean.mean().to_numpy() * 12
    covariance = clean.cov().to_numpy() * 12
    covariance = .75 * covariance + .25 * np.diag(np.diag(covariance))
    cost = costs if costs is not None else np.zeros(n)
    signal = research_signal if research_signal is not None and len(research_signal) == n else np.zeros(n)
    def loss(weights: np.ndarray) -> float:
        ret = float(mean @ weights)
        variance = float(weights @ covariance @ weights)
        concentration = float(np.sum(weights ** 2))
        if objective in {"lower_downside", "diversification"}:
            return variance * 6 + concentration * .8 - ret * .15 + float(cost @ weights)
        if objective in {"growth", "quality_growth"}:
            return -ret * .55 - float(signal @ weights) * .07 + variance * 2 + concentration * .2 + float(cost @ weights)
        if objective in {"value", "income", "macro_resilience", "custom"}:
            return -ret * .25 - float(signal @ weights) * .08 + variance * 2.8 + concentration * .35 + float(cost @ weights)
        if objective in {"lowest_cost"}:
            return float(cost @ weights) * 10 + variance * 2 + concentration * .2
        return -ret * .45 + variance * 3.5 + concentration * .45 + float(cost @ weights) * 2
    constraints: list[dict[str, Any]] = [{"type": "eq", "fun": lambda weights: weights.sum() - 1}]
    for indices, limit, _label in group_limits or []:
        constraints.append({
            "type": "ineq",
            "fun": lambda weights, members=np.asarray(indices, dtype=int), cap=limit: cap - float(weights[members].sum()),
        })
    result = minimize(loss, np.repeat(1 / n, n), method="SLSQP", bounds=[(0, max_weight)] * n, constraints=constraints, options={"maxiter": 500, "ftol": 1e-10})
    if not result.success:
        return np.repeat(1 / n, n), [f"Optimizer diagnostic: {result.message}"]
    return result.x, []


def optimize_etfs(request: ETFAllocationRequest) -> dict[str, Any]:
    excluded = {ticker.upper() for ticker in request.excluded_tickers}
    requested = list(dict.fromkeys(ticker.upper() for ticker in request.candidate_tickers if ticker.upper() not in excluded))
    if not requested:
        requested = [row["ticker"] for row in database.search_etf_catalog(limit=100).get("results", []) if row["ticker"] not in excluded]
    catalog = {ticker: database.etf_catalog_entry(ticker) for ticker in requested}
    catalog = {ticker: row for ticker, row in catalog.items() if row and float(row.get("expense_ratio") or 0) <= request.max_expense_ratio}
    returns, providers = _monthly_returns(list(catalog))
    eligible = []
    exclusions = []
    for ticker, row in catalog.items():
        observations = int(returns[ticker].notna().sum()) if ticker in returns else 0
        liquidity = float(row.get("average_daily_volume") or row.get("aum") or 0)
        if request.minimum_liquidity > 0 and liquidity < request.minimum_liquidity:
            reason = "Liquidity evidence is unavailable." if liquidity <= 0 else f"Liquidity {liquidity:,.0f} is below the {request.minimum_liquidity:,.0f} minimum."
            exclusions.append({"ticker": ticker, "reason": reason})
        elif observations < request.minimum_history_years * 12:
            exclusions.append({"ticker": ticker, "reason": f"Only {observations} monthly observations; minimum is {request.minimum_history_years * 12:.0f}."})
        else:
            eligible.append(ticker)
    panel = returns[eligible] if eligible else pd.DataFrame()
    costs = np.asarray([float(catalog[ticker].get("expense_ratio") or 0) for ticker in eligible])
    issuer_groups: list[tuple[list[int], float, str]] = []
    for issuer in sorted({str(catalog[ticker].get("issuer") or "Unknown") for ticker in eligible}):
        indices = [index for index, ticker in enumerate(eligible) if str(catalog[ticker].get("issuer") or "Unknown") == issuer]
        issuer_groups.append((indices, request.max_issuer_weight, f"issuer:{issuer}"))
    weights, conflicts = _optimize(panel, request.max_fund_weight, request.objective, costs, issuer_groups)
    covered_categories = {str(catalog[ticker].get("category") or "").lower() for ticker in eligible}
    for required in request.required_asset_classes:
        if not any(required.lower() in category for category in covered_categories):
            conflicts.append(f"Required asset class '{required}' has no eligible ETF in the analyzed universe.")
    allocations = []
    for index, ticker in enumerate(eligible):
        detail = database.etf_research_detail(ticker, [holding.ticker for holding in request.current_holdings]) or {}
        weight = float(weights[index])
        allocations.append({
            "ticker": ticker, "name": catalog[ticker].get("name"), "issuer": catalog[ticker].get("issuer"),
            "category": catalog[ticker].get("category"), "benchmark": catalog[ticker].get("benchmark"),
            "target_range": [round(max(0, weight - .025), 4), round(min(request.max_fund_weight, weight + .025), 4)],
            "reference_weight": round(weight, 4), "expense_ratio": float(catalog[ticker].get("expense_ratio") or 0),
            "holdings_coverage": (detail.get("snapshot_coverage") or {}).get("coverage_percentage"),
            "effective_holdings": (detail.get("concentration") or {}).get("effective_holdings"),
            "top_10_weight": (detail.get("concentration") or {}).get("top_10_weight"),
            "what_it_contributes": f"{catalog[ticker].get('category') or 'Diversified ETF'} exposure with disclosed cost and look-through evidence.",
        })
    portfolio_metrics = _metrics(panel, weights) if len(weights) else _metrics(panel, weights)
    annual_expense = request.initial_investment * float(costs @ weights) if len(weights) else 0
    equal = np.repeat(1 / len(eligible), len(eligible)) if eligible else np.array([])
    three_fund_symbols = [ticker for ticker in ("VTI", "VXUS", "BND") if ticker in eligible]
    three_fund_weights = np.asarray([.60, .25, .15])[[("VTI", "VXUS", "BND").index(ticker) for ticker in three_fund_symbols]] if three_fund_symbols else np.array([])
    if len(three_fund_weights):
        three_fund_weights = three_fund_weights / three_fund_weights.sum()
    current_map = {holding.ticker: float(holding.weight or 0) for holding in request.current_holdings if holding.ticker in eligible}
    current_weights = np.asarray([current_map.get(ticker, 0) for ticker in eligible])
    if current_weights.sum() > 0:
        current_weights /= current_weights.sum()
    look_through: dict[str, float] = {}
    for allocation in allocations:
        detail = database.etf_research_detail(allocation["ticker"]) or {}
        for key, value in (detail.get("exposures") or {}).items():
            if isinstance(value, (int, float)):
                look_through[key] = look_through.get(key, 0) + allocation["reference_weight"] * float(value)
    return {
        "builder_type": "etf", "model_version": ETF_VERSION, "objective": request.objective,
        "universe": {"requested": requested, "eligible": eligible, "excluded": exclusions, "count": len(eligible)},
        "allocations": allocations, "portfolio_metrics": portfolio_metrics,
        "expected_expense_dollars_year_one": round(annual_expense, 2),
        "benchmarks": [
            *([{"name": "Equal weight", **_metrics(panel, equal)}] if len(equal) else []),
            *([{"name": "Simple three-fund", "symbols": three_fund_symbols, **_metrics(panel[three_fund_symbols], three_fund_weights)}] if len(three_fund_weights) else []),
            *([{"name": "Current allocation", **_metrics(panel, current_weights)}] if current_weights.sum() > 0 else []),
        ],
        "look_through_exposure": {key: round(value, 4) for key, value in sorted(look_through.items())},
        "overlap": _etf_overlap(eligible), "constraints": {"status": "infeasible" if conflicts else "satisfied", "diagnostics": conflicts},
        "lineage": [{"provider": "+".join(sorted(set(providers.values()))), "dataset": "adjusted ETF prices", "symbols": eligible}, {"provider": "issuer/provider snapshots", "dataset": "dated ETF catalog and holdings", "symbols": eligible}],
        "assumptions": ["Weights are shown as ranges around a reproducible reference solution.", "Fund expenses reduce results; holdings gaps remain explicit.", "This is a research allocation, not a trade instruction."],
        "warnings": [item["reason"] for item in exclusions],
    }


def _etf_overlap(tickers: list[str]) -> list[dict[str, Any]]:
    details = {ticker: database.etf_research_detail(ticker) or {} for ticker in tickers}
    holdings = {ticker: {row["constituent_ticker"]: float(row["weight"] or 0) for row in detail.get("holdings", [])} for ticker, detail in details.items()}
    rows = []
    for index, left in enumerate(tickers):
        for right in tickers[index + 1:]:
            shared = set(holdings[left]) & set(holdings[right])
            rows.append({"left": left, "right": right, "overlap_weight": round(sum(min(holdings[left][ticker], holdings[right][ticker]) for ticker in shared), 4), "shared_holdings": len(shared)})
    return sorted(rows, key=lambda row: row["overlap_weight"], reverse=True)


def optimize_stocks(request: StockBasketRequest) -> dict[str, Any]:
    excluded = {ticker.upper() for ticker in request.excluded_tickers}
    requested = list(dict.fromkeys(ticker.upper() for ticker in request.candidate_tickers if ticker.upper() not in excluded))
    research = {row["ticker"]: row for row in security_research(requested)}
    returns, providers = _monthly_returns([*requested, request.benchmark.upper()])
    eligible, exclusions = [], []
    for ticker in requested:
        observations = int(returns[ticker].notna().sum()) if ticker in returns else 0
        if ticker not in research:
            exclusions.append({"ticker": ticker, "reason": "No validated security research record."})
        elif observations < request.minimum_history_years * 12:
            exclusions.append({"ticker": ticker, "reason": f"Only {observations} monthly observations."})
        else:
            eligible.append(ticker)
    panel = returns[eligible] if eligible else pd.DataFrame()
    group_limits: list[tuple[list[int], float, str]] = []
    for field, limit in (("sector", request.max_sector_weight), ("industry", request.max_industry_weight)):
        values = sorted({str(research[ticker].get(field) or "Unknown") for ticker in eligible})
        for value in values:
            indices = [index for index, ticker in enumerate(eligible) if str(research[ticker].get(field) or "Unknown") == value]
            group_limits.append((indices, limit, f"{field}:{value}"))
    def signal(row: dict[str, Any]) -> float:
        confidence = float(row.get("confidence") or 0) / 100
        sector = str(row.get("sector") or "")
        components = {
            "quality": float(row.get("fundamental_score") or 0) / 100,
            "fundamentals": float(row.get("fundamental_score") or 0) / 100,
            "growth": float(row.get("growth_rating") or 0) / 100,
            "value": float(row.get("valuation_score") or 0) / 100,
            "valuation": float(row.get("valuation_score") or 0) / 100,
            "price_behavior": float(row.get("technical_score") or 0) / 100,
            "income": .72 if sector in {"Utilities", "Energy", "Real Estate", "Fixed Income"} else .45,
            "macro_resilience": .72 if sector in {"Utilities", "Healthcare", "Consumer Staples", "Fixed Income"} else .45,
        }
        if request.objective == "quality_growth":
            raw = .5 * components["quality"] + .5 * components["growth"]
        elif request.objective == "value":
            raw = components["value"]
        elif request.objective == "income":
            raw = components["income"]
        elif request.objective == "macro_resilience":
            raw = components["macro_resilience"]
        elif request.objective == "custom":
            total = sum(max(0, float(value)) for value in request.factor_weights.values()) or 1
            raw = sum(max(0, float(weight)) * components.get(key, 0) for key, weight in request.factor_weights.items()) / total
        else:
            raw = 0
        return raw * confidence
    research_signal = np.asarray([signal(research[ticker]) for ticker in eligible], dtype=float)
    weights, conflicts = _optimize(panel, request.max_security_weight, request.objective, group_limits=group_limits, research_signal=research_signal)
    covariance = panel.dropna().cov().to_numpy() * 12 if not panel.empty else np.empty((0, 0))
    portfolio_variance = float(weights @ covariance @ weights) if len(weights) else 0
    allocations = []
    for index, ticker in enumerate(eligible):
        row = research[ticker]
        marginal = float(weights[index] * (covariance @ weights)[index] / portfolio_variance) if portfolio_variance > 0 else 0
        allocations.append({
            "ticker": ticker, "company": row.get("company"), "sector": row.get("sector"), "industry": row.get("industry"),
            "target_range": [round(max(0, weights[index] - .02), 4), round(min(request.max_security_weight, weights[index] + .02), 4)],
            "reference_weight": round(float(weights[index]), 4), "marginal_contribution_to_risk": round(marginal, 4),
            "research_strengths": row.get("strengths", []), "research_weaknesses": row.get("risks", []),
            "included_because": f"Eligible under the disclosed {request.objective.replace('_', ' ')} objective and history constraints.",
            "what_would_change_it": "A material change in fundamentals, valuation, liquidity, correlation stability, or portfolio constraints.",
        })
    benchmark_metrics = None
    if request.benchmark.upper() in returns:
        benchmark_metrics = _metrics(returns[[request.benchmark.upper()]], np.array([1.0]))
    equal = np.repeat(1 / len(eligible), len(eligible)) if eligible else np.array([])
    return {
        "builder_type": "stock", "model_version": STOCK_VERSION, "objective": request.objective,
        "universe": {"requested": requested, "eligible": eligible, "excluded": exclusions, "count": len(eligible)},
        "allocations": allocations, "portfolio_metrics": _metrics(panel, weights),
        "benchmarks": [
            {"name": "Equal weight", **_metrics(panel, equal)},
            *([{"name": request.benchmark.upper(), **benchmark_metrics}] if benchmark_metrics else []),
        ],
        "constraints": {"status": "infeasible" if conflicts else "satisfied", "diagnostics": conflicts},
        "lineage": [{"provider": "+".join(sorted(set(providers.values()))), "dataset": "monthly adjusted prices", "symbols": [*eligible, request.benchmark.upper()]}, {"provider": "EagleEyes research store", "dataset": "deterministic security research", "symbols": eligible}],
        "signal_method": {"objective": request.objective, "factor_weights": request.factor_weights if request.objective == "custom" else {}, "confidence_adjusted": True},
        "assumptions": ["Expected return comes from historical monthly adjusted returns, not the language model.", "Quality, growth, value, income, macro-resilience, and custom tilts use deterministic stored research evidence adjusted by coverage confidence.", "Income and macro-resilience use disclosed sector evidence where issuer-level measures are unavailable.", "Covariance uses common history and diagonal shrinkage.", "Directional trade labels are not generated."],
        "warnings": [item["reason"] for item in exclusions],
    }
