from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from . import database
from .allocation_builders import optimize_etfs, optimize_stocks
from .models import ETFAllocationRequest, ModelPortfolioBacktestRequest, ModelPortfolioCompareRequest, StockBasketRequest


MODEL_PORTFOLIO_VERSION = "model-portfolio-workbench-v1.0.0"
BACKTEST_VERSION = "model-portfolio-common-history-v1.0.0"


def _weights(result: dict[str, Any]) -> dict[str, float]:
    return {
        row["ticker"]: float(row["reference_weight"])
        for row in result.get("allocations", [])
        if float(row.get("reference_weight") or 0) > 0
    }


def compare(request: ModelPortfolioCompareRequest) -> dict[str, Any]:
    tickers = request.candidate_tickers
    funds = [ticker for ticker in tickers if database.etf_catalog_entry(ticker)]
    stocks = [ticker for ticker in tickers if ticker not in funds]
    warnings: list[str] = []
    if request.portfolio_type == "stocks":
        analyzed = stocks
    elif request.portfolio_type == "etfs":
        analyzed = funds
    else:
        analyzed = tickers
        if funds and stocks:
            warnings.append("Mixed baskets use the security optimizer for common-history comparison; ETF fees and look-through overlap remain available on each fund page.")
    if len(analyzed) < 2:
        return {
            "version": MODEL_PORTFOLIO_VERSION,
            "status": "infeasible",
            "universe": {"requested": tickers, "analyzed": analyzed, "funds": funds, "stocks": stocks, "count": len(analyzed)},
            "alternatives": {},
            "warnings": ["At least two eligible securities with stored evidence are required."],
        }

    alternatives: dict[str, dict[str, Any]] = {}
    if request.portfolio_type == "etfs":
        objective_map = {
            "lower_downside": "lower_downside", "balanced": "balanced",
            "quality_growth": "growth", "income": "income",
        }
        def run_etf(item: tuple[str, str]) -> tuple[str, dict[str, Any]]:
            key, objective = item
            result = optimize_etfs(ETFAllocationRequest(
                candidate_tickers=analyzed, objective=objective,
                max_expense_ratio=request.max_expense_ratio,
                max_fund_weight=request.max_security_weight,
                minimum_history_years=request.minimum_history_years,
            ))
            return key, {"label": key.replace("_", " ").title(), "weights": _weights(result), "result": result}
        with ThreadPoolExecutor(max_workers=min(4, len(objective_map))) as executor:
            alternatives.update(dict(executor.map(run_etf, objective_map.items())))
        warnings.append("Value and custom factor alternatives are unavailable for ETF-only baskets until fund-level factor evidence is complete; no substitute result was invented.")
    else:
        objective_map = {
            "lower_downside": "lower_downside", "balanced": "diversification",
            "quality_growth": "quality_growth", "value": "value", "income": "income",
            "custom": "custom",
        }
        def run_stock(item: tuple[str, str]) -> tuple[str, dict[str, Any]]:
            key, objective = item
            result = optimize_stocks(StockBasketRequest(
                candidate_tickers=analyzed, benchmark=request.benchmark,
                objective=objective, factor_weights=request.factor_weights,
                max_security_weight=request.max_security_weight,
                minimum_history_years=request.minimum_history_years,
                minimum_data_quality="low",
            ))
            return key, {"label": key.replace("_", " ").title(), "weights": _weights(result), "result": result}
        with ThreadPoolExecutor(max_workers=min(4, len(objective_map))) as executor:
            alternatives.update(dict(executor.map(run_stock, objective_map.items())))

    eligible = sorted({ticker for item in alternatives.values() for ticker in item["weights"]})
    if eligible:
        equal = round(1 / len(eligible), 8)
        alternatives = {"equal_weight": {"label": "Equal weight", "weights": {ticker: equal for ticker in eligible}, "result": None}, **alternatives}
    return {
        "version": MODEL_PORTFOLIO_VERSION,
        "status": "ready" if eligible else "infeasible",
        "universe": {
            "requested": tickers, "analyzed": eligible, "funds": funds, "stocks": stocks,
            "count": len(eligible),
            "disclosure": f"Results identify the strongest available evidence within these {len(eligible)} analyzed securities; they are not a claim about every investment.",
        },
        "alternatives": alternatives,
        "warnings": warnings,
    }


def _metric(series: pd.Series) -> dict[str, Any]:
    series = series.dropna()
    if series.empty:
        return {"annual_return": None, "volatility": None, "sharpe_ratio": None, "maximum_drawdown": None, "ending_growth_of_one": None}
    annual_return = float((1 + series).prod() ** (12 / len(series)) - 1)
    volatility = float(series.std(ddof=1) * math.sqrt(12)) if len(series) > 1 else None
    wealth = (1 + series).cumprod()
    drawdown = float((wealth / wealth.cummax() - 1).min())
    return {
        "annual_return": round(annual_return, 5),
        "volatility": round(volatility, 5) if volatility is not None else None,
        "sharpe_ratio": round((annual_return - .04) / volatility, 3) if volatility else None,
        "maximum_drawdown": round(drawdown, 5),
        "ending_growth_of_one": round(float(wealth.iloc[-1]), 4),
    }


def backtest(request: ModelPortfolioBacktestRequest) -> dict[str, Any]:
    normalized: dict[str, dict[str, float]] = {}
    for key, values in request.alternatives.items():
        cleaned = {ticker.strip().upper(): float(value) for ticker, value in values.items() if float(value) > 0}
        total = sum(cleaned.values())
        if total > 0:
            normalized[key] = {ticker: value / total for ticker, value in cleaned.items()}
    benchmark = request.benchmark.upper()
    symbols = sorted({ticker for values in normalized.values() for ticker in values} | {benchmark, "SPY", "VTI", "VXUS", "BND"})
    rows = database.price_history(symbols, 10000)
    if not rows:
        return {"version": BACKTEST_VERSION, "status": "unavailable", "results": [], "warnings": ["No adjusted price history is stored for the requested basket."]}
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None)
    prices = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").resample("ME").last()
    returns = prices.pct_change(fill_method=None)
    series: dict[str, pd.Series] = {}
    warnings: list[str] = []
    for key, weights in normalized.items():
        available = [ticker for ticker in weights if ticker in returns]
        panel = returns[available].dropna()
        if not available or panel.empty:
            warnings.append(f"{key.replace('_', ' ').title()} lacks common adjusted history.")
            continue
        weight_values = np.asarray([weights[ticker] for ticker in available], dtype=float)
        weight_values /= weight_values.sum()
        series[key] = pd.Series(panel.to_numpy() @ weight_values, index=panel.index)
    if "SPY" in returns:
        series["benchmark_spy"] = returns["SPY"].dropna()
    else:
        warnings.append("The SPY benchmark is unavailable because adjusted price history is missing.")
    if benchmark != "SPY":
        if benchmark in returns:
            series[f"benchmark_relevant_{benchmark.lower()}"] = returns[benchmark].dropna()
        else:
            warnings.append(f"The requested relevant benchmark {benchmark} is unavailable because adjusted price history is missing.")
    three = [ticker for ticker in ("VTI", "VXUS", "BND") if ticker in returns]
    if len(three) == 3:
        panel = returns[three].dropna()
        series["benchmark_three_fund"] = pd.Series(panel.to_numpy() @ np.asarray([.60, .25, .15]), index=panel.index)
    else:
        warnings.append("The 60% VTI / 25% VXUS / 15% BND three-fund baseline is unavailable because one or more histories are missing.")
    if not series:
        return {"version": BACKTEST_VERSION, "status": "unavailable", "results": [], "warnings": warnings}
    common = pd.concat(series, axis=1, join="inner").dropna()
    if common.empty:
        return {"version": BACKTEST_VERSION, "status": "unavailable", "results": [], "warnings": [*warnings, "The requested strategies do not share an overlapping history window."]}
    results = []
    for key in common:
        values = common[key]
        curve = (1 + values).cumprod()
        results.append({
            "key": key, "label": key.replace("benchmark_", "").replace("_", " ").title(),
            **_metric(values),
            "curve": [{"date": index.date().isoformat(), "value": round(float(value), 4)} for index, value in curve.items()],
        })
    providers = sorted(set(frame["provider"].astype(str)))
    return {
        "version": BACKTEST_VERSION, "status": "ready", "results": results,
        "period": {"start": common.index.min().date().isoformat(), "end": common.index.max().date().isoformat(), "monthly_observations": len(common)},
        "lineage": [{"provider": "+".join(providers), "dataset": "corporate-action-adjusted daily prices resampled monthly", "symbols": symbols}],
        "assumptions": ["All strategies use the same overlapping monthly observations.", "SPY is always included when its stored history is available; a separately requested relevant benchmark is also included.", "The three-fund baseline is fixed at 60% VTI, 25% VXUS, and 15% BND.", "Historical performance is hypothetical and is not a forecast."],
        "warnings": warnings,
    }
