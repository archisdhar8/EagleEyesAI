from __future__ import annotations

import math
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import database, theses


ProbabilitySource = Literal["MARKET_IMPLIED", "MODEL", "USER_DEFINED", "COMPOSITE"]
MarketCategory = Literal["MACRO", "POLICY", "GEOPOLITICAL", "INDUSTRY", "COMPANY_EVENT", "UNKNOWN", "OTHER"]
MarketQuality = Literal["HIGH", "MODERATE", "LOW", "INSUFFICIENT_DATA"]
ExposureDirection = Literal["POSITIVE", "NEGATIVE", "MIXED", "UNCERTAIN"]
ExposureStrength = Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"]


class ProbabilityValue(BaseModel):
    source_type: ProbabilitySource
    probability: float = Field(ge=0, le=1)
    as_of: datetime
    source: str
    methodology: str | None = None


class MarketQualityAssessment(BaseModel):
    level: MarketQuality
    freshness: Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"]
    liquidity: Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"]
    criteria: list[str]
    stale: bool
    methodology: Literal["prediction-market-quality-v1"] = "prediction-market-quality-v1"


class ExposureRelationship(BaseModel):
    factor: str
    mechanism: str
    direction: ExposureDirection
    strength: ExposureStrength
    linked_companies: list[str] = Field(default_factory=list)
    linked_industries: list[str] = Field(default_factory=list)
    linked_sectors: list[str] = Field(default_factory=list)


class PredictionMarketObservation(BaseModel):
    provider: str
    market_id: str
    event_key: str
    title: str
    description: str | None = None
    category: MarketCategory
    outcome: str = "YES"
    probability: ProbabilityValue
    market_opened_at: datetime | None = None
    resolution_date: datetime | None = None
    resolution_criteria: str | None = None
    status: str
    liquidity: float | None = None
    volume: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    linked_companies: list[str] = Field(default_factory=list)
    linked_industries: list[str] = Field(default_factory=list)
    linked_macro_factors: list[str] = Field(default_factory=list)
    linked_portfolio_factors: list[str] = Field(default_factory=list)
    event_tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    quality: MarketQualityAssessment
    change: dict[str, Any] = Field(default_factory=dict)
    exposures: list[ExposureRelationship] = Field(default_factory=list)
    affected_holdings: list[str] = Field(default_factory=list)
    affected_theses: list[dict[str, Any]] = Field(default_factory=list)
    relevance_score: int = 0


FACTOR_RULES: tuple[dict[str, Any], ...] = (
    {"factor": "SEMICONDUCTOR_EXPORT_RESTRICTION", "pattern": r"semiconductor|advanced[- ]chip|chip export|export restriction",
     "category": "INDUSTRY", "mechanism": "China revenue and advanced-chip sales exposure",
     "direction": "NEGATIVE", "strength": "HIGH", "industries": ["Semiconductors"],
     "companies": ["NVDA", "AMD", "AVGO", "MU", "INTC", "QCOM"]},
    {"factor": "INTEREST_RATES", "pattern": r"fed|rate cut|interest rate|treasury yield|higher.for.longer",
     "category": "MACRO", "mechanism": "financing costs and duration-sensitive valuation",
     "direction": "MIXED", "strength": "MODERATE", "sectors": ["Technology", "Real Estate", "Utilities", "Financials"]},
    {"factor": "RECESSION", "pattern": r"recession|economic contraction|unemployment",
     "category": "MACRO", "mechanism": "cyclical demand, credit quality, and earnings sensitivity",
     "direction": "NEGATIVE", "strength": "HIGH", "sectors": ["Consumer Cyclical", "Financials", "Industrials"]},
    {"factor": "INFLATION", "pattern": r"inflation|cpi|pce",
     "category": "MACRO", "mechanism": "input costs, pricing power, and discount-rate sensitivity",
     "direction": "MIXED", "strength": "MODERATE", "sectors": ["Consumer Cyclical", "Technology", "Energy"]},
    {"factor": "OIL_PRICE", "pattern": r"oil|wti|brent|crude",
     "category": "MACRO", "mechanism": "energy revenue and transportation/input costs",
     "direction": "MIXED", "strength": "HIGH", "sectors": ["Energy", "Industrials", "Consumer Cyclical"]},
    {"factor": "REGULATION", "pattern": r"regulation|regulator|antitrust|approval|ban|lawsuit",
     "category": "POLICY", "mechanism": "operating permissions, compliance costs, or transaction completion",
     "direction": "UNCERTAIN", "strength": "MODERATE"},
    {"factor": "GEOPOLITICAL_RISK", "pattern": r"war|conflict|sanction|taiwan|trade restriction|tariff",
     "category": "GEOPOLITICAL", "mechanism": "supply-chain, market-access, and geopolitical disruption",
     "direction": "NEGATIVE", "strength": "MODERATE"},
)

QUALITY_ORDER = {"INSUFFICIENT_DATA": 0, "LOW": 1, "MODERATE": 2, "HIGH": 3}
MATERIALITY_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def classify_market(title: str, metadata: dict[str, Any] | None = None) -> tuple[MarketCategory, list[str]]:
    text = " ".join([title, str((metadata or {}).get("category") or ""), str((metadata or {}).get("evidence_type") or "")]).lower()
    factors = [rule["factor"] for rule in FACTOR_RULES if re.search(rule["pattern"], text, re.IGNORECASE)]
    category = next((rule["category"] for rule in FACTOR_RULES if rule["factor"] in factors), None)
    if not category and re.search(r"merger|acquisition|earnings|launch|company|ceo", text):
        category = "COMPANY_EVENT"
    return (category or "UNKNOWN"), factors


def map_exposures(title: str, metadata: dict[str, Any] | None = None) -> list[ExposureRelationship]:
    text = " ".join([title, str((metadata or {}).get("canonical_scenario") or ""), str((metadata or {}).get("evidence_type") or "")])
    direct = str((metadata or {}).get("ticker") or "").upper()
    result: list[ExposureRelationship] = []
    for rule in FACTOR_RULES:
        if not re.search(rule["pattern"], text, re.IGNORECASE):
            continue
        companies = list(rule.get("companies", []))
        if direct and direct not in companies:
            companies.append(direct)
        result.append(ExposureRelationship(
            factor=rule["factor"], mechanism=rule["mechanism"], direction=rule["direction"],
            strength=rule["strength"], linked_companies=companies,
            linked_industries=rule.get("industries", []), linked_sectors=rule.get("sectors", []),
        ))
    if direct and not result:
        result.append(ExposureRelationship(
            factor="COMPANY_EVENT", mechanism="direct company event exposure", direction="UNCERTAIN",
            strength="HIGH", linked_companies=[direct],
        ))
    return result


def assess_market_quality(*, observed_at: Any, volume: Any = None, liquidity: Any = None,
                          bid: Any = None, ask: Any = None, resolution_criteria: str | None = None,
                          provider: str | None = None, now: datetime | None = None) -> MarketQualityAssessment:
    current = now or datetime.now(timezone.utc)
    observed = _utc(observed_at)
    age_hours = None if observed is None else max(0.0, (current - observed).total_seconds() / 3600)
    stale = age_hours is None or age_hours > 72
    freshness: Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"] = (
        "UNKNOWN" if age_hours is None else "HIGH" if age_hours <= 24 else "MODERATE" if age_hours <= 72 else "LOW"
    )
    bid_value, ask_value = _float(bid), _float(ask)
    spread = None if bid_value is None or ask_value is None else max(0.0, ask_value - bid_value)
    activity = max(_float(volume) or 0.0, _float(liquidity) or 0.0)
    liquidity_level: Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"]
    if spread is None and activity <= 0:
        liquidity_level = "UNKNOWN"
    elif (spread is not None and spread <= 0.05) and activity >= 10_000:
        liquidity_level = "HIGH"
    elif (spread is None or spread <= 0.15) and activity >= 1_000:
        liquidity_level = "MODERATE"
    else:
        liquidity_level = "LOW"
    criteria = [f"Quote freshness: {freshness}", f"Liquidity evidence: {liquidity_level}"]
    if spread is not None:
        criteria.append(f"Bid/ask spread: {spread * 100:.1f} percentage points")
    criteria.append("Resolution criteria supplied" if resolution_criteria else "Resolution criteria unavailable")
    recognized = (provider or "").lower() in {"kalshi", "polymarket"}
    if observed is None or (liquidity_level == "UNKNOWN" and not resolution_criteria):
        level: MarketQuality = "INSUFFICIENT_DATA"
    elif stale or liquidity_level == "LOW":
        level = "LOW"
    elif freshness == "HIGH" and liquidity_level == "HIGH" and recognized and resolution_criteria:
        level = "HIGH"
    else:
        level = "MODERATE"
    return MarketQualityAssessment(level=level, freshness=freshness, liquidity=liquidity_level,
                                   criteria=criteria, stale=stale)


def probability_change(history: list[dict[str, Any]], current_probability: float,
                       current_as_of: Any, quality: MarketQuality) -> dict[str, Any]:
    current_time = _utc(current_as_of) or datetime.now(timezone.utc)
    prior_rows = sorted(
        ((stamp, value) for row in history
         if (stamp := _utc(row.get("observed_at"))) and stamp < current_time
         and (value := _float(row.get("probability"))) is not None), key=lambda item: item[0]
    )
    if not prior_rows:
        return {"previous_probability": None, "percentage_point_change": None, "relative_percent_change": None,
                "materiality": "UNKNOWN", "quality_adjusted_attention": "LOW", "volatility_points": None,
                "largest_jump_points": None, "methodology": "probability-change-v1"}
    previous = prior_rows[-1][1]
    pp = (current_probability - previous) * 100
    relative = None if previous == 0 else (current_probability - previous) / previous * 100
    magnitude = abs(pp)
    materiality = "HIGH" if magnitude >= 15 else "MEDIUM" if magnitude >= 5 else "LOW" if magnitude >= 1 else "NONE"
    attention = materiality
    if quality in {"LOW", "INSUFFICIENT_DATA"} and MATERIALITY_ORDER[attention] > 1:
        attention = "MEDIUM" if attention == "HIGH" else "LOW"
    values = [row[1] for row in prior_rows] + [current_probability]
    jumps = [abs((values[index] - values[index - 1]) * 100) for index in range(1, len(values))]
    return {
        "previous_probability": round(previous, 4), "percentage_point_change": round(pp, 2),
        "relative_percent_change": None if relative is None else round(relative, 2), "materiality": materiality,
        "quality_adjusted_attention": attention,
        "volatility_points": round(statistics.pstdev(values) * 100, 2) if len(values) > 1 else None,
        "largest_jump_points": round(max(jumps), 2) if jumps else None,
        "methodology": "probability-change-v1",
    }


def _event_key(row: dict[str, Any], factors: list[str]) -> str:
    series = row.get("series_key") or row.get("canonical_scenario")
    if series:
        return str(series)
    if factors:
        return factors[0]
    clean = re.sub(r"[^a-z0-9]+", "-", str(row.get("title") or row.get("market_id") or "market").lower()).strip("-")
    return clean[:100]


def _affected_theses(thesis_rows: list[dict[str, Any]], exposures: list[ExposureRelationship]) -> list[dict[str, Any]]:
    factors = {item.factor for item in exposures}
    terms = {term for factor in factors for term in factor.lower().split("_") if len(term) > 3}
    affected: list[dict[str, Any]] = []
    for thesis in thesis_rows:
        ticker = thesis["ticker"]
        direct = any(ticker in item.linked_companies for item in exposures)
        matches = []
        for assumption in thesis.get("assumptions", []):
            text = f"{assumption.get('description', '')} {assumption.get('category', '')}".lower()
            if direct or any(term in text for term in terms):
                matches.append({"id": assumption.get("id"), "description": assumption.get("description")})
        if direct or matches:
            affected.append({"thesis_id": thesis["id"], "ticker": ticker, "assumptions": matches,
                             "relationship": "DIRECT_ENTITY" if direct else "FACTOR_MATCH"})
    return affected


def build_intelligence(user_id: str, *, ticker: str | None = None, query: str | None = None,
                       limit: int = 50, holdings: list[dict[str, Any]] | None = None,
                       thesis_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    raw = database.prediction_market_observations(limit=max(100, limit * 4))
    if holdings is None:
        portfolios = database.list_portfolios(user_id)
        holdings = (portfolios[0].get("holdings") if portfolios else []) or []
    holding_tickers = {str(item.get("ticker") or "").upper() for item in holdings}
    if thesis_rows is None:
        thesis_rows = theses.list_theses(user_id)
    observations: list[PredictionMarketObservation] = []
    for row in raw:
        title = str(row.get("title") or row.get("question") or "Untitled market")
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if row.get("canonical_scenario"):
            metadata = {**metadata, "canonical_scenario": row["canonical_scenario"]}
        category, factors = classify_market(title, metadata)
        exposures = map_exposures(title, metadata)
        linked = sorted({company for item in exposures for company in item.linked_companies})
        affected_holdings = sorted(holding_tickers.intersection(linked))
        direct_ticker = str(metadata.get("ticker") or "").upper()
        if direct_ticker in holding_tickers and direct_ticker not in affected_holdings:
            affected_holdings.append(direct_ticker)
        if ticker and ticker.upper() not in linked and ticker.upper() != direct_ticker:
            continue
        if query and query.lower() not in f"{title} {' '.join(factors)} {' '.join(linked)}".lower():
            continue
        observed_at = _utc(row.get("observed_at")) or datetime.now(timezone.utc)
        probability = _float(row.get("probability"))
        if probability is None:
            continue
        quality = assess_market_quality(
            observed_at=observed_at, volume=row.get("volume"), liquidity=row.get("liquidity"),
            bid=row.get("bid"), ask=row.get("ask"), resolution_criteria=row.get("resolution_criteria"),
            provider=str(row.get("provider") or ""),
        )
        history = row.get("history") if isinstance(row.get("history"), list) else []
        change = probability_change(history, probability, observed_at, quality.level)
        affected = _affected_theses(thesis_rows, exposures)
        resolution = _utc(row.get("resolution_date") or row.get("closes_at"))
        days_to_resolution = None if resolution is None else (resolution - datetime.now(timezone.utc)).days
        upcoming = 2 if days_to_resolution is not None and 0 <= days_to_resolution <= 30 else 0
        relevance = QUALITY_ORDER[quality.level] * 4 + MATERIALITY_ORDER.get(change["quality_adjusted_attention"], 0) * 4
        relevance += min(8, len(affected_holdings) * 4) + min(8, len(affected) * 4) + upcoming
        bid, ask = _float(row.get("bid")), _float(row.get("ask"))
        observations.append(PredictionMarketObservation(
            provider=str(row.get("provider") or "Unknown"), market_id=str(row.get("market_id") or row.get("id")),
            event_key=_event_key(row, factors), title=title, description=row.get("description"), category=category,
            outcome=str(row.get("outcome") or "YES"),
            probability=ProbabilityValue(source_type="MARKET_IMPLIED", probability=probability, as_of=observed_at,
                                         source=str(row.get("provider") or "Unknown"), methodology="venue probability snapshot"),
            market_opened_at=_utc(row.get("market_opened_at") or row.get("opens_at")), resolution_date=resolution,
            resolution_criteria=row.get("resolution_criteria"), status=str(row.get("status") or ("RESOLVED" if row.get("resolved_outcome") is not None else "OPEN")),
            liquidity=_float(row.get("liquidity")), volume=_float(row.get("volume")), bid=bid, ask=ask,
            spread=None if bid is None or ask is None else round(max(0.0, ask - bid), 4),
            linked_companies=linked, linked_industries=sorted({v for item in exposures for v in item.linked_industries}),
            linked_macro_factors=factors, linked_portfolio_factors=sorted({item.factor for item in exposures}),
            event_tags=factors, source_url=row.get("source_url") or row.get("source"), quality=quality,
            change=change, exposures=exposures, affected_holdings=affected_holdings, affected_theses=affected,
            relevance_score=relevance,
        ))
    observations.sort(key=lambda item: (item.relevance_score, item.probability.as_of), reverse=True)
    disagreement: list[dict[str, Any]] = []
    grouped: dict[str, list[PredictionMarketObservation]] = {}
    for item in observations:
        grouped.setdefault(item.event_key, []).append(item)
    for key, items in grouped.items():
        providers = {item.provider.lower() for item in items}
        values = [item.probability.probability for item in items]
        if len(providers) > 1 and max(values) - min(values) >= 0.10:
            disagreement.append({"event_key": key, "agreement": "LOW", "range": [min(values), max(values)],
                                 "markets": [{"provider": item.provider, "market_id": item.market_id,
                                              "probability": item.probability.probability} for item in items],
                                 "methodology": "No aggregation; venue probabilities are shown separately."})
    return {"markets": [item.model_dump(mode="json") for item in observations[:limit]],
            "disagreements": disagreement, "as_of": datetime.now(timezone.utc).isoformat(),
            "methodology": "prediction-intelligence-v1", "warnings": [] if raw else ["Prediction-market evidence unavailable."]}


def compare_probabilities(user_probability: float, market_probability: float | None,
                          model_probability: float | None = None) -> dict[str, Any]:
    return {
        "user_vs_market_points": None if market_probability is None else round((user_probability - market_probability) * 100, 2),
        "user_vs_model_points": None if model_probability is None else round((user_probability - model_probability) * 100, 2),
        "interpretation": (
            "Market comparison unavailable." if market_probability is None else
            "You assign materially higher odds than the current market-implied probability." if user_probability - market_probability >= .10 else
            "You assign materially lower odds than the current market-implied probability." if market_probability - user_probability >= .10 else
            "Your probability is broadly aligned with the current market-implied probability."
        ),
    }


def get_forecast(target: str, horizon: str, as_of: datetime | None = None) -> dict[str, Any]:
    snapshot = database.latest_scenario_snapshot() or {}
    scenario = next((row for row in snapshot.get("scenarios", []) if row.get("key") == target), None)
    if not scenario:
        return {"status": "UNAVAILABLE", "target": target, "horizon": horizon,
                "message": "Forecast unavailable: no approved model output exists for this target."}
    basis = scenario.get("evidence_basis")
    source_type: ProbabilitySource = "COMPOSITE" if basis == "blended" else "MARKET_IMPLIED" if basis == "prediction_market" else "MODEL"
    if basis == "disclosed_prior":
        source_type = "MODEL"
    return {
        "status": "AVAILABLE", "target": target, "forecast_type": source_type,
        "point_estimate": scenario["probability"], "distribution": None, "range": None, "horizon": horizon,
        "input_data_as_of": scenario.get("as_of") or snapshot.get("fetched_at"),
        "methodology": basis or "disclosed_prior", "model_version": scenario.get("probability_model", "independent_conditions_v1"),
        "assumptions": ["Scenario conditions may overlap and are not forced into a single 100% distribution."],
        "data_coverage": "REDUCED" if scenario.get("is_prior") else "AVAILABLE",
        "sources": scenario.get("sources", []), "confidence": scenario.get("confidence"),
    }
