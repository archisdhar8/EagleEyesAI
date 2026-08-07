from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from . import database


KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
POLYMARKET_URL = "https://gamma-api.polymarket.com/markets"
CACHE_SECONDS = 3600

PRIORS = {
    "soft_landing": 0.38,
    "sticky_inflation": 0.20,
    "recession_cuts": 0.18,
    "growth_reacceleration": 0.16,
    "oil_shock": 0.08,
}
LABELS = {
    "soft_landing": "Soft landing",
    "sticky_inflation": "Sticky inflation",
    "recession_cuts": "Recession / cutting cycle",
    "growth_reacceleration": "Growth reacceleration",
    "oil_shock": "Oil shock",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _probability(value: Any) -> float | None:
    if isinstance(value, str) and value.startswith("["):
        value = value.strip("[]").split(",")[0].strip().strip('"')
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result > 1:
        result /= 100
    return max(0.0, min(1.0, result))


def _canonical(text: str) -> tuple[str, str] | None:
    clean = text.lower()
    rules: list[tuple[str, str, str]] = [
        ("recession", "recession_cuts", "recession probability"),
        ("unemployment", "recession_cuts", "unemployment risk"),
        (r"fed.*cut|rate cut|interest rate.*lower", "recession_cuts", "rate-cut probability"),
        (r"cpi|inflation|pce", "sticky_inflation", "inflation path"),
        (r"oil|wti|brent", "oil_shock", "oil price"),
        (r"gdp|economic growth", "growth_reacceleration", "growth path"),
        (r"treasury|yield|interest rate", "sticky_inflation", "rates path"),
    ]
    for pattern, scenario, indicator in rules:
        if re.search(pattern, clean):
            return scenario, indicator
    return None


def _confidence(*, bid: float | None, ask: float | None, volume: float, open_interest: float, depth: float, updated_at: str | None) -> float:
    spread = 0.30 if bid is None or ask is None else max(0.0, ask - bid)
    spread_score = max(0.0, 1.0 - spread / 0.30)
    activity = min(1.0, math.log1p(max(volume, 0.0) + max(open_interest, 0.0)) / math.log(10001))
    depth_score = min(1.0, math.log1p(max(depth, 0.0)) / math.log(10001))
    recency = 0.7
    if updated_at:
        try:
            timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_hours = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600)
            recency = max(0.2, math.exp(-age_hours / 168))
        except ValueError:
            pass
    return max(0.05, min(1.0, spread_score * 0.45 + activity * 0.30 + depth_score * 0.10 + recency * 0.15))


def normalize_kalshi(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for market in markets:
        title = str(market.get("title") or market.get("subtitle") or market.get("ticker") or "")
        mapping = _canonical(title)
        if mapping is None:
            continue
        bid = _probability(market.get("yes_bid_dollars") or market.get("yes_bid"))
        ask = _probability(market.get("yes_ask_dollars") or market.get("yes_ask"))
        last = _probability(market.get("last_price_dollars") or market.get("last_price"))
        probability = (bid + ask) / 2 if bid is not None and ask is not None else last
        if probability is None:
            continue
        volume = _number(market.get("volume_fp") or market.get("volume"))
        oi = _number(market.get("open_interest_fp") or market.get("open_interest"))
        scenario, indicator = mapping
        contracts.append({
            "provider": "Kalshi",
            "id": str(market.get("ticker")),
            "event_id": str(market.get("event_ticker") or market.get("ticker")),
            "title": title,
            "scenario": scenario,
            "indicator": indicator,
            "probability": probability,
            "confidence": _confidence(bid=bid, ask=ask, volume=volume, open_interest=oi, depth=0, updated_at=market.get("updated_time")),
            "volume": volume,
            "open_interest": oi,
            "source": f"https://kalshi.com/markets/{market.get('ticker', '')}",
        })
    return contracts


def normalize_polymarket(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for market in markets:
        title = str(market.get("question") or market.get("title") or "")
        mapping = _canonical(title)
        if mapping is None:
            continue
        probability = _probability(market.get("outcomePrices") or market.get("lastTradePrice"))
        if probability is None:
            continue
        bid = _probability(market.get("bestBid"))
        ask = _probability(market.get("bestAsk"))
        volume = _number(market.get("volumeNum") or market.get("volume"))
        oi = _number(market.get("openInterest"))
        scenario, indicator = mapping
        contracts.append({
            "provider": "Polymarket",
            "id": str(market.get("id") or market.get("conditionId")),
            "event_id": str(market.get("conditionId") or market.get("id")),
            "title": title,
            "scenario": scenario,
            "indicator": indicator,
            "probability": probability,
            "confidence": _confidence(bid=bid, ask=ask, volume=volume, open_interest=oi, depth=0, updated_at=market.get("updatedAt")),
            "volume": volume,
            "open_interest": oi,
            "source": f"https://polymarket.com/event/{market.get('slug', '')}",
        })
    return contracts


def _deduplicate(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for contract in contracts:
        key = (contract["provider"], contract["event_id"], contract["indicator"])
        if key not in best or contract["confidence"] > best[key]["confidence"]:
            best[key] = contract
    return list(best.values())


def build_scenarios(contracts: list[dict[str, Any]], history: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    contracts = _deduplicate(contracts)
    raw: dict[str, float] = {}
    confidence: dict[str, float] = {}
    now = datetime.now(timezone.utc)
    for key, prior in PRIORS.items():
        subset = [row for row in contracts if row["scenario"] == key]
        if not subset:
            raw[key] = prior
            confidence[key] = 0.20
            continue
        total_weight = sum(max(row["confidence"], 0.05) for row in subset)
        observed = sum(row["probability"] * max(row["confidence"], 0.05) for row in subset) / total_weight
        mean_confidence = min(1.0, total_weight / max(2.0, len(subset)))
        raw[key] = prior * (1 - mean_confidence) + observed * mean_confidence
        confidence[key] = max(0.20, mean_confidence)
    total = sum(raw.values()) or 1.0
    probabilities = {key: value / total for key, value in raw.items()}
    scenarios = []
    for key in PRIORS:
        subset = [row for row in contracts if row["scenario"] == key]
        scenarios.append({
            "key": key,
            "label": LABELS[key],
            "probability": round(probabilities[key], 4),
            "confidence": round(confidence[key], 4),
            "change_1d": _historical_change(key, probabilities[key], history or [], timedelta(days=1)),
            "change_1w": _historical_change(key, probabilities[key], history or [], timedelta(days=7)),
            "change_1m": _historical_change(key, probabilities[key], history or [], timedelta(days=30)),
            "indicators": sorted({row["indicator"] for row in subset}),
            "sources": sorted({row["source"] for row in subset})[:5],
            "as_of": now.isoformat(),
            "is_prior": not subset,
        })
    return scenarios


def _historical_change(key: str, current: float, history: list[dict[str, Any]], delta: timedelta) -> float | None:
    target = datetime.now(timezone.utc) - delta
    candidates: list[tuple[float, float]] = []
    for snapshot in history:
        try:
            timestamp = datetime.fromisoformat(snapshot["fetched_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        for scenario in snapshot["scenarios"]:
            if scenario["key"] == key:
                candidates.append((abs((timestamp - target).total_seconds()), float(scenario["probability"])))
    if not candidates:
        return None
    distance, prior_value = min(candidates, key=lambda item: item[0])
    if distance > max(delta.total_seconds() * 0.75, 6 * 3600):
        return None
    return round(current - prior_value, 4)


def refresh(force: bool = False) -> dict[str, Any]:
    latest = database.latest_scenario_snapshot()
    if latest and not force:
        fetched = datetime.fromisoformat(latest["fetched_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - fetched).total_seconds() < CACHE_SECONDS:
            return {**latest, "cached": True}
    warnings: list[str] = []
    contracts: list[dict[str, Any]] = []
    try:
        response = requests.get(KALSHI_URL, params={"status": "open", "limit": 1000, "mve_filter": "exclude"}, timeout=15)
        response.raise_for_status()
        contracts.extend(normalize_kalshi(response.json().get("markets", [])))
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"Kalshi refresh unavailable: {type(exc).__name__}")
    try:
        response = requests.get(POLYMARKET_URL, params={"active": "true", "closed": "false", "limit": 500}, timeout=15)
        response.raise_for_status()
        contracts.extend(normalize_polymarket(response.json()))
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"Polymarket refresh unavailable: {type(exc).__name__}")

    if not contracts and latest:
        return {**latest, "cached": True, "warnings": latest["warnings"] + warnings + ["Using the latest validated scenario snapshot."]}
    history = database.scenario_history()
    scenarios = build_scenarios(contracts, history)
    if not contracts:
        warnings.append("No matching macro contracts found; scenario probabilities use disclosed priors.")
    database.save_scenario_snapshot(scenarios, contracts, warnings)
    return {"scenarios": scenarios, "contracts": contracts, "warnings": warnings, "fetched_at": datetime.now(timezone.utc).isoformat(), "cached": False}

