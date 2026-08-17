from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import database
from .analysis import _valuation_evidence
from .resilience import TTLCache


EvidenceType = Literal[
    "FUNDAMENTAL", "VALUATION", "ESTIMATE", "EARNINGS", "GUIDANCE",
    "PRICE_MARKET", "NEWS", "MACRO", "PREDICTION_MARKET", "PORTFOLIO", "RISK", "EVENT",
]
EvidenceValueKind = Literal["NUMERIC", "BOOLEAN", "CATEGORICAL", "EVENT", "QUALITATIVE"]
EvidenceAvailability = Literal["AVAILABLE", "UNAVAILABLE", "UNSUPPORTED", "DISAGREEMENT"]
EvidenceQuality = Literal["HIGH", "MEDIUM", "LOW", "UNAVAILABLE"]
Freshness = Literal["CURRENT", "STALE", "UNAVAILABLE"]
BaselineType = Literal[
    "LAST_THESIS_REVIEW", "LAST_RESEARCH_REVIEW", "LAST_DECISION", "PREVIOUS_EARNINGS",
    "ONE_DAY", "SEVEN_DAYS", "THIRTY_DAYS", "CUSTOM_DATE",
]
ChangeStatus = Literal[
    "CHANGED", "UNCHANGED", "ADDED", "REMOVED", "MISSING_BASELINE", "MISSING_CURRENT",
    "SOURCE_DISAGREEMENT", "UNSUPPORTED",
]
Direction = Literal["UP", "DOWN", "UNCHANGED", "CHANGED", "ADDED", "REMOVED", "UNKNOWN"]
Materiality = Literal["NONE", "LOW", "MEDIUM", "HIGH", "UNKNOWN"]


ALL_EVIDENCE_TYPES: tuple[EvidenceType, ...] = (
    "FUNDAMENTAL", "VALUATION", "ESTIMATE", "EARNINGS", "GUIDANCE", "PRICE_MARKET",
    "NEWS", "MACRO", "PREDICTION_MARKET", "PORTFOLIO", "RISK", "EVENT",
)


class EvidenceObservation(BaseModel):
    id: str
    entity_type: Literal["SECURITY", "MACRO", "PORTFOLIO", "MARKET"] = "SECURITY"
    entity_key: str
    evidence_type: EvidenceType
    metric: str
    label: str
    value_kind: EvidenceValueKind
    value: float | bool | str | None = None
    normalized_value: float | None = None
    unit: str | None = None
    effective_date: datetime | None = None
    observed_at: datetime
    source: str
    provider: str
    source_reference: str | None = None
    freshness: Freshness
    evidence_quality: EvidenceQuality
    availability: EvidenceAvailability = "AVAILABLE"
    metadata: dict[str, Any] = Field(default_factory=dict)
    methodology: str | None = None


class BaselineSelection(BaseModel):
    requested: BaselineType
    resolved: BaselineType
    as_of: datetime
    reference_id: str | None = None
    source: str
    fallback_reason: str | None = None


class EvidenceChange(BaseModel):
    evidence_type: EvidenceType
    metric: str
    label: str
    status: ChangeStatus
    previous_value: float | bool | str | None = None
    current_value: float | bool | str | None = None
    unit: str | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    percentage_point_change: float | None = None
    direction: Direction
    materiality: Materiality
    previous_as_of: datetime | None = None
    current_as_of: datetime | None = None
    source: str
    sources: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    freshness: Freshness
    evidence_quality: EvidenceQuality
    interpretation: None = None
    methodology: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceCoverage(BaseModel):
    evidence_type: EvidenceType
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE", "UNSUPPORTED", "UNCHANGED"]
    observation_count: int = 0
    message: str


class EvidenceChangeSet(BaseModel):
    entity: str
    entity_type: str = "SECURITY"
    baseline: BaselineSelection
    baseline_as_of: datetime
    current_as_of: datetime
    changes: list[EvidenceChange]
    coverage: list[EvidenceCoverage]
    summary: dict[str, int]
    calculation_version: Literal["evidence-change-v1"] = "evidence-change-v1"
    generated_at: datetime
    warnings: list[str] = Field(default_factory=list)


class MetricPolicy(BaseModel):
    mode: Literal["PERCENT", "ABSOLUTE", "PERCENTAGE_POINT", "EVENT", "CATEGORICAL"]
    medium: float
    high: float


# Thresholds are centralized and deliberately domain-specific. They determine
# attention materiality, never whether a change is good or bad.
DEFAULT_MATERIALITY_POLICY: dict[str, MetricPolicy] = {
    "price.close": MetricPolicy(mode="PERCENT", medium=3.0, high=8.0),
    "valuation.pe": MetricPolicy(mode="PERCENT", medium=5.0, high=15.0),
    "valuation.price_to_sales": MetricPolicy(mode="PERCENT", medium=5.0, high=15.0),
    "valuation.fcf_yield": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.75, high=2.0),
    "fundamental.revenue_yoy": MetricPolicy(mode="PERCENTAGE_POINT", medium=2.0, high=6.0),
    "fundamental.eps_yoy": MetricPolicy(mode="PERCENTAGE_POINT", medium=3.0, high=10.0),
    "fundamental.free_cash_flow_yoy": MetricPolicy(mode="PERCENTAGE_POINT", medium=5.0, high=15.0),
    "fundamental.gross_margin": MetricPolicy(mode="PERCENTAGE_POINT", medium=1.0, high=3.0),
    "fundamental.operating_margin": MetricPolicy(mode="PERCENTAGE_POINT", medium=1.0, high=3.0),
    "fundamental.net_margin": MetricPolicy(mode="PERCENTAGE_POINT", medium=1.0, high=3.0),
    "fundamental.total_debt": MetricPolicy(mode="PERCENT", medium=5.0, high=15.0),
    "fundamental.cash": MetricPolicy(mode="PERCENT", medium=5.0, high=15.0),
    "fundamental.shares_diluted": MetricPolicy(mode="PERCENT", medium=1.0, high=3.0),
    "estimate.consensus": MetricPolicy(mode="PERCENT", medium=2.0, high=6.0),
    "macro.CPIAUCSL": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.2, high=0.5),
    "macro.PCEPI": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.2, high=0.5),
    "macro.UNRATE": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.2, high=0.5),
    "macro.FEDFUNDS": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.25, high=0.5),
    "macro.DGS10": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.25, high=0.5),
    "macro.T10Y2Y": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.25, high=0.5),
    "macro.BAMLH0A0HYM2": MetricPolicy(mode="PERCENTAGE_POINT", medium=0.5, high=1.0),
    "prediction.probability": MetricPolicy(mode="PERCENTAGE_POINT", medium=5.0, high=15.0),
    "news.default": MetricPolicy(mode="EVENT", medium=1.0, high=2.0),
    "event.default": MetricPolicy(mode="EVENT", medium=1.0, high=2.0),
}

UNSUPPORTED_TYPES: dict[EvidenceType, str] = {
    "ESTIMATE": "Analyst-consensus estimate history is not connected for this security/provider.",
    "GUIDANCE": "Structured company-guidance history is not connected; guidance is not inferred from prose.",
}
MACRO_SERIES = ("CPIAUCSL", "PCEPI", "UNRATE", "FEDFUNDS", "DGS10", "T10Y2Y", "BAMLH0A0HYM2")
_CHANGE_CACHE = TTLCache(max_entries=128)


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return None if not math.isfinite(result) else result
    except (TypeError, ValueError):
        return None


def _observation_id(entity: str, evidence_type: str, metric: str, effective_date: Any, provider: str) -> str:
    identity = f"{entity}|{evidence_type}|{metric}|{_plain(effective_date)}|{provider}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _freshness(evidence_type: EvidenceType, effective_date: datetime | None, as_of: datetime) -> Freshness:
    if effective_date is None:
        return "UNAVAILABLE"
    age = max(0, (as_of - effective_date).days)
    limits = {"PRICE_MARKET": 5, "PREDICTION_MARKET": 3, "NEWS": 30, "EVENT": 45, "MACRO": 60, "FUNDAMENTAL": 180, "VALUATION": 10}
    return "CURRENT" if age <= limits.get(evidence_type, 90) else "STALE"


def _quality_from_score(value: Any) -> EvidenceQuality:
    score = _number(value)
    if score is None:
        return "UNAVAILABLE"
    return "HIGH" if score >= 0.75 else "MEDIUM" if score >= 0.45 else "LOW"


def _obs(
    *, entity: str, evidence_type: EvidenceType, metric: str, label: str,
    value: float | bool | str | None, value_kind: EvidenceValueKind, unit: str | None,
    effective_date: Any, observed_at: Any, provider: str, source_reference: str | None,
    quality: EvidenceQuality, as_of: datetime, metadata: dict[str, Any] | None = None,
    methodology: str | None = None, entity_type: Literal["SECURITY", "MACRO", "PORTFOLIO", "MARKET"] = "SECURITY",
) -> EvidenceObservation:
    effective = _utc(effective_date) if effective_date else None
    return EvidenceObservation(
        id=_observation_id(entity, evidence_type, metric, effective, provider), entity_type=entity_type,
        entity_key=entity, evidence_type=evidence_type, metric=metric, label=label,
        value_kind=value_kind, value=value, normalized_value=_number(value) if value_kind == "NUMERIC" else None,
        unit=unit, effective_date=effective, observed_at=_utc(observed_at), source=provider,
        provider=provider, source_reference=source_reference,
        freshness=_freshness(evidence_type, effective, as_of), evidence_quality=quality,
        metadata=metadata or {}, methodology=methodology,
    )


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: _plain(value) for key, value in dict(row).items()}


def load_history_bundle(ticker: str, baseline_as_of: datetime, current_as_of: datetime) -> dict[str, list[dict[str, Any]]]:
    """Load bounded raw histories once; adapters reconstruct both comparison states."""
    empty = {"prices": [], "fundamentals": [], "macro": [], "prediction_markets": [], "events": [], "news": [], "research": []}
    if not database.DATABASE_URL:
        return empty
    with database.postgres_connection() as conn:
        security = conn.execute(
            "SELECT id FROM public.securities WHERE ticker=%s AND active=true ORDER BY updated_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        security_id = security["id"] if security else None
        prices = [] if not security_id else conn.execute(
            """SELECT p.ts,p.adjusted_close,p.close,p.volume,p.provider,p.fetched_at
            FROM public.price_bars p WHERE p.security_id=%s AND p.interval='1d' AND p.ts<=%s
            ORDER BY p.ts DESC,p.fetched_at DESC LIMIT 800""", (security_id, current_as_of),
        ).fetchall()
        fundamentals = [] if not security_id else conn.execute(
            """SELECT period_end,fiscal_period,fiscal_year,metrics,data_quality_score,provider,source_url,fetched_at
            FROM public.fundamental_periods WHERE security_id=%s AND fetched_at<=%s
            ORDER BY period_end DESC,fetched_at DESC LIMIT 40""", (security_id, current_as_of),
        ).fetchall()
        macro = conn.execute(
            """SELECT series_id,observation_date,vintage_date,value,unit,provider,source_url,fetched_at
            FROM public.macro_observations WHERE series_id=ANY(%s) AND fetched_at<=%s
            ORDER BY series_id,observation_date DESC,vintage_date DESC LIMIT 500""", (list(MACRO_SERIES), current_as_of),
        ).fetchall()
        prediction = conn.execute(
            """SELECT pm.id AS market_id,pm.provider,pm.external_market_id,pm.title,pm.source_url,
            pm.closes_at,pm.canonical_scenario,pm.metadata,pms.observed_at,pms.probability,pms.bid,pms.ask,
            pms.volume,pms.open_interest,pms.order_book_depth,pms.confidence
            FROM public.prediction_markets pm JOIN public.prediction_market_snapshots pms ON pms.market_id=pm.id
            WHERE pms.observed_at<=%s AND (upper(pm.metadata->>'ticker')=%s OR pm.canonical_scenario IS NOT NULL)
            ORDER BY pm.id,pms.observed_at DESC LIMIT 600""", (current_as_of, ticker),
        ).fetchall()
        events = conn.execute(
            """SELECT id,provider,event_type,title,starts_at,tickers,source_url,metadata,fetched_at,
            event_status,timing_status,verified_at FROM public.market_events
            WHERE fetched_at<=%s AND (%s=ANY(tickers) OR event_type='macro_release')
            AND starts_at>=%s ORDER BY fetched_at DESC LIMIT 100""",
            (current_as_of, ticker, baseline_as_of - timedelta(days=30)),
        ).fetchall()
        news = [] if not security_id else conn.execute(
            """SELECT d.id,d.provider,d.title,d.source_url,d.published_at,d.fetched_at,d.content_hash,d.metadata
            FROM public.document_securities ds JOIN public.documents d ON d.id=ds.document_id
            WHERE ds.security_id=%s AND d.document_type='news' AND d.fetched_at<=%s
            AND coalesce(d.published_at,d.fetched_at)>=%s
            ORDER BY coalesce(d.published_at,d.fetched_at) DESC LIMIT 120""",
            (security_id, current_as_of, baseline_as_of - timedelta(days=14)),
        ).fetchall()
        research = [] if not security_id else conn.execute(
            """SELECT id,as_of,model_version,valuation_score,final_score,confidence,data_quality,metrics,risks,catalysts,lineage
            FROM public.security_research_snapshots WHERE security_id=%s AND as_of<=%s
            ORDER BY as_of DESC LIMIT 30""", (security_id, current_as_of),
        ).fetchall()
    return {key: [_row_dict(row) for row in rows] for key, rows in {
        "prices": prices, "fundamentals": fundamentals, "macro": macro,
        "prediction_markets": prediction, "events": events, "news": news, "research": research,
    }.items()}


def _fundamental_observations(ticker: str, rows: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    eligible = [row for row in rows if _utc(row["fetched_at"]) <= as_of and _utc(row["period_end"]) <= as_of]
    if not eligible:
        return []
    eligible.sort(key=lambda row: (_utc(row["period_end"]), _utc(row["fetched_at"])), reverse=True)
    latest = eligible[0]
    metrics = latest.get("metrics") or {}
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    comparable = next((row for row in eligible[1:] if row.get("fiscal_period") == latest.get("fiscal_period") and row.get("fiscal_year") != latest.get("fiscal_year")), None)
    previous = (comparable or {}).get("metrics") or {}
    if isinstance(previous, str):
        previous = json.loads(previous)
    provider = latest.get("provider") or "SEC Company Facts"
    quality = _quality_from_score(latest.get("data_quality_score"))
    if quality == "UNAVAILABLE":
        quality = "MEDIUM" if metrics else "LOW"
    effective, observed = latest["period_end"], latest["fetched_at"]
    source = latest.get("source_url")
    metadata = {"fiscal_period": latest.get("fiscal_period"), "fiscal_year": latest.get("fiscal_year"), "period_alignment": "latest reported period"}
    result: list[EvidenceObservation] = []

    def add(metric: str, label: str, value: float | None, unit: str, method: str, extra: dict[str, Any] | None = None) -> None:
        if value is not None:
            result.append(_obs(entity=ticker, evidence_type="FUNDAMENTAL", metric=metric, label=label, value=value,
                value_kind="NUMERIC", unit=unit, effective_date=effective, observed_at=observed, provider=provider,
                source_reference=source, quality=quality, as_of=as_of, metadata={**metadata, **(extra or {})}, methodology=method))

    revenue, prior_revenue = _number(metrics.get("revenue")), _number(previous.get("revenue"))
    eps, prior_eps = _number(metrics.get("eps_diluted")), _number(previous.get("eps_diluted"))
    fcf, prior_fcf = _number(metrics.get("free_cash_flow")), _number(previous.get("free_cash_flow"))
    add("fundamental.revenue_yoy", "Revenue growth, comparable period", (revenue / prior_revenue - 1) if revenue is not None and prior_revenue not in (None, 0) else None, "ratio", "comparable-period-yoy-v1", {"comparison_period_end": (comparable or {}).get("period_end")})
    add("fundamental.eps_yoy", "Diluted EPS growth, comparable period", (eps / prior_eps - 1) if eps is not None and prior_eps is not None and prior_eps > 0 else None, "ratio", "comparable-period-yoy-v1", {"comparison_period_end": (comparable or {}).get("period_end"), "unavailable_when_prior_nonpositive": True})
    add("fundamental.free_cash_flow_yoy", "Free cash flow growth, comparable period", (fcf / prior_fcf - 1) if fcf is not None and prior_fcf is not None and prior_fcf > 0 else None, "ratio", "comparable-period-yoy-v1", {"comparison_period_end": (comparable or {}).get("period_end"), "unavailable_when_prior_nonpositive": True})
    gross, operating, net_income = _number(metrics.get("gross_profit")), _number(metrics.get("operating_income")), _number(metrics.get("net_income"))
    if revenue not in (None, 0):
        add("fundamental.gross_margin", "Gross margin", None if gross is None else gross / revenue, "ratio", "reported-period-margin-v1")
        add("fundamental.operating_margin", "Operating margin", None if operating is None else operating / revenue, "ratio", "reported-period-margin-v1")
        add("fundamental.net_margin", "Net margin", None if net_income is None else net_income / revenue, "ratio", "reported-period-margin-v1")
    for key, label, unit in (("total_debt", "Total debt", "USD"), ("cash", "Cash and equivalents", "USD"), ("shares_diluted", "Diluted share count", "shares")):
        add(f"fundamental.{key}", label, _number(metrics.get(key)), unit, "reported-period-level-v1")
    return result


def _valuation_observations(ticker: str, fundamentals: list[dict[str, Any]], prices: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    eligible_periods = [row for row in fundamentals if _utc(row["fetched_at"]) <= as_of and _utc(row["period_end"]) <= as_of]
    eligible_prices = [row for row in prices if _utc(row["ts"]) <= as_of]
    if not eligible_periods or not eligible_prices:
        return []
    period = max(eligible_periods, key=lambda row: (_utc(row["period_end"]), _utc(row["fetched_at"])))
    price = max(eligible_prices, key=lambda row: (_utc(row["ts"]), _utc(row["fetched_at"])))
    metrics = period.get("metrics") or {}
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    result = _valuation_evidence(imported_score=None, price=_number(price.get("adjusted_close") or price.get("close")), metrics=metrics, fiscal_period=period.get("fiscal_period"))
    raw = result.get("raw_metrics") or {}
    observations = []
    for key, label, unit in (("pe", "Price / earnings", "multiple"), ("price_to_sales", "Price / sales", "multiple"), ("free_cash_flow_yield", "Free cash flow yield", "ratio")):
        value = _number(raw.get(key))
        if value is not None:
            observations.append(_obs(entity=ticker, evidence_type="VALUATION", metric=f"valuation.{key}", label=label,
                value=value, value_kind="NUMERIC", unit=unit, effective_date=price["ts"], observed_at=price["fetched_at"],
                provider=result.get("source") or "stored valuation inputs", source_reference=period.get("source_url"),
                quality="HIGH" if len(result.get("components") or []) >= 3 else "MEDIUM", as_of=as_of,
                metadata={"fundamental_period_end": period.get("period_end"), "fiscal_period": period.get("fiscal_period")}, methodology=result.get("method")))
    return observations


def _price_observations(ticker: str, rows: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    eligible = [row for row in rows if _utc(row["ts"]) <= as_of]
    if not eligible:
        return []
    row = max(eligible, key=lambda item: (_utc(item["ts"]), _utc(item["fetched_at"])))
    value = _number(row.get("adjusted_close") or row.get("close"))
    if value is None:
        return []
    provider = row.get("provider") or "stored adjusted prices"
    return [_obs(entity=ticker, evidence_type="PRICE_MARKET", metric="price.close", label="Adjusted closing price",
        value=value, value_kind="NUMERIC", unit="USD", effective_date=row["ts"], observed_at=row["fetched_at"],
        provider=provider, source_reference=None, quality="HIGH", as_of=as_of,
        metadata={"latency": "end-of-day"}, methodology="canonical-adjusted-close-v1")]


def _macro_observations(rows: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _utc(row["fetched_at"]) <= as_of and _utc(row["observation_date"]) <= as_of:
            grouped[str(row["series_id"])].append(row)
    labels = {"CPIAUCSL": "Consumer price index", "PCEPI": "PCE price index", "UNRATE": "Unemployment rate", "FEDFUNDS": "Federal funds rate", "DGS10": "10-year Treasury yield", "T10Y2Y": "10y–2y Treasury spread", "BAMLH0A0HYM2": "High-yield credit spread"}
    result = []
    for series, values in grouped.items():
        row = max(values, key=lambda item: (_utc(item["observation_date"]), _utc(item["vintage_date"])))
        value = _number(row.get("value"))
        if value is None:
            continue
        methodology = "point-in-time-macro-v1"
        unit = row.get("unit") or ("percent" if series in {"UNRATE","FEDFUNDS","DGS10","T10Y2Y","BAMLH0A0HYM2"} else "index")
        if series in {"CPIAUCSL", "PCEPI"}:
            target = _utc(row["observation_date"]) - timedelta(days=365)
            prior = min((item for item in values if _utc(item["observation_date"]) < _utc(row["observation_date"])), key=lambda item: abs((_utc(item["observation_date"]) - target).days), default=None)
            prior_value = _number((prior or {}).get("value"))
            if prior is None or prior_value in (None, 0) or abs((_utc(prior["observation_date"]) - target).days) > 45:
                continue
            value = (value / prior_value - 1) * 100
            unit, methodology = "percent", "point-in-time-inflation-yoy-v1"
        result.append(_obs(entity="MACRO", entity_type="MACRO", evidence_type="MACRO", metric=f"macro.{series}",
            label=(f"{labels.get(series, series)} year-over-year" if series in {"CPIAUCSL", "PCEPI"} else labels.get(series, series)), value=value, value_kind="NUMERIC", unit=unit,
            effective_date=row["observation_date"], observed_at=row["fetched_at"], provider=row.get("provider") or "FRED",
            source_reference=row.get("source_url"), quality="HIGH", as_of=as_of,
            metadata={"vintage_date": row.get("vintage_date"), "series_id": series}, methodology=methodology))
    return result


def prediction_market_quality(row: dict[str, Any], as_of: datetime) -> tuple[EvidenceQuality, dict[str, Any]]:
    from .forecasting import assess_market_quality
    assessment = assess_market_quality(
        observed_at=row.get("observed_at"), volume=row.get("volume"), liquidity=row.get("liquidity"),
        bid=row.get("bid"), ask=row.get("ask"), resolution_criteria=row.get("resolution_criteria"),
        provider=row.get("provider"), now=as_of,
    )
    mapped: EvidenceQuality = {"HIGH": "HIGH", "MODERATE": "MEDIUM", "LOW": "LOW",
                               "INSUFFICIENT_DATA": "UNAVAILABLE"}[assessment.level]
    observed = _utc(row["observed_at"])
    age_hours = max(0.0, (as_of - observed).total_seconds() / 3600)
    return mapped, {"market_quality": mapped, "forecast_market_quality": assessment.level,
                    "freshness_hours": round(age_hours, 2), "freshness": assessment.freshness,
                    "liquidity": assessment.liquidity, "stale": assessment.stale,
                    "criteria": assessment.criteria, "methodology": assessment.methodology}


def _prediction_observations(rows: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _utc(row["observed_at"]) <= as_of:
            grouped[str(row["market_id"])].append(row)
    result = []
    for market_id, values in grouped.items():
        row = max(values, key=lambda item: _utc(item["observed_at"]))
        probability = _number(row.get("probability"))
        if probability is None:
            continue
        quality, quality_metadata = prediction_market_quality(row, as_of)
        provider = str(row.get("provider") or "prediction market")
        closes_at = row.get("closes_at")
        status = "closed" if closes_at and _utc(closes_at) < as_of else "open"
        result.append(_obs(entity=str((row.get("metadata") or {}).get("ticker") or "MARKET"), entity_type="MARKET",
            evidence_type="PREDICTION_MARKET", metric=f"prediction:{provider}:{row.get('external_market_id')}",
            label=row.get("title") or "Prediction market", value=probability, value_kind="NUMERIC", unit="probability",
            effective_date=row["observed_at"], observed_at=row["observed_at"], provider=provider,
            source_reference=row.get("source_url"), quality=quality, as_of=as_of,
            metadata={**quality_metadata, "market_id": row.get("external_market_id"), "resolution_date": closes_at,
                "category": (row.get("metadata") or {}).get("evidence_type") or row.get("canonical_scenario"),
                "linked_entities": [value for value in [(row.get("metadata") or {}).get("ticker")] if value],
                "linked_macro_factors": [value for value in [row.get("canonical_scenario")] if value],
                "market_status": status, "probability_context": "Market-derived evidence, not objective truth."},
            methodology="venue-probability-snapshot-v1"))
    return result


def _event_observations(ticker: str, rows: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    result = []
    for row in rows:
        fetched = _utc(row["fetched_at"])
        if fetched > as_of:
            continue
        event_type = "EARNINGS" if row.get("event_type") == "earnings" else "MACRO" if row.get("event_type") == "macro_release" else "EVENT"
        metadata = row.get("metadata") or {}
        result.append(_obs(entity=ticker if ticker in (row.get("tickers") or []) else "MACRO", evidence_type=event_type,
            metric=f"event:{row['id']}", label=row.get("title") or "Market event", value=str(row.get("title") or "Market event"),
            value_kind="EVENT", unit=None, effective_date=row.get("starts_at"), observed_at=row.get("verified_at") or fetched,
            provider=row.get("provider") or "event provider", source_reference=row.get("source_url"),
            quality="HIGH" if row.get("timing_status") == "confirmed" else "MEDIUM", as_of=as_of,
            metadata={**metadata, "event_type": row.get("event_type"), "event_status": row.get("event_status"),
                "timing_status": row.get("timing_status")}, methodology="structured-market-event-v1"))
    return result


def _news_observations(ticker: str, rows: list[dict[str, Any]], as_of: datetime) -> list[EvidenceObservation]:
    result = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: _utc(item.get("published_at") or item["fetched_at"]), reverse=True):
        if _utc(row["fetched_at"]) > as_of or (row.get("published_at") and _utc(row["published_at"]) > as_of):
            continue
        title = " ".join(str(row.get("title") or "Untitled news item").lower().split())
        identity = str(row.get("content_hash") or hashlib.sha256(title.encode()).hexdigest())
        if identity in seen:
            continue
        seen.add(identity)
        metadata = row.get("metadata") or {}
        provider = str(row.get("provider") or metadata.get("source") or "news provider")
        result.append(_obs(
            entity=ticker, evidence_type="NEWS", metric=f"news:{identity[:24]}", label=str(row.get("title") or "Untitled news item"),
            value=str(row.get("title") or "Untitled news item"), value_kind="EVENT", unit=None,
            effective_date=row.get("published_at") or row["fetched_at"], observed_at=row["fetched_at"], provider=provider,
            source_reference=row.get("source_url"), quality="HIGH" if row.get("source_url") and row.get("published_at") else "MEDIUM",
            as_of=as_of, metadata={"novelty_key": identity, "publisher": metadata.get("source"), "credibility_method": "provenance-completeness-only"},
            methodology="content-hash-news-novelty-v1",
        ))
    return result


def observations_from_bundle(ticker: str, bundle: dict[str, list[dict[str, Any]]], as_of: datetime) -> list[EvidenceObservation]:
    return deduplicate_observations([
        *_price_observations(ticker, bundle.get("prices", []), as_of),
        *_fundamental_observations(ticker, bundle.get("fundamentals", []), as_of),
        *_valuation_observations(ticker, bundle.get("fundamentals", []), bundle.get("prices", []), as_of),
        *_macro_observations(bundle.get("macro", []), as_of),
        *_prediction_observations(bundle.get("prediction_markets", []), as_of),
        *_news_observations(ticker, bundle.get("news", []), as_of),
        *_event_observations(ticker, bundle.get("events", []), as_of),
    ])


def deduplicate_observations(observations: list[EvidenceObservation]) -> list[EvidenceObservation]:
    groups: dict[tuple[str, str, str], list[EvidenceObservation]] = defaultdict(list)
    for item in observations:
        groups[(item.entity_key, item.evidence_type, item.metric)].append(item)
    result = []
    quality_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNAVAILABLE": 0}
    for _, values in groups.items():
        if len(values) == 1:
            result.append(values[0]); continue
        unique_values = {json.dumps(_plain(item.value), sort_keys=True) for item in values}
        best = max(values, key=lambda item: (quality_rank[item.evidence_quality], item.observed_at))
        sources = sorted({item.provider for item in values})
        if len(unique_values) == 1:
            result.append(best.model_copy(update={"source": ", ".join(sources), "metadata": {**best.metadata, "supporting_sources": sources}}))
        else:
            result.append(best.model_copy(update={
                "value": None, "normalized_value": None, "availability": "DISAGREEMENT", "evidence_quality": "LOW",
                "source": ", ".join(sources), "metadata": {**best.metadata, "source_disagreement": [
                    {"provider": item.provider, "value": _plain(item.value), "observed_at": item.observed_at.isoformat()} for item in values
                ]},
            }))
    return sorted(result, key=lambda item: (item.evidence_type, item.metric))


def _policy_for(item: EvidenceObservation) -> MetricPolicy:
    if item.metric.startswith("prediction:"):
        return DEFAULT_MATERIALITY_POLICY["prediction.probability"]
    if item.metric.startswith("event:"):
        return DEFAULT_MATERIALITY_POLICY["event.default"]
    if item.metric.startswith("news:"):
        return DEFAULT_MATERIALITY_POLICY["news.default"]
    return DEFAULT_MATERIALITY_POLICY.get(item.metric, MetricPolicy(mode="PERCENT", medium=5.0, high=15.0))


def _materiality(magnitude: float | None, policy: MetricPolicy, quality: EvidenceQuality, freshness: Freshness) -> Materiality:
    if magnitude is None:
        return "UNKNOWN"
    level: Materiality = "HIGH" if magnitude >= policy.high else "MEDIUM" if magnitude >= policy.medium else "LOW" if magnitude > 0 else "NONE"
    if freshness == "STALE" and level == "HIGH":
        level = "MEDIUM"
    if quality in {"LOW", "UNAVAILABLE"} and level == "HIGH":
        level = "MEDIUM"
    return level


def compare_observations(
    previous: list[EvidenceObservation], current: list[EvidenceObservation], *, include_low: bool = False,
) -> tuple[list[EvidenceChange], dict[str, int]]:
    before = {(item.evidence_type, item.metric): item for item in deduplicate_observations(previous)}
    after = {(item.evidence_type, item.metric): item for item in deduplicate_observations(current)}
    changes: list[EvidenceChange] = []
    counters = {"changed": 0, "unchanged": 0, "missing_baseline": 0, "missing_current": 0, "disagreement": 0, "low_suppressed": 0}
    for key in sorted(set(before) | set(after)):
        prior, now = before.get(key), after.get(key)
        item = now or prior
        assert item is not None
        status: ChangeStatus
        direction: Direction
        materiality: Materiality = "UNKNOWN"
        absolute = percent = points = None
        metadata: dict[str, Any] = {}
        if (prior and prior.availability == "DISAGREEMENT") or (now and now.availability == "DISAGREEMENT"):
            status, direction, materiality = "SOURCE_DISAGREEMENT", "UNKNOWN", "UNKNOWN"
            counters["disagreement"] += 1
            metadata["source_disagreement"] = (now or prior).metadata.get("source_disagreement", [])
        elif prior is None:
            status, direction = ("ADDED", "ADDED") if item.value_kind == "EVENT" else ("MISSING_BASELINE", "UNKNOWN")
            materiality = "MEDIUM" if item.value_kind == "EVENT" else "UNKNOWN"
            counters["missing_baseline"] += 1
        elif now is None:
            status, direction = ("REMOVED", "REMOVED") if item.value_kind == "EVENT" else ("MISSING_CURRENT", "UNKNOWN")
            materiality = "LOW" if item.value_kind == "EVENT" else "UNKNOWN"
            counters["missing_current"] += 1
        elif prior.value == now.value:
            status, direction, materiality = "UNCHANGED", "UNCHANGED", "NONE"
            counters["unchanged"] += 1
        elif prior.value_kind == "NUMERIC" and now.value_kind == "NUMERIC":
            previous_value, current_value = _number(prior.value), _number(now.value)
            if previous_value is None or current_value is None:
                status, direction = "MISSING_CURRENT", "UNKNOWN"
                counters["missing_current"] += 1
            else:
                status = "CHANGED"
                absolute = current_value - previous_value
                percent = None if abs(previous_value) < 1e-12 else absolute / abs(previous_value) * 100
                policy = _policy_for(now)
                if policy.mode == "PERCENTAGE_POINT":
                    points = round(absolute * 100 if now.unit in {"ratio", "probability"} else absolute, 12)
                    magnitude = abs(points)
                elif policy.mode == "ABSOLUTE":
                    magnitude = abs(absolute)
                else:
                    magnitude = abs(percent) if percent is not None else abs(absolute)
                direction = "UP" if absolute > 0 else "DOWN" if absolute < 0 else "UNCHANGED"
                materiality = _materiality(magnitude, policy, now.evidence_quality, now.freshness)
                counters["changed"] += 1
        else:
            status, direction, materiality = "CHANGED", "CHANGED", "MEDIUM"
            counters["changed"] += 1
        sources = sorted({value.provider for value in (prior, now) if value})
        references = sorted({value.source_reference for value in (prior, now) if value and value.source_reference})
        change = EvidenceChange(
            evidence_type=item.evidence_type, metric=item.metric, label=item.label, status=status,
            previous_value=prior.value if prior else None, current_value=now.value if now else None, unit=item.unit,
            absolute_change=absolute, percent_change=percent, percentage_point_change=points,
            direction=direction, materiality=materiality, previous_as_of=prior.effective_date if prior else None,
            current_as_of=now.effective_date if now else None, source=", ".join(sources) or item.source,
            sources=sources, source_references=references, freshness=(now or prior).freshness,
            evidence_quality=(now or prior).evidence_quality, methodology=(now or prior).methodology,
            metadata={**metadata, "previous_metadata": prior.metadata if prior else {}, "current_metadata": now.metadata if now else {}},
        )
        if include_low or materiality in {"MEDIUM", "HIGH", "UNKNOWN"} or status in {"MISSING_BASELINE", "MISSING_CURRENT", "SOURCE_DISAGREEMENT", "UNSUPPORTED"}:
            changes.append(change)
        elif status == "CHANGED" and materiality == "LOW":
            counters["low_suppressed"] += 1
    rank = {"HIGH": 0, "MEDIUM": 1, "UNKNOWN": 2, "LOW": 3, "NONE": 4}
    return sorted(changes, key=lambda item: (rank[item.materiality], item.evidence_type, item.metric)), counters


def select_baseline(user_id: str, ticker: str, requested: BaselineType, custom_date: datetime | None = None, current_as_of: datetime | None = None) -> BaselineSelection:
    now = current_as_of or datetime.now(timezone.utc)
    if requested == "CUSTOM_DATE":
        if custom_date is None:
            raise ValueError("custom_date is required for CUSTOM_DATE")
        return BaselineSelection(requested=requested, resolved=requested, as_of=custom_date, source="user-selected date")
    days = {"ONE_DAY": 1, "SEVEN_DAYS": 7, "THIRTY_DAYS": 30}
    if requested in days:
        return BaselineSelection(requested=requested, resolved=requested, as_of=now - timedelta(days=days[requested]), source="time window")
    if requested in {"LAST_THESIS_REVIEW", "LAST_DECISION", "LAST_RESEARCH_REVIEW"}:
        postgres = bool(database.DATABASE_URL)
        with (database.postgres_connection() if postgres else database.sqlite_connection()) as conn:
            p, prefix = ("%s", "public.") if postgres else ("?", "")
            row = None
            if requested == "LAST_THESIS_REVIEW":
                review_table = f"{prefix}thesis_review_events"
                row = conn.execute(
                    f"SELECT id,reviewed_at AS created_at FROM {review_table} WHERE user_id={p} AND ticker={p} ORDER BY reviewed_at DESC LIMIT 1",
                    (user_id, ticker),
                ).fetchone()
                source = "latest explicit thesis review"
                if row is None:
                    row = conn.execute(
                        f"""SELECT tv.id,tv.created_at FROM {prefix}thesis_versions tv JOIN {prefix}investment_theses t ON t.id=tv.thesis_id
                        WHERE tv.user_id={p} AND t.user_id={p} AND t.ticker={p} ORDER BY tv.version_number ASC LIMIT 1""",
                        (user_id, user_id, ticker),
                    ).fetchone()
                    source = "original thesis baseline"
            elif requested == "LAST_DECISION":
                row = conn.execute(
                    f"SELECT id,decision_date AS created_at FROM {prefix}investment_decisions WHERE user_id={p} AND ticker={p} ORDER BY decision_date DESC LIMIT 1",
                    (user_id, ticker),
                ).fetchone()
                source = "latest saved investment decision"
            elif requested == "LAST_RESEARCH_REVIEW":
                row = conn.execute(
                    f"""SELECT baseline_ref AS id,as_of AS created_at FROM {prefix}evidence_snapshots
                    WHERE user_id={p} AND entity_key={p} AND baseline_type='LAST_RESEARCH_REVIEW' ORDER BY as_of DESC LIMIT 1""",
                    (user_id, ticker),
                ).fetchone()
                source = "latest explicit research review"
            if row:
                return BaselineSelection(requested=requested, resolved=requested, as_of=_utc(row["created_at"]), reference_id=str(row["id"]), source=source)
    if requested == "PREVIOUS_EARNINGS" and database.DATABASE_URL:
        with database.postgres_connection() as conn:
            row = conn.execute(
                """SELECT id,coalesce(fetched_at,period_end::timestamptz) AS created_at FROM public.fundamental_periods f
                JOIN public.securities s ON s.id=f.security_id WHERE s.ticker=%s ORDER BY period_end DESC OFFSET 1 LIMIT 1""",
                (ticker,),
            ).fetchone()
            source = "previous reported fundamental period"
            if row:
                return BaselineSelection(requested=requested, resolved=requested, as_of=_utc(row["created_at"]), reference_id=str(row["id"]), source=source)
    fallback = now - timedelta(days=30)
    return BaselineSelection(requested=requested, resolved="THIRTY_DAYS", as_of=fallback, source="time window fallback", fallback_reason=f"{requested.replace('_', ' ').title()} is unavailable; using 30 days.")


def _saved_snapshot(user_id: str, ticker: str, baseline: BaselineSelection) -> list[EvidenceObservation] | None:
    if not baseline.reference_id:
        return None
    postgres = bool(database.DATABASE_URL)
    with (database.postgres_connection() if postgres else database.sqlite_connection()) as conn:
        p, prefix = ("%s", "public.") if postgres else ("?", "")
        column = "observations" if postgres else "observations_json"
        row = conn.execute(
            f"""SELECT {column} FROM {prefix}evidence_snapshots WHERE user_id={p} AND entity_key={p}
            AND baseline_type={p} AND baseline_ref={p} ORDER BY as_of DESC LIMIT 1""",
            (user_id, ticker, baseline.resolved, baseline.reference_id),
        ).fetchone()
    if not row:
        return None
    raw_value = row[column]
    raw = raw_value if not isinstance(raw_value, str) else json.loads(raw_value)
    return [EvidenceObservation.model_validate(item) for item in raw]


def capture_snapshot(user_id: str, ticker: str, baseline_type: BaselineType, baseline_ref: str, as_of: datetime | None = None) -> dict[str, Any] | None:
    captured_at = as_of or datetime.now(timezone.utc)
    bundle = load_history_bundle(ticker, captured_at - timedelta(days=365), captured_at)
    observations = observations_from_bundle(ticker, bundle, captured_at)[:150]
    snapshot_id = str(uuid.uuid4())
    postgres = bool(database.DATABASE_URL)
    with (database.postgres_connection() if postgres else database.sqlite_connection()) as conn:
        if postgres:
            row = conn.execute(
            """INSERT INTO public.evidence_snapshots
            (id,user_id,entity_type,entity_key,baseline_type,baseline_ref,as_of,observations,methodology_version)
            VALUES (%s,%s,'SECURITY',%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id,entity_key,baseline_type,baseline_ref) DO NOTHING RETURNING id""",
            (snapshot_id, user_id, ticker, baseline_type, baseline_ref, captured_at,
             database._jsonb([item.model_dump(mode="json") for item in observations]), "evidence-normalization-v1"),
            ).fetchone()
        else:
            conn.execute(
                """INSERT OR IGNORE INTO evidence_snapshots
                (id,user_id,entity_type,entity_key,baseline_type,baseline_ref,as_of,observations_json,methodology_version,created_at)
                VALUES (?,?, 'SECURITY',?,?,?,?,?,?,?)""",
                (snapshot_id, user_id, ticker, baseline_type, baseline_ref, captured_at.isoformat(),
                 json.dumps([item.model_dump(mode="json") for item in observations]), "evidence-normalization-v1", datetime.now(timezone.utc).isoformat()),
            )
            row = {"id": snapshot_id}
    return {"id": str(row["id"]) if row else None, "ticker": ticker, "as_of": captured_at.isoformat(), "observation_count": len(observations), "created": bool(row)}


def coverage_for(types: list[EvidenceType], previous: list[EvidenceObservation], current: list[EvidenceObservation], changes: list[EvidenceChange]) -> list[EvidenceCoverage]:
    result = []
    for evidence_type in types:
        if evidence_type in UNSUPPORTED_TYPES:
            result.append(EvidenceCoverage(evidence_type=evidence_type, status="UNSUPPORTED", message=UNSUPPORTED_TYPES[evidence_type])); continue
        before_count = sum(item.evidence_type == evidence_type for item in previous)
        after_count = sum(item.evidence_type == evidence_type for item in current)
        change_count = sum(item.evidence_type == evidence_type and item.status != "UNCHANGED" for item in changes)
        if not before_count and not after_count:
            status, message = "UNAVAILABLE", "No verified current or baseline observations are available."
        elif not before_count or not after_count:
            status, message = "PARTIAL", "Current or baseline coverage is unavailable; missing evidence is not treated as no change."
        elif not change_count:
            status, message = "UNCHANGED", "Comparable verified observations are available with no surfaced material change."
        else:
            status, message = "AVAILABLE", "Comparable verified observations are available."
        result.append(EvidenceCoverage(evidence_type=evidence_type, status=status, observation_count=after_count, message=message))
    return result


def get_changes(
    user_id: str, ticker: str, *, baseline_type: BaselineType = "LAST_THESIS_REVIEW",
    from_date: datetime | None = None, current_as_of: datetime | None = None,
    evidence_types: list[EvidenceType] | None = None, include_low: bool = False,
) -> EvidenceChangeSet:
    normalized = ticker.strip().upper()
    now = current_as_of or datetime.now(timezone.utc)
    baseline = select_baseline(user_id, normalized, "CUSTOM_DATE" if from_date else baseline_type, from_date, now)
    selected_types = evidence_types or list(ALL_EVIDENCE_TYPES)
    cache_key = f"{user_id}:{normalized}:{baseline.model_dump_json()}:{now.replace(second=0,microsecond=0).isoformat()}:{','.join(selected_types)}:{include_low}"
    cached = _CHANGE_CACHE.get(cache_key)
    if cached is not None:
        return EvidenceChangeSet.model_validate(cached)
    bundle = load_history_bundle(normalized, baseline.as_of, now)
    previous = _saved_snapshot(user_id, normalized, baseline) or observations_from_bundle(normalized, bundle, baseline.as_of)
    current = observations_from_bundle(normalized, bundle, now)
    previous = [item for item in previous if item.evidence_type in selected_types]
    current = [item for item in current if item.evidence_type in selected_types]
    changes, summary = compare_observations(previous, current, include_low=include_low)
    result = EvidenceChangeSet(
        entity=normalized, baseline=baseline, baseline_as_of=baseline.as_of, current_as_of=now,
        changes=changes[:60], coverage=coverage_for(selected_types, previous, current, changes), summary=summary,
        generated_at=datetime.now(timezone.utc), warnings=[baseline.fallback_reason] if baseline.fallback_reason else [],
    )
    _CHANGE_CACHE.put(cache_key, result.model_dump(mode="json"), ttl_seconds=60)
    return result


def get_changes_since_last_review(user_id: str, ticker: str, evidence_types: list[EvidenceType] | None = None) -> EvidenceChangeSet:
    return get_changes(user_id, ticker, baseline_type="LAST_THESIS_REVIEW", evidence_types=evidence_types)
