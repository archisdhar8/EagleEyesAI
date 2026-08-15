from __future__ import annotations

import math
import re
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from . import database


KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
POLYMARKET_URL = "https://gamma-api.polymarket.com/markets"
POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"
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
DIMENSIONS = {
    "soft_landing": ("Economic conditions", "Soft landing / slowdown"),
    "growth_reacceleration": ("Economic conditions", "Growth reacceleration"),
    "recession_cuts": ("Economic conditions", "Recession / slowdown"),
    "sticky_inflation": ("Inflation conditions", "Sticky / accelerating inflation"),
    "oil_shock": ("Independent market shocks", "Oil-price shock"),
}

SPORTS_CONTEXT_PATTERN = re.compile(
    r"\b(?:sports?|soccer|football|basketball|baseball|hockey|tennis|cricket|"
    r"esports?|nfl|nba|wnba|nhl|mlb|epl|uefa|fifa)\b",
    re.IGNORECASE,
)
SPORTS_TITLE_PATTERN = re.compile(
    r"(?:\bvs(?:\.|\b)|\b(?:match|game|score|goals?|league|tournament|"
    r"playoffs?|quarterfinal|semifinal)\b|\bwinner\s*\?)",
    re.IGNORECASE,
)


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


def _market_context(market: dict[str, Any] | None) -> str:
    if not market:
        return ""
    values: list[str] = []
    for key in ("category", "subcategory", "tags", "series_ticker", "event_ticker", "ticker", "slug"):
        value = market.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item.get("label") or item.get("name") or item) if isinstance(item, dict) else str(item) for item in value)
    return " ".join(values)


def is_sports_market(text: str, market: dict[str, Any] | None = None) -> bool:
    return bool(SPORTS_TITLE_PATTERN.search(text) or SPORTS_CONTEXT_PATTERN.search(_market_context(market)))


def _canonical(text: str, market: dict[str, Any] | None = None) -> tuple[str, str] | None:
    clean = text.lower()
    if is_sports_market(clean, market):
        return None
    rules: list[tuple[str, str, str]] = [
        (r"\brecession\b", "recession_cuts", "recession probability"),
        (r"\bunemployment\b", "recession_cuts", "unemployment risk"),
        (r"\bfed\b.*\bcut|\brate cuts?\b|\binterest rates?\b.*\blower\b", "recession_cuts", "rate-cut probability"),
        (r"\b(?:cpi|inflation|pce)\b", "sticky_inflation", "inflation path"),
        (
            r"\b(?:crude oil|oil prices?|wti|west texas intermediate|brent(?: crude| oil| prices?)?)\b",
            "oil_shock",
            "oil price",
        ),
        (r"\b(?:gdp|economic growth)\b", "growth_reacceleration", "growth path"),
        (r"\b(?:treasury|yields?|interest rates?)\b", "sticky_inflation", "rates path"),
    ]
    for pattern, scenario, indicator in rules:
        if re.search(pattern, clean):
            return scenario, indicator
    return None


def _threshold_bucket(text: str) -> dict[str, Any]:
    clean = text.lower().replace(",", "")
    operator = None
    if re.search(r"\b(above|over|exceed|higher than|at least|more than)\b", clean):
        operator = "gte"
    elif re.search(r"\b(below|under|lower than|at most|less than)\b", clean):
        operator = "lte"
    match = re.search(r"(?:\$\s*)?(-?\d+(?:\.\d+)?)\s*(%|percent|bps|basis points|dollars?)?", clean)
    if operator is None or match is None:
        return {}
    value = float(match.group(1))
    unit = match.group(2) or ("usd" if "$" in match.group(0) else "level")
    return {"operator": operator, "value": value, "unit": unit}


def canonical_contract_series(contract: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map venue-specific expirations into a stable macro-question family."""
    bucket = contract.get("threshold_bucket") or _threshold_bucket(str(contract.get("title", "")))
    parts = [str(contract.get("scenario", "unknown")), str(contract.get("indicator", "unknown"))]
    if bucket:
        parts.extend([str(bucket.get("operator")), str(bucket.get("value")), str(bucket.get("unit"))])
    material = "|".join(parts).lower()
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"macro:{digest}", bucket


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
        mapping = _canonical(title, market)
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
            "bid": bid,
            "ask": ask,
            "confidence": _confidence(bid=bid, ask=ask, volume=volume, open_interest=oi, depth=0, updated_at=market.get("updated_time")),
            "volume": volume,
            "open_interest": oi,
            "source": f"https://kalshi.com/markets/{market.get('ticker', '')}",
            "closes_at": market.get("close_time") or market.get("expected_expiration_time") or market.get("expiration_time"),
            "threshold_bucket": _threshold_bucket(title),
        })
    return contracts


def normalize_polymarket(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for market in markets:
        title = str(market.get("question") or market.get("title") or "")
        mapping = _canonical(title, market)
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
            "bid": bid,
            "ask": ask,
            "confidence": _confidence(bid=bid, ask=ask, volume=volume, open_interest=oi, depth=0, updated_at=market.get("updatedAt")),
            "volume": volume,
            "open_interest": oi,
            "source": f"https://polymarket.com/event/{market.get('slug', '')}",
            "closes_at": market.get("endDate") or market.get("end_date_iso"),
            "threshold_bucket": _threshold_bucket(title),
            "token_ids": market.get("clobTokenIds"),
        })
    return contracts


def discover_polymarket_contracts(max_events: int = 400) -> list[dict[str, Any]]:
    """Discover macro contracts through event pagination.

    The first /markets page is popularity ordered and can contain no macro
    questions. Polymarket documents event pagination as its complete discovery
    path; events embed their associated markets.
    """
    contracts: list[dict[str, Any]] = []
    page_size = 100
    for offset in range(0, max_events, page_size):
        response = requests.get(
            POLYMARKET_EVENTS_URL,
            params={
                "active": "true", "closed": "false", "order": "volume",
                "ascending": "false", "limit": page_size, "offset": offset,
            },
            timeout=15,
        )
        response.raise_for_status()
        events = response.json()
        if not isinstance(events, list):
            raise ValueError("Polymarket returned an unexpected events payload")
        markets = [market for event in events for market in (event.get("markets") or [])]
        contracts.extend(normalize_polymarket(markets))
        if len(events) < page_size:
            break
    return _deduplicate(contracts)


def _deduplicate(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for contract in contracts:
        key = (contract["provider"], contract["event_id"], contract["indicator"])
        if key not in best or contract["confidence"] > best[key]["confidence"]:
            best[key] = contract
    return list(best.values())


def sanitize_contracts(contracts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Revalidate stored contracts with the current classifier.

    Snapshots can outlive a classifier release, so cached data must pass the
    same checks as newly fetched provider data before it can affect a scenario.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for contract in contracts:
        mapping = _canonical(str(contract.get("title", "")), contract)
        if mapping is None or mapping != (contract.get("scenario"), contract.get("indicator")):
            rejected.append(contract)
        else:
            accepted.append(contract)
    return accepted, rejected


def _macro_priors(macro_signal: dict[str, Any] | None) -> tuple[dict[str, float], float, str | None]:
    """Blend the stable disclosed baseline with the latest point-in-time macro trend model."""
    if not macro_signal:
        return dict(PRIORS), 0.0, None
    supplied = macro_signal.get("probabilities") or {}
    probabilities = {key: max(0.0, _number(supplied.get(key))) for key in PRIORS}
    total = sum(probabilities.values())
    if total <= 0:
        return dict(PRIORS), 0.0, None
    probabilities = {key: value / total for key, value in probabilities.items()}
    quality = max(0.0, min(1.0, _number(macro_signal.get("data_quality"), 0.0)))
    trend_weight = 0.75 * quality
    blended = {
        key: PRIORS[key] * (1 - trend_weight) + probabilities[key] * trend_weight
        for key in PRIORS
    }
    confidence = max(0.20, min(0.75, _number(macro_signal.get("confidence"), 0.0) * quality))
    return blended, confidence, str(macro_signal.get("as_of_date") or "") or None


def build_scenarios(
    contracts: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
    macro_signal: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    contracts = _deduplicate(contracts)
    macro_priors, macro_confidence, macro_as_of = _macro_priors(macro_signal)
    raw: dict[str, float] = {}
    confidence: dict[str, float] = {}
    now = datetime.now(timezone.utc)
    for key, prior in macro_priors.items():
        subset = [row for row in contracts if row["scenario"] == key]
        if not subset:
            raw[key] = prior
            confidence[key] = max(0.20, macro_confidence)
            continue
        total_weight = sum(max(row["confidence"], 0.05) for row in subset)
        observed = sum(row["probability"] * max(row["confidence"], 0.05) for row in subset) / total_weight
        mean_confidence = min(1.0, total_weight / max(2.0, len(subset)))
        raw[key] = prior * (1 - mean_confidence) + observed * mean_confidence
        confidence[key] = max(0.20, min(1.0, macro_confidence * (1 - mean_confidence) + mean_confidence))
    # These estimates describe overlapping conditions, not five mutually exclusive
    # outcomes. Do not force them to sum to 100%. The optimizer normalizes the
    # applicable regime weights internally when it needs a convex mixture.
    probabilities = {key: max(0.01, min(0.99, value)) for key, value in raw.items()}
    scenarios = []
    for key in PRIORS:
        subset = [row for row in contracts if row["scenario"] == key]
        scenarios.append({
            "key": key,
            "label": LABELS[key],
            "dimension": DIMENSIONS[key][0],
            "state": DIMENSIONS[key][1],
            "probability": round(probabilities[key], 4),
            "confidence": round(confidence[key], 4),
            "change_1d": _historical_change(key, probabilities[key], history or [], timedelta(days=1)),
            "change_1w": _historical_change(key, probabilities[key], history or [], timedelta(days=7)),
            "change_1m": _historical_change(key, probabilities[key], history or [], timedelta(days=30)),
            "indicators": (["FRED macro trends"] if macro_as_of else []) + sorted({row["indicator"] for row in subset}),
            "sources": ((["https://fred.stlouisfed.org/"] if macro_as_of else []) + sorted({row["source"] for row in subset}))[:6],
            "as_of": now.isoformat(),
            "is_prior": not subset and macro_as_of is None,
            "evidence_basis": "blended" if subset and macro_as_of else "prediction_market" if subset else "macro_trend_model" if macro_as_of else "disclosed_prior",
            "macro_as_of": macro_as_of,
            "probability_model": "independent_conditions_v1",
        })
    return scenarios


def build_condition_dimensions(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compile legacy-compatible signals into explicit, composable condition dimensions."""
    by_key={row["key"]:row for row in scenarios}
    now=datetime.now(timezone.utc).isoformat()
    def dimension(name: str, values: list[tuple[str,str,float,list[str]]]) -> list[dict[str,Any]]:
        total=sum(max(value,0.001) for _,_,value,_ in values)
        return [{
            "key":key,"label":label,"dimension":name,"state":label,
            "probability":round(max(value,0.001)/total,4),
            "confidence":round(max((by_key.get(source) or {}).get("confidence",.2) for source in sources),4),
            "change_1d":None,"change_1w":None,"change_1m":None,
            "indicators":sorted({item for source in sources for item in (by_key.get(source) or {}).get("indicators",[])}),
            "sources":sorted({item for source in sources for item in (by_key.get(source) or {}).get("sources",[])}),
            "as_of":now,"is_prior":all((by_key.get(source) or {}).get("is_prior",True) for source in sources),
            "evidence_basis":"dimension_compiler","probability_model":"composable_conditions_v2",
            "source_signals":sources,
        } for key,label,value,sources in values]
    recession=float((by_key.get("recession_cuts") or {}).get("probability",.18))
    growth=float((by_key.get("growth_reacceleration") or {}).get("probability",.16))
    slowdown=float((by_key.get("soft_landing") or {}).get("probability",.38))
    inflation=float((by_key.get("sticky_inflation") or {}).get("probability",.20))
    easing=min(.85,.15+.65*recession); tightening=min(.85,.10+.70*inflation); stable=max(.05,1-easing-tightening)
    output=[]
    output.extend(dimension("Economic state",[("economic_expansion","Expansion",growth,["growth_reacceleration"]),("economic_slowdown","Slowdown",slowdown,["soft_landing"]),("economic_recession","Recession",recession,["recession_cuts"])]))
    output.extend(dimension("Inflation state",[("inflation_cooling","Cooling",(1-inflation)*.45,["sticky_inflation"]),("inflation_stable","Stable",(1-inflation)*.55,["sticky_inflation"]),("inflation_accelerating","Accelerating",inflation,["sticky_inflation"])]))
    output.extend(dimension("Rate state",[("rates_easing","Easing",easing,["recession_cuts"]),("rates_stable","Stable",stable,["soft_landing"]),("rates_tightening","Tightening",tightening,["sticky_inflation"])]))
    oil=by_key.get("oil_shock") or {}
    output.append({**oil,"key":"shock_oil","label":"Oil-price shock","dimension":"Independent shocks","state":"Oil-price shock","probability_model":"independent_shock_v2","source_signals":["oil_shock"]})
    return output


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
    regime_rows = database.regime_history(limit=1)
    macro_signal = regime_rows[0] if regime_rows else None
    latest = database.latest_scenario_snapshot()
    latest_contracts: list[dict[str, Any]] = []
    rejected_cached: list[dict[str, Any]] = []
    if latest:
        latest_contracts, rejected_cached = sanitize_contracts(latest.get("contracts", []))
    if latest and not force:
        fetched = datetime.fromisoformat(latest["fetched_at"].replace("Z", "+00:00"))
        current_model = all(
            row.get("probability_model") == "independent_conditions_v1"
            for row in latest.get("scenarios", [])
        )
        if current_model and not rejected_cached and (datetime.now(timezone.utc) - fetched).total_seconds() < CACHE_SECONDS:
            return {**latest, "condition_dimensions":build_condition_dimensions(latest.get("scenarios",[])),"condition_model":"composable_conditions_v2","cached": True}
    warnings: list[str] = []
    contracts: list[dict[str, Any]] = []
    try:
        response = requests.get(KALSHI_URL, params={"status": "open", "limit": 1000, "mve_filter": "exclude"}, timeout=15)
        response.raise_for_status()
        contracts.extend(normalize_kalshi(response.json().get("markets", [])))
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"Kalshi refresh unavailable: {type(exc).__name__}")
    try:
        contracts.extend(discover_polymarket_contracts())
    except (requests.RequestException, ValueError) as exc:
        warnings.append(f"Polymarket refresh unavailable: {type(exc).__name__}")

    if rejected_cached:
        warnings.append(
            f"Rejected {len(rejected_cached)} cached contract(s) that failed the current macro-market classifier."
        )
    if not contracts and latest:
        fallback_scenarios = build_scenarios(latest_contracts, macro_signal=macro_signal)
        fallback_warnings = list(latest.get("warnings", [])) + warnings
        if latest_contracts:
            fallback_warnings.append("Using only revalidated contracts from the latest snapshot.")
        else:
            fallback_warnings.append("No validated prediction-market evidence remains; using disclosed priors.")
        fallback_warnings = list(dict.fromkeys(fallback_warnings))
        database.save_scenario_snapshot(fallback_scenarios, latest_contracts, fallback_warnings)
        return {
            "scenarios": fallback_scenarios,
            "condition_dimensions":build_condition_dimensions(fallback_scenarios),
            "condition_model":"composable_conditions_v2",
            "contracts": latest_contracts,
            "warnings": fallback_warnings,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cached": True,
        }
    history = database.scenario_history()
    scenarios = build_scenarios(contracts, history, macro_signal)
    if not contracts:
        warnings.append("No matching macro contracts found; scenario probabilities use disclosed priors.")
    database.save_scenario_snapshot(scenarios, contracts, warnings)
    return {"scenarios": scenarios,"condition_dimensions":build_condition_dimensions(scenarios),"condition_model":"composable_conditions_v2", "contracts": contracts, "warnings": warnings, "fetched_at": datetime.now(timezone.utc).isoformat(), "cached": False}
