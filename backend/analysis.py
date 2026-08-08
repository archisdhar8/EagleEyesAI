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
from .quant import (
    REGIME_KEYS,
    SECTOR_PROXIES,
    dynamic_covariance,
    empirical_regime_returns,
    portfolio_path_metrics,
)
from .scenarios import refresh as refresh_scenarios


ROOT = Path(__file__).resolve().parents[1]
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

def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return default if math.isnan(result) else result
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def load_rankings() -> pd.DataFrame:
    if not RANKINGS_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(RANKINGS_PATH).drop_duplicates("ticker", keep="first")


def latest_macro() -> dict[str, Any]:
    if database.DATABASE_URL:
        observations = database.macro_observation_history(
            ["CPIAUCSL", "PCEPI", "UNRATE", "T10Y2Y", "BAMLH0A0HYM2", "FEDFUNDS"],
            limit_per_series=36,
        )
        by_series: dict[str, list[dict[str, Any]]] = {}
        for observation in observations:
            values = by_series.setdefault(observation["series_id"], [])
            if not any(item["date"] == observation["date"] for item in values):
                values.append(observation)
        latest = {key: values[0] for key, values in by_series.items() if values}
        if latest:
            inflation_values = by_series.get("CPIAUCSL") or by_series.get("PCEPI") or []
            inflation_yoy = None
            if len(inflation_values) >= 13 and _num(inflation_values[12]["value"]) > 0:
                inflation_yoy = (_num(inflation_values[0]["value"]) / _num(inflation_values[12]["value"]) - 1) * 100
            unemployment = _num(latest.get("UNRATE", {}).get("value"), 4.5)
            curve = _num(latest.get("T10Y2Y", {}).get("value"), 0)
            credit_spread = _num(latest.get("BAMLH0A0HYM2", {}).get("value"), 4.5)
            policy_rate = _num(latest.get("FEDFUNDS", {}).get("value"), 4.0)
            score = 50.0
            if inflation_yoy is not None:
                score += 8 if inflation_yoy <= 2.5 else -10 if inflation_yoy >= 3.5 else 0
            score += 8 if unemployment < 4.5 else -12 if unemployment >= 5.0 else 0
            score += 6 if curve >= 0 else -6
            score += 5 if credit_spread < 4.0 else -10 if credit_spread >= 6.0 else 0
            if inflation_yoy is not None and inflation_yoy >= 3.5:
                regime = "sticky_inflation"
            elif unemployment >= 5.0 or credit_spread >= 6.0:
                regime = "recession_risk"
            elif inflation_yoy is not None and inflation_yoy <= 2.8 and unemployment < 4.5 and curve >= 0:
                regime = "supportive_growth"
            else:
                regime = "neutral"
            as_of = max(item["date"] for item in latest.values())
            return {
                "regime": regime, "score": round(_clip(score), 1), "as_of": as_of,
                "source": "Supabase · FRED",
                "metrics": {
                    "inflation_yoy": None if inflation_yoy is None else round(inflation_yoy, 2),
                    "unemployment": round(unemployment, 2), "yield_curve": round(curve, 2),
                    "credit_spread": round(credit_spread, 2), "policy_rate": round(policy_rate, 2),
                },
            }
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
    stored = database.security_data(tickers) if database.DATABASE_URL else {
        "securities": [], "fundamentals": [], "prices": [], "news": []
    }
    stored_securities = {row["ticker"]: row for row in stored["securities"]}
    stored_fundamentals: dict[str, list[dict[str, Any]]] = {}
    stored_prices: dict[str, list[dict[str, Any]]] = {}
    stored_news: dict[str, list[dict[str, Any]]] = {}
    for row in stored["fundamentals"]:
        stored_fundamentals.setdefault(row["ticker"], []).append(row)
    for row in stored["prices"]:
        stored_prices.setdefault(row["ticker"], []).append(row)
    for row in stored["news"]:
        stored_news.setdefault(row["ticker"], []).append(row)
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
        security = stored_securities.get(ticker)
        fundamentals = stored_fundamentals.get(ticker, [])
        prices = stored_prices.get(ticker, [])
        news_items = stored_news.get(ticker, [])
        price = _num(prices[-1]["close"]) if prices else None
        price_change_1y = None
        if len(prices) >= 2 and _num(prices[max(0, len(prices) - 252)]["close"]) > 0:
            price_change_1y = price / _num(prices[max(0, len(prices) - 252)]["close"]) - 1
            technical = _clip(50 + price_change_1y * 65)
        revenue_growth = None
        latest_metrics = fundamentals[0].get("metrics", {}) if fundamentals else {}
        current_revenue = _num(latest_metrics.get("revenue"))
        comparable = next(
            (
                period for period in fundamentals[1:]
                if period.get("fiscal_period") == fundamentals[0].get("fiscal_period")
                and period.get("fiscal_year") != fundamentals[0].get("fiscal_year")
            ),
            fundamentals[1] if len(fundamentals) > 1 else None,
        ) if fundamentals else None
        prior_revenue = _num((comparable or {}).get("metrics", {}).get("revenue"))
        if current_revenue and prior_revenue:
            revenue_growth = current_revenue / prior_revenue - 1
            fundamental = _clip(fundamental * 0.65 + _clip(50 + revenue_growth * 140) * 0.35)
        net_income = _num(latest_metrics.get("net_income"))
        net_margin = net_income / current_revenue if current_revenue else None
        debt = _num(latest_metrics.get("total_debt"))
        assets = _num(latest_metrics.get("total_assets"))
        if net_margin is not None:
            fundamental = _clip(fundamental + max(-8, min(8, net_margin * 40)))
        if assets and debt / assets > 0.55:
            risks = list(dict.fromkeys([*risks, "elevated_balance_sheet_leverage"]))
            fundamental = _clip(fundamental - 7)
        sentiment_values = []
        for item in news_items:
            metadata = item.get("metadata") or {}
            sentiment_values.append(_num(metadata.get("sentiment_score")))
        if sentiment_values:
            news = _clip(50 + float(np.mean(sentiment_values)) * 35)
        growth = _clip(fundamental * 0.40 + industry_score * 0.25 + technical * 0.20 + news * 0.15)
        coverage = (30 if len(prices) >= 252 else 15 if prices else 0) + (30 if fundamentals else 0) + (20 if news_items else 0) + (10 if security else 0)
        if database.DATABASE_URL:
            confidence = _clip(confidence * 0.35 + coverage * 0.65)
            quality = "high" if confidence >= 80 else "medium" if confidence >= 60 else "low"
            if security:
                company = security.get("company_name") or company
                sector = security.get("sector") or sector
                industry = security.get("industry") or industry
        final = _clip(
            fundamental * 0.28 + valuation * 0.20 + industry_score * 0.14
            + technical * 0.18 + news * 0.10 + growth * 0.10
        ) if database.DATABASE_URL and (prices or fundamentals or news_items) else final
        expected_return = max(-0.03, min(0.18, 0.035 + (final - 50) * 0.0015 + (valuation - 50) * 0.0005))
        rows.append({
            "ticker": ticker, "company": company, "sector": sector, "industry": industry,
            "final_score": round(final, 1), "growth_rating": round(growth, 1), "valuation_score": round(valuation, 1),
            "fundamental_score": round(fundamental, 1), "industry_score": round(industry_score, 1),
            "technical_score": round(technical, 1), "news_score": round(news, 1), "confidence": round(confidence, 1),
            "data_quality": quality, "risk_flags": risks, "source": source, "expected_return": expected_return,
            "price": None if price is None else round(price, 2),
            "price_change_1y": None if price_change_1y is None else round(price_change_1y, 4),
            "price_as_of": prices[-1]["date"] if prices else None,
            "fundamentals_as_of": fundamentals[0]["period_end"] if fundamentals else None,
            "revenue_growth": None if revenue_growth is None else round(revenue_growth, 4),
            "net_margin": None if net_margin is None else round(net_margin, 4),
            "news_count": len(news_items),
            "latest_news": news_items[0] if news_items else None,
            "data_source": "supabase" if database.DATABASE_URL and (prices or fundamentals or news_items) else "local_fallback",
        })
    return rows


def _price_matrix(tickers: list[str], price_limit: int = 5000) -> pd.DataFrame:
    if database.DATABASE_URL:
        stored = database.price_history(tickers, limit_per_ticker=price_limit)
        if stored:
            frame = pd.DataFrame(stored)
            frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.date
            return frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()
    if not PRICES_PATH.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(PRICES_PATH, columns=["ticker", "date", "close"])
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame = frame[frame["ticker"].isin(tickers)]
    if frame.empty:
        return pd.DataFrame()
    return frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().tail(price_limit)


def _return_model(
    research: list[dict[str, Any]], scenarios: list[dict[str, Any]],
    prices: pd.DataFrame | None = None, labels: list[dict[str, Any]] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, float], dict[str, Any], dict[str, np.ndarray]]:
    tickers = [row["ticker"] for row in research]
    prices = prices if prices is not None else _price_matrix(tickers)
    returns = prices.pct_change(fill_method=None).dropna(how="all") if not prices.empty else pd.DataFrame()
    vol_by_ticker: dict[str, float] = {}
    for ticker in tickers:
        series = returns[ticker].dropna() if ticker in returns else pd.Series(dtype=float)
        vol_by_ticker[ticker] = float(series.std() * np.sqrt(252)) if len(series) >= 60 else (0.01 if ticker == "CASH" else 0.16 if ticker in ETF_META else 0.28)
    covariance_estimate = dynamic_covariance(returns, tickers, vol_by_ticker)
    regime_estimate = empirical_regime_returns(prices, labels or [], research)
    probabilities = {item["key"]: float(item["probability"]) for item in scenarios}
    probability_total = sum(probabilities.get(key, 0) for key in REGIME_KEYS) or 1.0
    empirical_expected = sum(
        regime_estimate.returns[key] * probabilities.get(key, 0) / probability_total
        for key in REGIME_KEYS
    )
    score_expected = np.array([row["expected_return"] * (0.55 + row["confidence"] / 200) for row in research])
    labelled_months = regime_estimate.diagnostics["labelled_forward_months"]
    empirical_weight = 0.0 if labelled_months == 0 else float(np.clip(labelled_months / 48, 0.45, 0.85))
    expected = empirical_expected * empirical_weight + score_expected * (1 - empirical_weight)
    diagnostics = {
        "covariance": covariance_estimate.diagnostics,
        "regime_returns": regime_estimate.diagnostics,
        "expected_return_blend": {
            "empirical_regime_weight": round(empirical_weight, 6),
            "company_research_weight": round(1 - empirical_weight, 6),
            "scenario_probability_source": "prediction markets with macro-prior fallback",
        },
    }
    return expected, covariance_estimate.matrix, vol_by_ticker, diagnostics, regime_estimate.returns


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


def _scenario_outcomes(
    weights: np.ndarray,
    scenarios: list[dict[str, Any]],
    regime_returns: dict[str, np.ndarray],
    regime_diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    outcomes = []
    for scenario in scenarios:
        state = regime_diagnostics.get("states", {}).get(scenario["key"], {})
        vector = regime_returns.get(scenario["key"], np.zeros(len(weights)))
        outcomes.append({
            "key": scenario["key"], "label": scenario["label"],
            "probability": scenario["probability"],
            "estimated_return": round(float(weights @ vector), 4),
            "sample_count": state.get("median_asset_samples", 0),
            "regime_months": state.get("regime_months", 0),
            "shrinkage": state.get("average_shrinkage", 1.0),
            "method": "Shrunk empirical next-month return",
        })
    return outcomes


def _probabilities_at(labels: list[dict[str, Any]], cutoff: pd.Timestamp) -> dict[str, float]:
    available = [item for item in labels if pd.Timestamp(item["as_of_date"]) <= cutoff]
    if not available:
        return {key: 1 / len(REGIME_KEYS) for key in REGIME_KEYS}
    latest = max(available, key=lambda item: item["as_of_date"])
    probabilities = {key: _num((latest.get("probabilities") or {}).get(key)) for key in REGIME_KEYS}
    total = sum(probabilities.values()) or 1.0
    return {key: value / total for key, value in probabilities.items()}


def _walk_forward(
    prices: pd.DataFrame,
    labels: list[dict[str, Any]],
    research: list[dict[str, Any]],
    profile: InvestorProfile,
    static_weights: np.ndarray,
    *,
    train_months: int = 24,
    test_months: int = 3,
) -> dict[str, Any]:
    tickers = [row["ticker"] for row in research]
    if prices.empty or len(prices) < 252 or not labels:
        return {
            "status": "insufficient_history", "periods": [], "period_count": 0,
            "benchmarks": [], "assumptions": [
                "At least one year of daily prices and point-in-time monthly regime labels are required."
            ],
        }
    frame = prices.reindex(columns=tickers).copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(None)
    daily = frame.pct_change(fill_method=None)
    if "CASH" in tickers:
        daily["CASH"] = 0.025 / 252
    start = frame.index.min() + pd.DateOffset(months=train_months)
    end = frame.index.max() - pd.DateOffset(months=test_months)
    if start > end:
        return {
            "status": "insufficient_history", "periods": [], "period_count": 0,
            "benchmarks": [], "assumptions": [f"At least {train_months + test_months} months of price history is required."],
        }
    cutoffs = pd.date_range(start=start, end=end, freq=f"{test_months}ME")
    model_parts: list[pd.Series] = []
    equal_parts: list[pd.Series] = []
    static_parts: list[pd.Series] = []
    periods: list[dict[str, Any]] = []
    prior_weights = np.full(len(tickers), 1 / max(len(tickers), 1))
    turnovers: list[float] = []
    static = static_weights.copy()
    if static.sum() <= 0:
        static = prior_weights.copy()
    else:
        static /= static.sum()
    for cutoff in cutoffs:
        train_prices = frame.loc[:cutoff]
        train_returns = daily.loc[:cutoff].tail(504)
        eligible = np.array([
            ticker == "CASH" or train_prices[ticker].count() >= 120
            for ticker in tickers
        ], dtype=bool)
        if eligible.sum() < 2:
            continue
        fallback_volatility = {
            ticker: float(train_returns[ticker].std() * np.sqrt(252))
            if train_returns[ticker].count() >= 60 else (0.01 if ticker == "CASH" else 0.25)
            for ticker in tickers
        }
        covariance = dynamic_covariance(train_returns, tickers, fallback_volatility).matrix
        regime = empirical_regime_returns(train_prices, labels, research, as_of=cutoff)
        probabilities = _probabilities_at(labels, cutoff)
        empirical = sum(regime.returns[key] * probabilities[key] for key in REGIME_KEYS)
        score_expected = np.array([
            row["expected_return"] * (0.55 + row["confidence"] / 200) for row in research
        ])
        labelled_months = regime.diagnostics["labelled_forward_months"]
        empirical_weight = 0.0 if labelled_months == 0 else float(np.clip(labelled_months / 48, 0.45, 0.85))
        expected = empirical * empirical_weight + score_expected * (1 - empirical_weight)
        adjusted_research = [dict(row) for row in research]
        for index, is_eligible in enumerate(eligible):
            if not is_eligible:
                adjusted_research[index]["confidence"] = 0
        weights, conflicts = _optimize(
            "Balanced", expected, covariance, prior_weights, adjusted_research, profile
        )
        if conflicts:
            continue
        test_start = cutoff + pd.Timedelta(days=1)
        test_end = cutoff + pd.DateOffset(months=test_months)
        realized = daily[(daily.index >= test_start) & (daily.index <= test_end)]
        if len(realized) < 20:
            continue
        equal_weights = eligible.astype(float) / eligible.sum()
        model_return = realized.fillna(0).mul(weights, axis=1).sum(axis=1)
        equal_return = realized.fillna(0).mul(equal_weights, axis=1).sum(axis=1)
        static_return = realized.fillna(0).mul(static, axis=1).sum(axis=1)
        turnover = float(np.abs(weights - prior_weights).sum() / 2)
        turnovers.append(turnover)
        model_parts.append(model_return)
        equal_parts.append(equal_return)
        static_parts.append(static_return)
        periods.append({
            "train_end": cutoff.date().isoformat(),
            "test_start": test_start.date().isoformat(),
            "test_end": min(test_end, realized.index.max()).date().isoformat(),
            "model_return": round(float((1 + model_return).prod() - 1), 6),
            "equal_weight_return": round(float((1 + equal_return).prod() - 1), 6),
            "static_return": round(float((1 + static_return).prod() - 1), 6),
            "turnover": round(turnover, 6),
            "eligible_assets": int(eligible.sum()),
            "regime_training_months": regime.diagnostics["labelled_forward_months"],
        })
        prior_weights = weights
    if not periods:
        return {
            "status": "insufficient_history", "periods": [], "period_count": 0,
            "benchmarks": [], "assumptions": ["No complete out-of-sample quarter passed coverage constraints."],
        }
    model_path = pd.concat(model_parts).sort_index()
    equal_path = pd.concat(equal_parts).sort_index()
    static_path = pd.concat(static_parts).sort_index()
    model_metrics = portfolio_path_metrics(model_path)
    equal_metrics = portfolio_path_metrics(equal_path)
    static_metrics = portfolio_path_metrics(static_path)
    model_metrics["average_turnover"] = round(float(np.mean(turnovers)), 6)
    model_metrics["quarters_beating_equal_weight"] = round(float(np.mean([
        item["model_return"] > item["equal_weight_return"] for item in periods
    ])), 6)
    model_metrics["quarters_beating_static"] = round(float(np.mean([
        item["model_return"] > item["static_return"] for item in periods
    ])), 6)
    return {
        "status": "complete", "period_count": len(periods), "periods": periods,
        "model": {"name": "Walk-forward Balanced", **model_metrics},
        "benchmarks": [
            {"name": "Equal weight", **equal_metrics},
            {"name": "Static current allocation", **static_metrics},
        ],
        "assumptions": [
            f"Expanding point-in-time regime window; trailing 504 trading days for covariance; {test_months}-month tests.",
            "Historical macro-regime probabilities stand in for unavailable historical prediction-market snapshots.",
            "Returns are evaluated before fees, spreads, taxes, and implementation delay.",
            "Equal weight is rebalanced each test quarter; static current allocation is not optimized.",
        ],
    }


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
    proxy_tickers = sorted(set(SECTOR_PROXIES.values()))
    price_tickers = list(dict.fromkeys([row["ticker"] for row in research] + proxy_tickers))
    prices = _price_matrix(price_tickers)
    labels = database.regime_history(limit=1000)
    expected, covariance, _, model_diagnostics, regime_returns = _return_model(
        research, scenarios, prices, labels
    )
    current, portfolio_value = _current_weights(holdings, research)
    walk_forward = _walk_forward(prices, labels, research, profile, current)
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
            "scenario_outcomes": _scenario_outcomes(
                weights, scenarios, regime_returns, model_diagnostics["regime_returns"]
            ),
            "projection": _projection(portfolio_value, exp_return, volatility, profile, 90210 + index),
            "tax": _tax_estimate(weights, current, research, holdings, portfolio_value, profile),
            "constraint_status": "infeasible" if conflicts else "satisfied", "conflicts": conflicts,
            "tradeoff": _tradeoff(label),
            "model_assumptions": [
                f"Expected return blends {model_diagnostics['expected_return_blend']['empirical_regime_weight']:.0%} empirical regime history with company research.",
                f"Covariance uses {model_diagnostics['covariance']['shrinkage_intensity']:.0%} shrinkage toward a constant-correlation target.",
                "Scenario outcomes are sample-size-shrunk historical next-month returns, not fixed sector shocks.",
                "Risk, return, drawdown, tax, and retirement figures are estimates rather than guarantees.",
            ],
        })
    run_id = str(uuid.uuid4())
    result = {
        "id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "model_version": "walk-forward-regime-shrinkage-v2",
        "macro": latest_macro(), "scenarios": scenarios, "scenario_warnings": scenario_payload["warnings"],
        "portfolio_value": round(portfolio_value, 2), "current_weights": {row["ticker"]: round(float(current[i]), 4) for i, row in enumerate(research) if current[i] > 0},
        "research": research, "alternatives": alternatives,
        "model_diagnostics": model_diagnostics, "walk_forward": walk_forward,
        "benchmarks": walk_forward.get("benchmarks", []),
        "warnings": [
            "Decision-support research only; no trades are submitted.",
            "Expected returns and projections are model estimates, not guarantees.",
            *(["Walk-forward validation is unavailable until more overlapping price and point-in-time regime history exists."] if walk_forward["status"] != "complete" else []),
        ],
        "data_lineage": {
            "research": "supabase" if database.DATABASE_URL else str(RANKINGS_PATH),
            "prices": "supabase.price_bars" if database.DATABASE_URL else str(PRICES_PATH),
            "macro": "supabase.macro_observations" if database.DATABASE_URL else str(MACRO_PATH),
            "regimes": "supabase.macro_regime_labels" if database.DATABASE_URL else "unavailable",
            "scenario_fetched_at": scenario_payload["fetched_at"],
        },
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
