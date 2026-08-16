from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from . import database


VERSION = "security-research-snapshot-v1.0.0"


def bucket(value: float | None, thresholds: tuple[float, float, float, float], higher_is_better: bool = True) -> str:
    if value is None or not math.isfinite(value):
        return "Unavailable"
    labels = ["Very Weak", "Weak", "Mixed", "Strong", "Very Strong"]
    index = sum(value >= threshold for threshold in thresholds)
    return labels[index if higher_is_better else 4 - index]


def _series(rows: list[dict[str, Any]], ticker: str) -> pd.DataFrame:
    values = [row for row in rows if row.get("ticker") == ticker]
    if not values:
        return pd.DataFrame(columns=["close", "volume"])
    frame = pd.DataFrame(values)
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    return frame.dropna(subset=["close"])


def _return(frame: pd.DataFrame, sessions: int) -> float | None:
    if len(frame) <= sessions:
        return None
    return float(frame["close"].iloc[-1] / frame["close"].iloc[-sessions - 1] - 1)


def _max_drawdown(values: pd.Series) -> float | None:
    if values.empty:
        return None
    return float((values / values.cummax() - 1).min())


def _rsi(values: pd.Series, window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    changes = values.diff().dropna()
    gain = changes.clip(lower=0).tail(window).mean()
    loss = -changes.clip(upper=0).tail(window).mean()
    if loss == 0:
        return 100.0
    return float(100 - 100 / (1 + gain / loss))


def _support_resistance(values: pd.Series) -> dict[str, Any]:
    recent = values.tail(126)
    if len(recent) < 20:
        return {"support": [], "resistance": [], "method": "insufficient history"}
    current = float(recent.iloc[-1])
    lows = [float(recent.quantile(.10)), float(recent.quantile(.25))]
    highs = [float(recent.quantile(.75)), float(recent.quantile(.90))]
    return {
        "support": sorted({round(value, 2) for value in lows if value < current}, reverse=True),
        "resistance": sorted({round(value, 2) for value in highs if value > current}),
        "method": "10th/25th and 75th/90th percentiles of the latest 126 adjusted closes",
    }


def technicals(ticker: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = ticker.upper()
    payload = data or database.security_data([normalized, "SPY"], price_limit=3000)
    frame = _series(payload.get("prices", []), normalized)
    benchmark = _series(payload.get("prices", []), "SPY")
    if frame.empty:
        return {"ticker": normalized, "status": "unavailable", "warnings": ["No validated adjusted-price history is stored."], "method_version": VERSION}
    returns = frame["close"].pct_change().dropna()
    annual_return = float((frame["close"].iloc[-1] / frame["close"].iloc[0]) ** (252 / max(1, len(frame) - 1)) - 1) if len(frame) > 1 else None
    volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 else None
    sharpe = ((annual_return - .04) / volatility) if annual_return is not None and volatility and volatility > 0 else None
    beta = None
    if not benchmark.empty:
        pair = pd.concat([returns.rename("asset"), benchmark["close"].pct_change().rename("market")], axis=1).dropna()
        if len(pair) >= 30 and pair["market"].var() > 0:
            beta = float(pair.cov().loc["asset", "market"] / pair["market"].var())
    rsi = _rsi(frame["close"])
    sma50 = float(frame["close"].tail(50).mean()) if len(frame) >= 50 else None
    sma200 = float(frame["close"].tail(200).mean()) if len(frame) >= 200 else None
    current = float(frame["close"].iloc[-1])
    trend = "Unavailable"
    if sma50 is not None:
        trend = "Very Strong" if sma200 and current > sma50 > sma200 else "Strong" if current > sma50 else "Very Weak" if sma200 and current < sma50 < sma200 else "Weak"
    provider = next((row.get("provider") for row in reversed(payload.get("prices", [])) if row.get("ticker") == normalized), "unknown")
    return {
        "ticker": normalized, "status": "ready", "as_of": frame.index[-1].isoformat(),
        "price": current, "daily_change": _return(frame, 1),
        "returns": {"1_week": _return(frame, 5), "1_month": _return(frame, 21), "3_month": _return(frame, 63), "1_year": _return(frame, 252), "3_year": _return(frame, 756)},
        "range_52_week": {"low": round(float(frame["close"].tail(252).min()), 2), "high": round(float(frame["close"].tail(252).max()), 2)},
        "liquidity": {"average_daily_volume_30d": float(frame["volume"].tail(30).mean()) if frame["volume"].notna().any() else None},
        "volatility": volatility, "beta": beta, "sharpe_ratio": sharpe,
        "maximum_drawdown": _max_drawdown(frame["close"]), "rsi_14": rsi,
        "moving_averages": {"sma_50": sma50, "sma_200": sma200, "trend_bucket": trend},
        "support_resistance": _support_resistance(frame["close"]),
        "buckets": {
            "risk": bucket(volatility, (.15, .25, .40, .60), higher_is_better=False),
            "risk_adjusted_return": bucket(sharpe, (0, .5, 1, 1.5)),
            "momentum": bucket(rsi, (30, 45, 60, 70)),
            "price_behavior": trend,
        },
        "lineage": [{"provider": provider, "dataset": "daily corporate-action-adjusted prices", "effective_through": frame.index[-1].isoformat()}],
        "calculation": {"method": "descriptive price statistics", "version": VERSION, "sample_count": len(frame), "risk_free_rate": .04},
        "assumptions": ["Adjusted closes are used.", "Sharpe ratio uses a disclosed 4% annual risk-free assumption."],
        "warnings": [] if len(frame) >= 252 else ["Less than one trading year is available; long-horizon statistics are weakened."],
    }


def sentiment(ticker: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = ticker.upper()
    payload = data or database.security_data([normalized], price_limit=2)
    rows = [row for row in payload.get("news", []) if row.get("ticker") == normalized]
    now = datetime.now(timezone.utc)
    counts = {"positive": 0, "neutral": 0, "negative": 0, "unclassified": 0}
    windows = {"30_days": 0, "90_days": 0}
    articles = []
    for row in rows:
        metadata = row.get("metadata") or {}
        label = str(metadata.get("sentiment") or metadata.get("sentiment_label") or "unclassified").lower()
        label = label if label in counts else "unclassified"
        counts[label] += 1
        published = pd.to_datetime(row.get("published_at"), utc=True, errors="coerce")
        if not pd.isna(published):
            age = (now - published.to_pydatetime()).days
            windows["30_days"] += age <= 30
            windows["90_days"] += age <= 90
        articles.append({"title": row.get("title"), "source_url": row.get("source_url"), "published_at": row.get("published_at"), "sentiment": label, "source_quality": metadata.get("source_quality") or "not rated"})
    classified = counts["positive"] + counts["neutral"] + counts["negative"]
    distribution = {key: round(value / classified, 4) if classified else None for key, value in counts.items() if key != "unclassified"}
    agreement = max(distribution.values()) if classified and all(value is not None for value in distribution.values()) else None
    return {
        "ticker": normalized, "as_of": now.isoformat(), "article_count": len(rows), "windows": windows,
        "distribution": distribution, "unclassified_count": counts["unclassified"],
        "coverage": "Strong" if classified >= 15 else "Mixed" if classified >= 5 else "Weak",
        "agreement": "High" if agreement and agreement >= .70 else "Mixed" if agreement and agreement >= .50 else "Low",
        "freshness": "Current" if windows["30_days"] else "Stale or unavailable",
        "articles": articles,
        "lineage": [{"provider": "stored news sources", "dataset": "article-level news evidence", "effective_through": max((row.get("published_at") or "" for row in rows), default=None)}],
        "calculation": {"method": "stored article labels and deterministic distribution", "version": VERSION},
        "warnings": [] if classified >= 5 else ["Too few classified articles for a strong sentiment conclusion."],
    }


def overview(ticker: str) -> dict[str, Any]:
    normalized = ticker.upper()
    data = database.security_data([normalized, "SPY"], price_limit=3000)
    security = next((row for row in data.get("securities", []) if row.get("ticker") == normalized), None)
    if not security:
        return {"ticker": normalized, "status": "unavailable", "warnings": ["Security is not present in the validated research store."]}
    tech = technicals(normalized, data)
    sent = sentiment(normalized, data)
    periods = [row for row in data.get("fundamentals", []) if row.get("ticker") == normalized]
    latest = (periods[0].get("metrics") or {}) if periods else {}
    previous = (periods[1].get("metrics") or {}) if len(periods) > 1 else {}
    def first(metrics: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None
    revenue = first(latest, "revenue", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
    prior_revenue = first(previous, "revenue", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
    net_income = first(latest, "net_income", "NetIncomeLoss")
    equity = first(latest, "equity", "StockholdersEquity")
    assets = first(latest, "assets", "Assets")
    liabilities = first(latest, "liabilities", "Liabilities")
    fcf = first(latest, "free_cash_flow", "FreeCashFlow")
    fundamentals = {
        "revenue": revenue,
        "revenue_growth": (revenue / prior_revenue - 1) if revenue is not None and prior_revenue else None,
        "net_margin": (net_income / revenue) if net_income is not None and revenue else None,
        "free_cash_flow": fcf,
        "roe": (net_income / equity) if net_income is not None and equity else None,
        "debt_to_assets": (liabilities / assets) if liabilities is not None and assets else None,
        "periods_available": len(periods),
    }
    available = sum(value is not None for key, value in fundamentals.items() if key != "periods_available")
    return {
        "ticker": normalized, "company": security.get("company_name") or normalized,
        "sector": security.get("sector"), "industry": security.get("industry"),
        "market": tech, "fundamentals": fundamentals, "sentiment_summary": {key: sent[key] for key in ("article_count", "distribution", "coverage", "agreement", "freshness")},
        "conclusions": {
            "company_quality": bucket(fundamentals["net_margin"], (0, .05, .12, .22)),
            "fundamental_trend": bucket(fundamentals["revenue_growth"], (-.10, 0, .08, .20)),
            "price_behavior": tech.get("buckets", {}).get("price_behavior", "Unavailable"),
            "sentiment": sent["coverage"] if sent["coverage"] == "Weak" else sent["agreement"],
            "research_confidence": "Strong" if available >= 4 and len(periods) >= 4 else "Mixed" if available >= 2 else "Weak",
        },
        "lineage": [*tech.get("lineage", []), *sent.get("lineage", [])],
        "calculation": {"method": "separate deterministic research lenses", "version": VERSION},
        "warnings": [*tech.get("warnings", []), *sent.get("warnings", []), *([] if periods else ["No stored SEC fundamental periods are available."])],
        "what_would_change_the_view": ["A material change in revenue or margin trend", "A valuation change relative to selected peers", "New evidence that changes price-risk or catalyst conclusions"],
    }
