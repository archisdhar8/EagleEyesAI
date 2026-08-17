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
from .ml_regime import evaluate_regime_classifier
from .models import InvestorProfile
from .quant import (
    REGIME_KEYS,
    SECTOR_PROXIES,
    dynamic_covariance,
    empirical_regime_returns,
    portfolio_path_metrics,
)
from .scenarios import refresh as refresh_scenarios
from .portfolio_eligibility import equity_analysis_holdings


ROOT = Path(__file__).resolve().parents[1]
RANKINGS_PATH = ROOT / "data" / "outputs" / "stock_rankings.csv"
PRICES_PATH = ROOT / "data" / "raw" / "polygon" / "prices_daily.parquet"
MACRO_PATH = ROOT / "data" / "processed" / "macro_features.parquet"

ETF_META = {
    "SPY": ("S&P 500 ETF", "Broad Market", "Large Blend"),
    "VTI": ("Total U.S. Market ETF", "Broad Market", "Total Market"),
    "QQQ": ("Nasdaq-100 ETF", "Broad Market", "Growth"),
    "ARKK": ("ARK Innovation ETF", "Broad Market", "Active Growth ETF"),
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


def _valuation_evidence(
    *,
    imported_score: float | None,
    price: float | None,
    metrics: dict[str, Any],
    fiscal_period: str | None,
) -> dict[str, Any]:
    """Build an auditable valuation signal from available point-in-time inputs.

    The score is only a relative research input. It is deliberately not a DCF,
    fair-value estimate, or price target.
    """
    if imported_score is not None:
        return {
            "status": "available",
            "score": round(imported_score, 1),
            "source": "imported research ranking",
            "method": "legacy-valuation-ranking-v1",
            "raw_metrics": {},
            "components": [{"metric": "Imported valuation evidence", "value": round(imported_score, 1), "score_effect": 0}],
            "formula": "The upstream ranking's valuation component is preserved without recomputation.",
            "limitations": ["The current local dataset does not contain the upstream model's raw multiple inputs."],
        }

    current_price = price if price and price > 0 else None
    shares = _num(metrics.get("shares_diluted")) or None
    revenue = _num(metrics.get("revenue")) or None
    eps = _num(metrics.get("eps_diluted")) or None
    free_cash_flow = _num(metrics.get("free_cash_flow")) or None
    annualizer = 1 if str(fiscal_period or "").upper() == "FY" else 4
    market_cap = current_price * shares if current_price and shares else None
    pe = current_price / (eps * annualizer) if current_price and eps and eps > 0 else None
    price_to_sales = market_cap / (revenue * annualizer) if market_cap and revenue and revenue > 0 else None
    fcf_yield = (free_cash_flow * annualizer) / market_cap if market_cap and free_cash_flow is not None else None

    score, components = 50.0, []
    if pe is not None:
        effect = 15 if pe <= 15 else 7 if pe <= 25 else -3 if pe <= 40 else -12
        score += effect
        components.append({"metric": "Price / earnings", "value": round(pe, 2), "score_effect": effect})
    elif eps is not None and eps <= 0:
        score -= 15
        components.append({"metric": "Price / earnings", "value": None, "score_effect": -15, "reason": "Earnings were not positive."})
    if price_to_sales is not None:
        effect = 10 if price_to_sales <= 3 else 0 if price_to_sales <= 8 else -10
        score += effect
        components.append({"metric": "Price / sales", "value": round(price_to_sales, 2), "score_effect": effect})
    if fcf_yield is not None:
        effect = 12 if fcf_yield >= .05 else 5 if fcf_yield >= .02 else -12 if fcf_yield < 0 else -3
        score += effect
        components.append({"metric": "Free-cash-flow yield", "value": round(fcf_yield, 4), "score_effect": effect})

    missing = []
    if current_price is None:
        missing.append("current adjusted closing price")
    if shares is None:
        missing.append("diluted share count")
    if revenue is None:
        missing.append("revenue")
    if eps is None:
        missing.append("diluted EPS")
    if free_cash_flow is None:
        missing.append("free cash flow")
    available = len(components) >= 2
    return {
        "status": "available" if available else "insufficient",
        "score": round(_clip(score), 1) if available else None,
        "source": "adjusted prices plus SEC Company Facts" if components else "no usable valuation inputs",
        "method": "transparent-multiples-v1",
        "raw_metrics": {
            "price": None if current_price is None else round(current_price, 2),
            "market_cap_proxy": None if market_cap is None else round(market_cap, 2),
            "pe": None if pe is None else round(pe, 2),
            "price_to_sales": None if price_to_sales is None else round(price_to_sales, 2),
            "free_cash_flow_yield": None if fcf_yield is None else round(fcf_yield, 4),
            "annualization_factor": annualizer,
        },
        "components": components,
        "formula": "Start at 50; add threshold adjustments for P/E, price-to-sales, and free-cash-flow yield; clamp to 0–100.",
        "thresholds": {
            "pe": "≤15: +15; ≤25: +7; ≤40: −3; >40: −12; non-positive earnings: −15",
            "price_to_sales": "≤3: +10; ≤8: 0; >8: −10",
            "free_cash_flow_yield": "≥5%: +12; ≥2%: +5; 0–2%: −3; negative: −12",
        },
        "missing_inputs": missing,
        "limitations": [
            "Quarterly figures are annualized mechanically when the latest period is not FY.",
            "This does not estimate intrinsic value, forecast growth, or produce a price target.",
        ],
    }

def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return default if math.isnan(result) else result
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _security_market_statistics(prices: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate familiar, auditable market statistics from adjusted closes."""
    if not prices:
        return {"status": "unavailable", "reason": "No adjusted daily price history is stored."}
    frame = pd.DataFrame(prices).copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        return {"status": "unavailable", "reason": "Stored daily rows contain no usable adjusted closes."}
    returns = close.pct_change(fill_method=None).dropna()

    def period_return(sessions: int) -> float | None:
        if len(close) <= sessions or float(close.iloc[-1 - sessions]) <= 0:
            return None
        return float(close.iloc[-1] / close.iloc[-1 - sessions] - 1)

    delta = close.diff()
    gains = delta.clip(lower=0).tail(14).mean()
    losses = -delta.clip(upper=0).tail(14).mean()
    rsi = None
    if len(delta.dropna()) >= 14:
        rsi = 100.0 if losses <= 1e-12 else 100 - 100 / (1 + gains / losses)
    wealth = (1 + returns).cumprod() if not returns.empty else pd.Series(dtype=float)
    years = len(returns) / 252
    annualized_return = float(wealth.iloc[-1] ** (1 / years) - 1) if years > 0 and not wealth.empty and wealth.iloc[-1] > 0 else None
    volatility = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else None
    max_drawdown = float((wealth / wealth.cummax() - 1).min()) if not wealth.empty else None
    sharpe = annualized_return / volatility if annualized_return is not None and volatility and volatility > 1e-12 else None
    sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    trailing = close.tail(252)
    volume = pd.to_numeric(frame.get("volume"), errors="coerce") if "volume" in frame else pd.Series(dtype=float)
    return {
        "status": "available", "method": "adjusted-price-statistics-v1",
        "observations": int(len(close)), "start_date": frame.iloc[0]["date"].date().isoformat(),
        "end_date": frame.iloc[-1]["date"].date().isoformat(), "last_price": round(float(close.iloc[-1]), 4),
        "return_1d": period_return(1), "return_1m": period_return(21), "return_3m": period_return(63),
        "return_1y": period_return(252), "annualized_return": annualized_return,
        "annualized_volatility": volatility, "sharpe_ratio": sharpe, "max_drawdown": max_drawdown,
        "rsi_14": None if rsi is None else float(rsi), "sma_50": sma_50, "sma_200": sma_200,
        "high_52w": float(trailing.max()), "low_52w": float(trailing.min()),
        "latest_volume": None if volume.empty or pd.isna(volume.iloc[-1]) else float(volume.iloc[-1]),
        "average_volume_20d": None if volume.dropna().empty else float(volume.tail(20).mean()),
        "assumptions": [
            "Prices use the provider's corporate-action-adjusted daily close where available.",
            "Sharpe ratio uses a 0% risk-free-rate assumption and the available stored history.",
            "RSI uses the latest 14 daily close-to-close changes.",
        ],
    }


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


def macro_factor_dashboard() -> dict[str, Any]:
    """Return the five primary macro transmission channels with dated evidence.

    Change is an observed-data trend, not a consensus surprise. The distinction is
    explicit because FRED does not provide release-consensus expectations.
    """
    definitions = {
        "rates": {"label": "Interest rates", "series": ["FEDFUNDS", "DGS10", "T10Y2Y"], "why": "Discount rates, borrowing costs, and valuation multiples."},
        "inflation": {"label": "Inflation", "series": ["CPIAUCSL", "PCEPI"], "why": "Policy expectations, purchasing power, and company margins."},
        "growth": {"label": "Economic growth", "series": ["INDPRO", "RSAFS", "PCE"], "why": "Revenue growth and forward earnings expectations."},
        "labor": {"label": "Labor market", "series": ["UNRATE", "PAYEMS", "ICSA"], "why": "Consumer demand, wage pressure, and recession risk."},
        "credit": {"label": "Credit conditions", "series": ["BAMLH0A0HYM2", "DRCCLACBS", "TOTALSL"], "why": "Financing availability and balance-sheet stress."},
    }
    series_ids = list(dict.fromkeys(series for item in definitions.values() for series in item["series"]))
    history = database.macro_observation_history(series_ids, limit_per_series=14) if database.DATABASE_URL else []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in history:
        if not any(item["date"] == row["date"] for item in grouped.setdefault(row["series_id"], [])):
            grouped[row["series_id"]].append(row)
    factors = []
    for key, definition in definitions.items():
        evidence = []
        for series in definition["series"]:
            values = grouped.get(series, [])
            if not values:
                continue
            latest, previous = values[0], values[1] if len(values) > 1 else None
            change = None if previous is None else _num(latest["value"]) - _num(previous["value"])
            evidence.append({
                "series_id": series, "value": _num(latest["value"]), "date": latest["date"],
                "change": None if change is None else round(change, 4),
                "source": f"https://fred.stlouisfed.org/series/{series}",
            })
        factors.append({
            "key": key, "label": definition["label"], "priority": "primary",
            "why_it_matters": definition["why"], "evidence": evidence,
            "as_of": max((item["date"] for item in evidence), default=None),
            "expectation_surprise": None,
            "assumption": "Observed change only; consensus-surprise data is not connected yet.",
        })
    return {
        "factors": factors,
        "framework": "Stock price ≈ expected future earnings ÷ required return",
        "secondary_factors": ["Consumer spending", "Fiscal policy", "Currency", "Commodities", "Global growth", "Geopolitical risk"],
    }


def security_research(tickers: list[str]) -> list[dict[str, Any]]:
    rankings = load_rankings()
    indexed = rankings.set_index(rankings["ticker"].astype(str).str.upper()) if not rankings.empty else pd.DataFrame()
    stored = database.security_data(tickers) if database.DATABASE_URL else {
        "securities": [], "fundamentals": [], "prices": [], "news": [], "company_markets": []
    }
    stored_securities = {row["ticker"]: row for row in stored["securities"]}
    stored_fundamentals: dict[str, list[dict[str, Any]]] = {}
    stored_prices: dict[str, list[dict[str, Any]]] = {}
    stored_news: dict[str, list[dict[str, Any]]] = {}
    stored_company_markets: dict[str, list[dict[str, Any]]] = {}
    for row in stored["fundamentals"]:
        stored_fundamentals.setdefault(row["ticker"], []).append(row)
    for row in stored["prices"]:
        stored_prices.setdefault(row["ticker"], []).append(row)
    for row in stored["news"]:
        stored_news.setdefault(row["ticker"], []).append(row)
    for row in stored.get("company_markets", []):
        stored_company_markets.setdefault(row["ticker"], []).append(row)
    rows: list[dict[str, Any]] = []
    for ticker in dict.fromkeys(t.upper() for t in tickers):
        component_coverage = {
            "growth": False, "valuation": False, "business_quality": False,
            "industry_position": False, "price_behavior": False, "news": False,
        }
        if not rankings.empty and ticker in indexed.index:
            row = indexed.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            final = _num(row.get("final_score"), 50)
            fundamental = _num(row.get("fundamental_score"), 50)
            imported_valuation = _num(row.get("valuation_score"), 50)
            valuation = imported_valuation
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
            component_coverage = {key: True for key in component_coverage}
        else:
            company, sector, industry = ETF_META.get(ticker, (ticker, "Unclassified", "Unclassified"))
            final = fundamental = valuation = industry_score = technical = news = 55 if ticker in ETF_META else 45
            imported_valuation = None
            confidence = 70 if ticker in ETF_META else 30
            risks = [] if ticker in ETF_META else ["limited_research_coverage"]
            quality = "medium" if ticker in ETF_META else "low"
            source = ""
        security = stored_securities.get(ticker)
        fundamentals = stored_fundamentals.get(ticker, [])
        prices = stored_prices.get(ticker, [])
        news_items = stored_news.get(ticker, [])
        company_markets = stored_company_markets.get(ticker, [])[:5]
        price = _num(prices[-1]["close"]) if prices else None
        price_change_1y = None
        if len(prices) >= 2 and _num(prices[max(0, len(prices) - 252)]["close"]) > 0:
            price_change_1y = price / _num(prices[max(0, len(prices) - 252)]["close"]) - 1
            technical = _clip(50 + price_change_1y * 65)
            component_coverage["price_behavior"] = True
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
            component_coverage["growth"] = True
        net_income = _num(latest_metrics.get("net_income"))
        net_margin = net_income / current_revenue if current_revenue else None
        debt = _num(latest_metrics.get("total_debt"))
        assets = _num(latest_metrics.get("total_assets"))
        if net_margin is not None:
            fundamental = _clip(fundamental + max(-8, min(8, net_margin * 40)))
            component_coverage["business_quality"] = True
        if assets and debt / assets > 0.55:
            risks = list(dict.fromkeys([*risks, "elevated_balance_sheet_leverage"]))
            fundamental = _clip(fundamental - 7)
        valuation_evidence = _valuation_evidence(
            imported_score=imported_valuation,
            price=price,
            metrics=latest_metrics,
            fiscal_period=fundamentals[0].get("fiscal_period") if fundamentals else None,
        )
        if valuation_evidence.get("score") is not None:
            valuation = _num(valuation_evidence["score"], valuation)
            component_coverage["valuation"] = True
        sentiment_values = []
        for item in news_items:
            metadata = item.get("metadata") or {}
            sentiment_values.append(_num(metadata.get("sentiment_score")))
        if sentiment_values:
            news = _clip(50 + float(np.mean(sentiment_values)) * 35)
            component_coverage["news"] = True
        mean_sentiment = float(np.mean(sentiment_values)) if sentiment_values else None
        sentiment_label = (
            "positive" if mean_sentiment is not None and mean_sentiment >= .15 else
            "negative" if mean_sentiment is not None and mean_sentiment <= -.15 else
            "mixed / neutral" if mean_sentiment is not None else "unavailable"
        )
        market_statistics = _security_market_statistics(prices)
        if security and (security.get("industry") or security.get("sector")):
            component_coverage["industry_position"] = True
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
            "valuation_evidence": valuation_evidence,
            "market_statistics": market_statistics,
            "fundamental_statistics": {
                "revenue": latest_metrics.get("revenue"), "net_income": latest_metrics.get("net_income"),
                "eps_diluted": latest_metrics.get("eps_diluted"), "free_cash_flow": latest_metrics.get("free_cash_flow"),
                "total_assets": latest_metrics.get("total_assets"), "total_debt": latest_metrics.get("total_debt"),
                "shares_diluted": latest_metrics.get("shares_diluted"),
                "net_margin": None if net_margin is None else round(net_margin, 6),
                "debt_to_assets": round(debt / assets, 6) if assets else None,
                "period_end": fundamentals[0].get("period_end") if fundamentals else None,
                "fiscal_period": fundamentals[0].get("fiscal_period") if fundamentals else None,
                "source": fundamentals[0].get("source_url") if fundamentals else None,
            },
            "news_sentiment": {
                "label": sentiment_label, "mean_score": mean_sentiment,
                "article_count": len(sentiment_values),
                "latest_published_at": news_items[0].get("published_at") if news_items else None,
                "method": "Mean stored provider article-sentiment score; descriptive and coverage-dependent.",
            },
            "news_count": len(news_items),
            "latest_news": news_items[0] if news_items else None,
            "prediction_markets": company_markets,
            "component_coverage": component_coverage,
            "data_source": "supabase" if database.DATABASE_URL and (prices or fundamentals or news_items or company_markets) else "local_fallback",
        })
    return rows


def _price_matrix(tickers: list[str], price_limit: int = 5000) -> pd.DataFrame:
    if database.DATABASE_URL:
        stored = database.price_history(tickers, limit_per_ticker=price_limit)
        if stored:
            frame = pd.DataFrame(stored)
            frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.date
            matrix = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()
            matrix.attrs["providers"] = {
                ticker: str(values.iloc[-1])
                for ticker, values in frame.sort_values("date").groupby("ticker")["provider"]
            }
            return matrix
    if not PRICES_PATH.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(PRICES_PATH, columns=["ticker", "date", "close"])
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame = frame[frame["ticker"].isin(tickers)]
    if frame.empty:
        return pd.DataFrame()
    return frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().tail(price_limit)


def _price_coverage_diagnostics(
    prices: pd.DataFrame, research: list[dict[str, Any]], proxy_tickers: list[str]
) -> dict[str, Any]:
    providers = prices.attrs.get("providers", {})
    assets: dict[str, dict[str, Any]] = {}
    for ticker in prices.columns:
        values = prices[ticker].dropna()
        if values.empty:
            continue
        first, last = pd.Timestamp(values.index[0]), pd.Timestamp(values.index[-1])
        years = max(0.0, (last - first).days / 365.25)
        assets[ticker] = {
            "provider": providers.get(ticker, "local"), "observations": int(len(values)),
            "first": str(first.date()), "last": str(last.date()), "years": round(years, 2),
        }
    research_tickers = [row["ticker"] for row in research if row["ticker"] != "CASH"]
    insufficient = sorted(
        ticker for ticker in research_tickers
        if ticker not in assets or float(assets[ticker]["years"]) < 7
    )
    missing_proxies = sorted(ticker for ticker in proxy_tickers if ticker not in assets)
    return {
        "method": "one coherent adjusted-price provider per ticker",
        "minimum_full_cycle_years": 7,
        "assets": assets,
        "insufficient_full_cycle": insufficient,
        "sector_proxy_fallbacks": {
            row["ticker"]: SECTOR_PROXIES.get(row.get("sector", ""), "VTI")
            for row in research if row["ticker"] != "CASH"
        },
        "missing_sector_proxies": missing_proxies,
    }


def _return_model(
    research: list[dict[str, Any]], scenarios: list[dict[str, Any]],
    prices: pd.DataFrame | None = None, labels: list[dict[str, Any]] | None = None,
    research_preferences: dict[str, float] | None = None,
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
    preferences = research_preferences or {"fundamentals": .25, "growth": .20, "valuation": .20, "dividend_income": .10, "macro_resilience": .15, "price_behavior": .10}
    preference_total = sum(preferences.values()) or 1.0
    def preference_score(row: dict[str, Any]) -> float:
        dividend = 70 if row["sector"] == "Fixed Income" else 62 if row["sector"] in {"Energy", "Utilities", "Real Estate"} else 48
        resilience = 70 if row["sector"] in {"Fixed Income", "Healthcare", "Utilities", "Consumer Staples"} else 55 if row["sector"] == "Broad Market" else 45
        components = {"fundamentals": row["fundamental_score"], "growth": row["growth_rating"], "valuation": row["valuation_score"], "dividend_income": dividend, "macro_resilience": resilience, "price_behavior": row["technical_score"]}
        return sum(float(preferences.get(key, 0)) * float(value) for key, value in components.items()) / preference_total
    preference_scores = np.array([preference_score(row) for row in research])
    score_expected = np.array([row["expected_return"] * (0.45 + row["confidence"] / 250) for row in research]) * (.80 + preference_scores / 250)
    history_confidence: dict[str, float] = {}
    for row in research:
        ticker = row["ticker"]
        values = prices[ticker].dropna() if ticker in prices else pd.Series(dtype=float)
        if len(values) < 2:
            history_confidence[ticker] = 0.35 if ticker != "CASH" else 1.0
            continue
        years = (pd.Timestamp(values.index[-1]) - pd.Timestamp(values.index[0])).days / 365.25
        history_confidence[ticker] = 1.0 if years >= 7 else 0.75 if years >= 2 else 0.5
    if len(score_expected):
        score_prior = float(np.median(score_expected))
        confidence_vector = np.array([history_confidence.get(row["ticker"], 0.35) for row in research])
        score_expected = confidence_vector * score_expected + (1 - confidence_vector) * score_prior
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
            "research_customization": {"method": "policy_weighted_transparent_research_v1", "preferences": preferences},
            "history_confidence": history_confidence,
            "history_treatment": "Security research return adjustments are shrunk toward the cross-sectional prior when adjusted-price history is shorter than seven years.",
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
    source_holdings = holdings
    holdings, analysis_exclusions = equity_analysis_holdings(source_holdings)
    if not holdings:
        raise ValueError("The portfolio has no eligible stock or ETF positions to analyze")
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
    ml_evaluation = evaluate_regime_classifier(labels)
    expected, covariance, _, model_diagnostics, regime_returns = _return_model(
        research, scenarios, prices, labels, profile.research_preferences
    )
    model_diagnostics["price_coverage"] = _price_coverage_diagnostics(
        prices, research, proxy_tickers
    )
    insufficient_history = model_diagnostics["price_coverage"]["insufficient_full_cycle"]
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
    balanced = next((item for item in alternatives if item["name"] == "Balanced"), alternatives[0] if alternatives else None)
    current_return = float(expected @ current) if len(current) else 0.0
    current_volatility = float(np.sqrt(max(0, current @ covariance @ current))) if len(current) else 0.0
    contribution_capacity = min(1.0, profile.annual_contribution / max(portfolio_value, 1.0))
    contribution_allocations = []
    if balanced:
        underweights = [item for item in balanced["allocations"] if item["delta"] > 0.002]
        underweight_total = sum(item["delta"] for item in underweights) or 1.0
        contribution_allocations = [
            {
                "ticker": item["ticker"],
                "contribution_share": round(item["delta"] / underweight_total, 4),
                "estimated_annual_dollars": round(profile.annual_contribution * item["delta"] / underweight_total, 2),
            }
            for item in underweights
        ]
    gradual_weights = current.copy()
    if balanced and len(current):
        balanced_map = {item["ticker"]: item["target_weight"] for item in balanced["allocations"]}
        balanced_weights = np.array([balanced_map.get(row["ticker"], 0.0) for row in research], dtype=float)
        gradual_weights = current + 0.5 * (balanced_weights - current)
        if gradual_weights.sum() > 0:
            gradual_weights /= gradual_weights.sum()
    gradual_return = float(expected @ gradual_weights) if len(gradual_weights) else 0.0
    gradual_volatility = float(np.sqrt(max(0, gradual_weights @ covariance @ gradual_weights))) if len(gradual_weights) else 0.0
    balanced_tax = (balanced or {}).get("tax", {})
    balanced_tax_value = balanced_tax.get("estimated_tax") if balanced_tax.get("available") else None
    implementation_paths = [
        {
            "key": "current", "name": "Current / do nothing", "implementation": "Keep the current portfolio unchanged",
            "expected_return": round(current_return, 4), "volatility": round(current_volatility, 4),
            "drawdown_range": [round(-current_volatility * 2.2, 4), round(-current_volatility * 1.2, 4)],
            "turnover": 0.0, "estimated_tax": 0.0,
            "expected_benefit": "Avoids trading costs and taxable realization while preserving the present exposures.",
            "costs_and_risks": "Existing concentration, correlation, and scenario exposures remain unchanged.",
            "consequence": "No implementation work is required; review again when evidence or constraints materially change.",
            "assumptions": ["Current saved weights are held constant.", "No deposits, withdrawals, or trades are modeled."],
        },
        {
            "key": "contributions_only", "name": "Contributions only", "implementation": "Direct new cash toward underweights; do not sell existing holdings.",
            "expected_return": round(current_return + contribution_capacity * ((balanced or {}).get("expected_return", current_return) - current_return), 4),
            "volatility": round(current_volatility + contribution_capacity * ((balanced or {}).get("volatility", current_volatility) - current_volatility), 4),
            "drawdown_range": [round(-current_volatility * 2.2, 4), round(-current_volatility * 1.2, 4)],
            "turnover": 0.0, "estimated_tax": 0.0, "contribution_allocations": contribution_allocations,
            "expected_benefit": "Improves diversification without realizing gains from sales.",
            "costs_and_risks": "Progress can be slow when contributions are small relative to the portfolio.",
            "consequence": "Existing overweights decline only as new money is added elsewhere.",
            "assumptions": ["Annual contributions are available as entered in Plan.", "No security is sold."],
        },
        {
            "key": "gradual", "name": "Gradual transition", "implementation": "Move halfway from current weights toward the Balanced target in this review period.",
            "expected_return": round(gradual_return, 4), "volatility": round(gradual_volatility, 4),
            "drawdown_range": [round(-gradual_volatility * 2.2, 4), round(-gradual_volatility * 1.2, 4)],
            "turnover": round((balanced or {}).get("turnover", 0.0) * 0.5, 4),
            "estimated_tax": round(balanced_tax_value * 0.5, 2) if balanced_tax_value is not None else None,
            "expected_benefit": "Captures part of the modeled diversification benefit while spreading implementation risk.",
            "costs_and_risks": "Retains some current concentration and may require multiple future reviews.",
            "consequence": "The portfolio remains between its current allocation and the model target.",
            "assumptions": ["Each Balanced allocation delta is implemented at 50%.", "Tax estimates use aggregate cost basis when available."],
        },
        {
            "key": "immediate", "name": "Immediate transition", "implementation": "Move to the Balanced target ranges in one implementation period.",
            "expected_return": (balanced or {}).get("expected_return", current_return),
            "volatility": (balanced or {}).get("volatility", current_volatility),
            "drawdown_range": (balanced or {}).get("drawdown_range", [round(-current_volatility * 2.2, 4), round(-current_volatility * 1.2, 4)]),
            "turnover": (balanced or {}).get("turnover", 0.0), "estimated_tax": balanced_tax_value,
            "expected_benefit": "Reaches the Balanced model ranges immediately.",
            "costs_and_risks": "Creates the highest near-term turnover and may realize taxable gains.",
            "consequence": "The full model change is taken now rather than phased over time.",
            "assumptions": ["Balanced target weights are implemented at once.", "Market impact and tax-lot selection are outside v1."],
        },
    ]
    run_id = str(uuid.uuid4())
    result = {
        "id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "model_version": "walk-forward-regime-shrinkage-v2",
        "macro": latest_macro(), "scenarios": scenarios, "scenario_warnings": scenario_payload["warnings"],
        "portfolio_value": round(portfolio_value, 2), "current_weights": {row["ticker"]: round(float(current[i]), 4) for i, row in enumerate(research) if current[i] > 0},
        "analysis_universe": {
            "eligible_asset_types": ["common_stock", "etf"],
            "eligible_tickers": [holding["ticker"].upper() for holding in holdings],
            "excluded_positions": analysis_exclusions,
            "analyzed_market_value": round(portfolio_value, 2),
            "source_portfolio_market_value": round(sum(_num(row.get("market_value")) for row in source_holdings), 2),
        },
        "research": research, "alternatives": alternatives, "implementation_paths": implementation_paths,
        "model_diagnostics": model_diagnostics, "walk_forward": walk_forward,
        "benchmarks": walk_forward.get("benchmarks", []),
        "ml_regime_evaluation": ml_evaluation,
        "warnings": [
            "Decision-support research only; no trades are submitted.",
            "Expected returns and projections are model estimates, not guarantees.",
            *([f"Excluded non-equity positions from stock/ETF analysis: {', '.join(row['ticker'] for row in analysis_exclusions)}."] if analysis_exclusions else []),
            *(["Walk-forward validation is unavailable until more overlapping price and point-in-time regime history exists."] if walk_forward["status"] != "complete" else []),
            *([f"Full-cycle adjusted-price history is insufficient for: {', '.join(insufficient_history)}. Regime estimates use disclosed sector/broad-ETF priors and company-return adjustments are shrunk."] if insufficient_history else []),
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
    return f"{direction}: relative research evidence is supported by {row['data_quality']} data quality and portfolio constraints."


def _tradeoff(label: str) -> str:
    return {
        "Risk-Controlled": "Lower concentration and modeled downside, with less participation if growth assets lead.",
        "Balanced": "Balances modeled return, risk, turnover, taxes, and diversification using your selected priorities.",
        "Goal-Tilted": "More exposure to the strongest goal-aligned signals, with higher estimation and concentration risk.",
    }[label]
