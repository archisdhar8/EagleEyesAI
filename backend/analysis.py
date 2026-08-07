from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from . import database
from .models import InvestorProfile
from .scenarios import refresh as refresh_scenarios


ROOT = Path(__file__).resolve().parents[2]
RANKINGS_PATH = ROOT / "data" / "outputs" / "stock_rankings.csv"
PRICES_PATH = ROOT / "data" / "raw" / "polygon" / "prices_daily.parquet"
MACRO_PATH = ROOT / "data" / "processed" / "macro_features.parquet"

ETF_META = {
    "SPY": ("S&P 500 ETF", "Broad Market", "Large Blend"),
    "VTI": ("Total U.S. Market ETF", "Broad Market", "Total Market"),
    "QQQ": ("Nasdaq-100 ETF", "Broad Market", "Growth"),
    "IWM": ("Russell 2000 ETF", "Broad Market", "Small Cap"),
    "XLK": ("Technology Select Sector ETF", "Information Technology", "Sector ETF"),
    "XLV": ("Health Care Select Sector ETF", "Health Care", "Sector ETF"),
    "XLE": ("Energy Select Sector ETF", "Energy", "Sector ETF"),
    "XLF": ("Financial Select Sector ETF", "Financials", "Sector ETF"),
    "XLI": ("Industrial Select Sector ETF", "Industrials", "Sector ETF"),
    "TLT": ("20+ Year Treasury ETF", "Fixed Income", "Treasuries"),
    "BND": ("Total Bond Market ETF", "Fixed Income", "Aggregate Bonds"),
    "CASH": ("Cash reserve", "Cash", "Cash"),
}

SCENARIO_SECTOR_EFFECTS = {
    "soft_landing": {"Broad Market": 0.08, "Information Technology": 0.11, "Financials": 0.08, "Energy": 0.04, "Fixed Income": 0.03},
    "sticky_inflation": {"Broad Market": -0.01, "Information Technology": -0.05, "Financials": 0.02, "Energy": 0.11, "Fixed Income": -0.06},
    "recession_cuts": {"Broad Market": -0.08, "Information Technology": -0.05, "Financials": -0.12, "Energy": -0.10, "Health Care": 0.01, "Fixed Income": 0.10},
    "growth_reacceleration": {"Broad Market": 0.12, "Information Technology": 0.16, "Financials": 0.10, "Industrials": 0.13, "Energy": 0.09, "Fixed Income": -0.02},
    "oil_shock": {"Broad Market": -0.06, "Energy": 0.18, "Industrials": -0.05, "Consumer Discretionary": -0.09, "Fixed Income": 0.02},
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return default if math.isnan(result) else result
    except (TypeError, ValueError):
        return default


def load_rankings() -> pd.DataFrame:
    if not RANKINGS_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(RANKINGS_PATH).drop_duplicates("ticker", keep="first")


def latest_macro() -> dict[str, Any]:
    if not MACRO_PATH.exists():
        return {"regime": "neutral", "score": 50, "as_of": None}
    frame = pd.read_parquet(MACRO_PATH).sort_values("date")
    if frame.empty:
        return {"regime": "neutral", "score": 50, "as_of": None}
    row = frame.iloc[-1]
    return {"regime": str(row.get("macro_regime", "neutral")), "score": round(_num(row.get("macro_score"), 50), 1), "as_of": str(row.get("date"))}


def security_research(tickers: list[str]) -> list[dict[str, Any]]:
    rankings = load_rankings()
    indexed = rankings.set_index(rankings["ticker"].astype(str).str.upper()) if not rankings.empty else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for ticker in dict.fromkeys(t.upper() for t in tickers):
        if not rankings.empty and ticker in indexed.index:
            row = indexed.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            final = _num(row.get("final_score"), 50)
            fundamental = _num(row.get("fundamental_score"), 50)
            valuation = _num(row.get("valuation_score"), 50)
            industry_score = _num(row.get("industry_score"), 50)
            technical = _num(row.get("technical_score"), 50)
            news = _num(row.get("news_score"), 50)
            confidence = _num(row.get("confidence_score"), 50)
            company = str(row.get("company_name") or ticker)
            sector = str(row.get("sector") or "Unclassified")
            industry = str(row.get("industry") or "Unclassified")
            risks = [] if str(row.get("risk_flags", "none")) == "none" else str(row.get("risk_flags", "")).split(";")
            quality = "high" if confidence >= 80 else "medium" if confidence >= 60 else "low"
            source = str(row.get("source_url") or row.get("news_url") or "")
        else:
            company, sector, industry = ETF_META.get(ticker, (ticker, "Unclassified", "Unclassified"))
            final = fundamental = valuation = industry_score = technical = news = 55 if ticker in ETF_META else 45
            confidence = 70 if ticker in ETF_META else 30
            risks = [] if ticker in ETF_META else ["limited_research_coverage"]
            quality = "medium" if ticker in ETF_META else "low"
            source = ""
        growth = max(0.0, min(100.0, fundamental * 0.40 + industry_score * 0.25 + technical * 0.20 + news * 0.15))
        expected_return = max(-0.03, min(0.18, 0.035 + (final - 50) * 0.0015 + (valuation - 50) * 0.0005))
        rows.append({
            "ticker": ticker, "company": company, "sector": sector, "industry": industry,
            "final_score": round(final, 1), "growth_rating": round(growth, 1), "valuation_score": round(valuation, 1),
            "fundamental_score": round(fundamental, 1), "industry_score": round(industry_score, 1),
            "technical_score": round(technical, 1), "news_score": round(news, 1), "confidence": round(confidence, 1),
            "data_quality": quality, "risk_flags": risks, "source": source, "expected_return": expected_return,
        })
    return rows


def _price_matrix(tickers: list[str]) -> pd.DataFrame:
    if not PRICES_PATH.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(PRICES_PATH, columns=["ticker", "date", "close"])
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame = frame[frame["ticker"].isin(tickers)]
    if frame.empty:
        return pd.DataFrame()
    return frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().tail(756)


def _return_model(research: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    tickers = [row["ticker"] for row in research]
    prices = _price_matrix(tickers)
    returns = prices.pct_change(fill_method=None).dropna(how="all") if not prices.empty else pd.DataFrame()
    vol_by_ticker: dict[str, float] = {}
    covariance = np.zeros((len(tickers), len(tickers)))
    for i, ticker in enumerate(tickers):
        series = returns[ticker].dropna() if ticker in returns else pd.Series(dtype=float)
        vol_by_ticker[ticker] = float(series.std() * np.sqrt(252)) if len(series) >= 60 else (0.01 if ticker == "CASH" else 0.16 if ticker in ETF_META else 0.28)
    if not returns.empty:
        raw = returns.reindex(columns=tickers).cov(min_periods=60).fillna(0).to_numpy() * 252
        diagonal = np.diag([vol_by_ticker[t] ** 2 for t in tickers])
        covariance = raw * 0.65 + diagonal * 0.35
    else:
        covariance = np.diag([vol_by_ticker[t] ** 2 for t in tickers])
    covariance += np.eye(len(tickers)) * 1e-6
    scenario_expected = []
    for row in research:
        value = 0.0
        for scenario in scenarios:
            effects = SCENARIO_SECTOR_EFFECTS.get(scenario["key"], {})
            sector_return = effects.get(row["sector"], effects.get("Broad Market", 0.0))
            if row["ticker"] == "CASH":
                sector_return = 0.025
            value += float(scenario["probability"]) * sector_return
        scenario_expected.append(value)
    score_expected = np.array([row["expected_return"] * (0.55 + row["confidence"] / 200) for row in research])
    expected = score_expected * 0.55 + np.array(scenario_expected) * 0.45
    return expected, covariance, vol_by_ticker


def _current_weights(holdings: list[dict[str, Any]], research: list[dict[str, Any]]) -> tuple[np.ndarray, float]:
    tickers = [row["ticker"] for row in research]
    values: dict[str, float] = {}
    explicit_weight = False
    for holding in holdings:
        ticker = holding["ticker"].upper()
        if holding.get("weight") is not None:
            values[ticker] = _num(holding["weight"])
            explicit_weight = True
        elif holding.get("market_value") is not None:
            values[ticker] = _num(holding["market_value"])
    if not values:
        for holding in holdings:
            values[holding["ticker"].upper()] = _num(holding.get("shares"), 0)
    total = sum(values.values()) or 1.0
    weights = np.array([values.get(ticker, 0.0) / total for ticker in tickers])
    if explicit_weight and weights.sum() > 0:
        weights /= weights.sum()
    portfolio_value = sum(_num(h.get("market_value")) for h in holdings)
    return weights, portfolio_value


def _optimize(label: str, expected: np.ndarray, covariance: np.ndarray, current: np.ndarray, research: list[dict[str, Any]], profile: InvestorProfile) -> tuple[np.ndarray, list[str]]:
    n = len(expected)
    if n == 0:
        return np.array([]), ["No eligible securities"]
    sliders = profile.objectives
    if label == "Risk-Controlled":
        return_weight, risk_weight, turnover_weight = 0.35, 1.35, 0.30
    elif label == "Goal-Tilted":
        return_weight = 0.75 + sliders.expected_return
        risk_weight = 0.35 + sliders.volatility * 0.45 + sliders.drawdown * 0.35
        turnover_weight = 0.08 + sliders.turnover * 0.15
    else:
        return_weight = 0.55 + sliders.expected_return * 0.45
        risk_weight = 0.65 + sliders.volatility * 0.45 + sliders.drawdown * 0.25
        turnover_weight = 0.12 + sliders.turnover * 0.22
    if profile.preset == "growth":
        return_weight += 0.25
        risk_weight = max(0.25, risk_weight - 0.15)
    elif profile.preset == "preservation":
        return_weight = max(0.25, return_weight - 0.10)
        risk_weight += 0.35
    risk_weight *= 0.75 + (11 - profile.risk_tolerance) * 0.05
    tax_penalties = np.zeros(n)
    if profile.account_type == "taxable":
        tax_penalties = current * profile.tax_rate * sliders.tax_drag * 0.02

    income_scores = np.array([
        0.03 if row["ticker"] == "CASH" else 0.045 if row["sector"] == "Fixed Income" else 0.03 if row["sector"] == "Energy" else 0.015
        for row in research
    ])

    def objective(weights: np.ndarray) -> float:
        variance = float(weights @ covariance @ weights)
        turnover = float(np.sqrt((weights - current) ** 2 + 1e-8).sum())
        concentration = float((weights**2).sum())
        return (
            -return_weight * float(expected @ weights)
            - (sliders.income + (0.35 if profile.preset == "income" else 0.0)) * float(income_scores @ weights) * 0.35
            + risk_weight * variance
            + turnover_weight * turnover * 0.015
            + sliders.diversification * concentration * 0.025
            + float(tax_penalties @ np.maximum(current - weights, 0))
        )

    constraints: list[dict[str, Any]] = [{"type": "eq", "fun": lambda w: float(w.sum() - 1.0)}]
    sectors = sorted({row["sector"] for row in research if row["sector"] not in {"Broad Market", "Fixed Income"}})
    for sector in sectors:
        indexes = [i for i, row in enumerate(research) if row["sector"] == sector]
        constraints.append({"type": "ineq", "fun": lambda w, idx=indexes: float(0.35 - w[idx].sum())})
    industries = sorted({row["industry"] for row in research if row["industry"] not in {"Sector ETF", "Total Market", "Large Blend", "Growth", "Cash"}})
    for industry in industries:
        indexes = [i for i, row in enumerate(research) if row["industry"] == industry]
        constraints.append({"type": "ineq", "fun": lambda w, idx=indexes: float(0.25 - w[idx].sum())})
    restrictions = {item.upper().strip() for item in profile.restrictions}
    bounds = []
    for row in research:
        maximum = 0.45 if row["ticker"] in ETF_META and row["sector"] in {"Broad Market", "Fixed Income"} else 0.18
        minimum = 0.10 if row["ticker"] == "CASH" and profile.preset == "preservation" else 0.03 if row["ticker"] == "CASH" else 0.0
        if row["confidence"] < 40 and row["ticker"] != "CASH":
            maximum = min(maximum, 0.03)
        if row["ticker"] in restrictions or row["sector"].upper() in restrictions:
            minimum = maximum = 0.0
        bounds.append((minimum, maximum))
    start = current.copy()
    if start.sum() <= 0 or any(start[i] > bounds[i][1] for i in range(n)):
        start = np.array([max(bound[0], min(1 / n, bound[1])) for bound in bounds])
        remaining = 1 - start.sum()
        for i, bound in enumerate(bounds):
            room = bound[1] - start[i]
            add = min(max(room, 0), max(remaining, 0))
            start[i] += add
            remaining -= add
    result = minimize(objective, start, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 500, "ftol": 1e-9})
    if not result.success:
        return current, [f"Constraints are infeasible: {result.message}"]
    weights = np.maximum(result.x, 0)
    weights /= weights.sum()
    return weights, []


def _scenario_outcomes(weights: np.ndarray, research: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcomes = []
    for scenario in scenarios:
        returns = []
        for row in research:
            sector_effects = SCENARIO_SECTOR_EFFECTS.get(scenario["key"], {})
            scenario_return = 0.025 if row["ticker"] == "CASH" else sector_effects.get(row["sector"], sector_effects.get("Broad Market", 0.0))
            returns.append(scenario_return + (row["final_score"] - 50) * 0.0003)
        outcomes.append({"key": scenario["key"], "label": scenario["label"], "probability": scenario["probability"], "estimated_return": round(float(weights @ np.array(returns)), 4)})
    return outcomes


def _projection(value: float, expected_return: float, volatility: float, profile: InvestorProfile, seed: int) -> dict[str, Any]:
    value = value or 100_000
    rng = np.random.default_rng(seed)
    paths = np.full(2500, value, dtype=float)
    for _ in range(profile.horizon_years):
        annual = rng.normal(expected_return, volatility, len(paths))
        paths = np.maximum(0, paths * (1 + annual) + profile.annual_contribution - profile.annual_withdrawal)
    real_paths = paths / (1.025**profile.horizon_years)
    return {
        "nominal_p10": round(float(np.percentile(paths, 10))), "nominal_p50": round(float(np.percentile(paths, 50))), "nominal_p90": round(float(np.percentile(paths, 90))),
        "real_p50": round(float(np.percentile(real_paths, 50))), "goal_probability": round(float((paths >= profile.target_value).mean()), 3),
        "assumptions": "2,500 seeded annual paths; 2.5% inflation; estimates are not guarantees.",
    }


def _tax_estimate(weights: np.ndarray, current: np.ndarray, research: list[dict[str, Any]], holdings: list[dict[str, Any]], portfolio_value: float, profile: InvestorProfile) -> dict[str, Any]:
    if profile.account_type != "taxable":
        return {"available": True, "estimated_realized_gain": 0, "estimated_tax": 0, "note": "Tax-deferred or tax-free account selected."}
    holding_map = {h["ticker"].upper(): h for h in holdings}
    if portfolio_value <= 0 or any(holding_map.get(row["ticker"], {}).get("cost_basis") is None for i, row in enumerate(research) if current[i] > weights[i] + 0.001):
        return {"available": False, "estimated_realized_gain": None, "estimated_tax": None, "note": "Add market values and aggregate cost basis to estimate taxable gains."}
    realized = 0.0
    for i, row in enumerate(research):
        sold_weight = max(0.0, current[i] - weights[i])
        holding = holding_map.get(row["ticker"], {})
        market_value = _num(holding.get("market_value"))
        cost_basis = _num(holding.get("cost_basis"))
        gain_ratio = max(0.0, (market_value - cost_basis) / market_value) if market_value else 0.0
        realized += sold_weight * portfolio_value * gain_ratio
    return {"available": True, "estimated_realized_gain": round(realized), "estimated_tax": round(realized * profile.tax_rate), "note": "Aggregate estimate only; no tax-lot or wash-sale handling."}


def run_analysis(holdings: list[dict[str, Any]], profile: InvestorProfile) -> dict[str, Any]:
    scenario_payload = refresh_scenarios(force=False)
    scenarios = scenario_payload["scenarios"]
    tickers = [h["ticker"].upper() for h in holdings]
    tickers.extend(t.upper() for t in profile.watchlist)
    if not any(ticker in ETF_META and ETF_META[ticker][1] == "Broad Market" for ticker in tickers):
        tickers.append("VTI")
    research = security_research(list(dict.fromkeys(tickers))[:50])
    expected, covariance, _ = _return_model(research, scenarios)
    current, portfolio_value = _current_weights(holdings, research)
    alternatives = []
    for index, label in enumerate(["Risk-Controlled", "Balanced", "Goal-Tilted"]):
        weights, conflicts = _optimize(label, expected, covariance, current, research, profile)
        exp_return = float(expected @ weights) if len(weights) else 0.0
        volatility = float(np.sqrt(max(0, weights @ covariance @ weights))) if len(weights) else 0.0
        allocations = []
        for i, row in enumerate(research):
            if weights[i] < 0.002 and current[i] < 0.002:
                continue
            target = float(weights[i])
            band = max(0.01, target * 0.12)
            allocations.append({
                "ticker": row["ticker"], "company": row["company"], "sector": row["sector"],
                "current_weight": round(float(current[i]), 4), "target_weight": round(target, 4),
                "target_min": round(max(0, target - band), 4), "target_max": round(min(1, target + band), 4),
                "delta": round(target - float(current[i]), 4), "reason": _allocation_reason(label, row, target - float(current[i])),
            })
        turnover = float(np.abs(weights - current).sum() / 2) if len(weights) else 0.0
        alternatives.append({
            "name": label, "expected_return": round(exp_return, 4), "volatility": round(volatility, 4),
            "drawdown_range": [round(-volatility * 2.2, 4), round(-volatility * 1.2, 4)],
            "turnover": round(turnover, 4), "effective_holdings": round(1 / max(float((weights**2).sum()), 1e-9), 1),
            "allocations": sorted(allocations, key=lambda item: item["target_weight"], reverse=True),
            "scenario_outcomes": _scenario_outcomes(weights, research, scenarios),
            "projection": _projection(portfolio_value, exp_return, volatility, profile, 90210 + index),
            "tax": _tax_estimate(weights, current, research, holdings, portfolio_value, profile),
            "constraint_status": "infeasible" if conflicts else "satisfied", "conflicts": conflicts,
            "tradeoff": _tradeoff(label),
        })
    run_id = str(uuid.uuid4())
    result = {
        "id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "model_version": "scenario-shrinkage-v1",
        "macro": latest_macro(), "scenarios": scenarios, "scenario_warnings": scenario_payload["warnings"],
        "portfolio_value": round(portfolio_value, 2), "current_weights": {row["ticker"]: round(float(current[i]), 4) for i, row in enumerate(research) if current[i] > 0},
        "research": research, "alternatives": alternatives,
        "warnings": ["Decision-support research only; no trades are submitted.", "Expected returns and projections are model estimates, not guarantees."],
        "data_lineage": {"rankings": str(RANKINGS_PATH), "prices": str(PRICES_PATH), "scenario_fetched_at": scenario_payload["fetched_at"]},
    }
    return result


def _allocation_reason(label: str, row: dict[str, Any], delta: float) -> str:
    direction = "Increase" if delta > 0.005 else "Reduce" if delta < -0.005 else "Maintain"
    if label == "Risk-Controlled":
        return f"{direction}: balances {row['confidence']:.0f}% research confidence with diversification and downside control."
    if label == "Goal-Tilted":
        return f"{direction}: goal tilt reflects growth {row['growth_rating']:.0f} and valuation {row['valuation_score']:.0f}."
    return f"{direction}: composite score {row['final_score']:.0f} with {row['data_quality']} data quality."


def _tradeoff(label: str) -> str:
    return {
        "Risk-Controlled": "Lower concentration and modeled downside, with less participation if growth assets lead.",
        "Balanced": "Balances modeled return, risk, turnover, taxes, and diversification using your selected priorities.",
        "Goal-Tilted": "More exposure to the strongest goal-aligned signals, with higher estimation and concentration risk.",
    }[label]
