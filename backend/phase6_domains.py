from __future__ import annotations

import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import database, phase4_analytics, read_models
from .analytical_contract import (
    AnalysisResult,
    AnalysisStatus,
    Coverage,
    DependencyResult,
    Freshness,
    LineageItem,
    Prerequisite,
    VerificationCheck,
    VerificationResult,
    VerificationSeverity,
    build_freshness,
    parse_timestamp,
    stable_fingerprint,
)


DOMAIN_SCHEMA_VERSION = "1"
COMPANY_CALCULATION_VERSION = "company-analysis-v2-shared-research"
COMPARISON_CALCULATION_VERSION = "company-comparison-v1"
MACRO_CALCULATION_VERSION = "macro-state-v1"
MARKET_CALCULATION_VERSION = "market-state-v1"
PREDICTION_CALCULATION_VERSION = "prediction-market-state-v1"
HISTORICAL_CALCULATION_VERSION = "historical-comparison-v1"

MARKET_INDEXES = ("SPY", "QQQ", "IWM", "DIA")
MARKET_SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC")
MACRO_SERIES = (
    "FEDFUNDS", "DGS10", "T10Y2Y", "CPIAUCSL", "PCEPI", "INDPRO", "RSAFS", "PCE",
    "UNRATE", "PAYEMS", "ICSA", "BAMLH0A0HYM2", "DRCCLACBS", "TOTALSL",
)


class EvidenceQuality(BaseModel):
    level: Literal["HIGH", "MODERATE", "LOW", "INSUFFICIENT_DATA"]
    available_domains: list[str] = Field(default_factory=list)
    missing_domains: list[str] = Field(default_factory=list)
    methodology: str = "Coverage and freshness classification; not a probability."


class ChangeItem(BaseModel):
    domain: str
    metric: str
    previous: Any = None
    current: Any = None
    absolute_change: float | None = None
    percentage_point_change: float | None = None
    direction: Literal["IMPROVING", "DETERIORATING", "MIXED", "UP", "DOWN", "UNCHANGED", "UNKNOWN"]
    materiality: Literal["HIGH", "MEDIUM", "LOW", "NONE", "UNKNOWN"]
    methodology: str


class CompanyAnalysisResult(BaseModel):
    ticker: str
    identity: dict[str, Any]
    sector: str | None = None
    industry: str | None = None
    price_state: dict[str, Any]
    performance: dict[str, Any]
    fundamentals: dict[str, Any]
    fundamental_trend: dict[str, Any]
    profitability: dict[str, Any]
    balance_sheet: dict[str, Any]
    valuation: dict[str, Any]
    momentum: dict[str, Any]
    earnings_state: dict[str, Any]
    news_state: dict[str, Any]
    eagleeyes_score: float | None = None
    score_components: dict[str, Any]
    thesis_state: dict[str, Any]
    evidence_quality: EvidenceQuality
    freshness: dict[str, Any]
    lineage: list[dict[str, Any]]
    research_capabilities: dict[str, Any] = Field(default_factory=dict)


class CompanyComparisonResult(BaseModel):
    companies: list[dict[str, Any]]
    growth_comparison: list[dict[str, Any]]
    profitability_comparison: list[dict[str, Any]]
    valuation_comparison: list[dict[str, Any]]
    balance_sheet_comparison: list[dict[str, Any]]
    momentum_comparison: list[dict[str, Any]]
    earnings_comparison: list[dict[str, Any]]
    evidence_quality: dict[str, str]
    portfolio_fit: list[dict[str, Any]]
    portfolio_context_available: bool
    advantages: dict[str, list[str]]
    disadvantages: dict[str, list[str]]
    missing_fields: dict[str, list[str]]
    confidence: Literal["HIGH", "MODERATE", "LOW", "INSUFFICIENT_DATA"]


class MacroStateResult(BaseModel):
    effective_date: datetime | None = None
    observed_state: dict[str, Any]
    rates: dict[str, Any]
    inflation: dict[str, Any]
    growth: dict[str, Any]
    labor: dict[str, Any]
    liquidity: dict[str, Any]
    factor_states: list[dict[str, Any]]
    regime: dict[str, Any]
    changes: list[ChangeItem]
    risks: list[str]
    evidence_quality: EvidenceQuality
    freshness: dict[str, Any]
    lineage: list[dict[str, Any]]
    portfolio_exposures: list[dict[str, Any]] = Field(default_factory=list)
    forecast: None = None


class MarketStateResult(BaseModel):
    effective_date: datetime | None = None
    broad_market_trend: dict[str, Any]
    volatility_state: dict[str, Any]
    breadth: dict[str, Any]
    factor_leadership: list[dict[str, Any]]
    sector_leadership: list[dict[str, Any]]
    risk_on_off_state: dict[str, Any]
    valuation_state: dict[str, Any]
    regime: str
    material_changes: list[ChangeItem]
    evidence_quality: EvidenceQuality
    freshness: dict[str, Any]
    portfolio_fit: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketChange(BaseModel):
    event: str
    previous_probability: float | None = None
    current_probability: float
    delta_pp: float | None = None
    time_window: str
    mapped_portfolio_weight: float | None = None
    relevance: str


class PredictionMarketResult(BaseModel):
    markets: list[dict[str, Any]]
    changes: list[PredictionMarketChange]
    probability_types: list[str]
    provider_disagreements: list[dict[str, Any]]
    calibration_quality: str
    portfolio_context_available: bool
    evidence_quality: EvidenceQuality
    freshness: dict[str, Any]
    lineage: list[dict[str, Any]]


class PortfolioMacroExposureResult(BaseModel):
    macro_factor: str
    direction_state: str
    exposed_holdings: list[str]
    portfolio_weight: float | None
    mapping_evidence: str
    historical_or_model_sensitivity: float | None = None
    confidence: str


class BaselineReference(BaseModel):
    baseline_id: str | None = None
    timestamp: datetime | None = None
    calculation_version: str | None = None
    schema_version: str | None = None
    input_fingerprint: str | None = None
    compatible: bool
    reason_if_incompatible: str | None = None
    selection: str


class HistoricalStatus(StrEnum):
    NO_BASELINE = "NO_BASELINE"
    NO_MATERIAL_CHANGE = "NO_MATERIAL_CHANGE"
    MATERIAL_CHANGE = "MATERIAL_CHANGE"
    INCOMPATIBLE_BASELINE = "INCOMPATIBLE_BASELINE"


class HistoricalComparison(BaseModel):
    domain: str
    status: HistoricalStatus
    current: dict[str, Any]
    baseline: BaselineReference
    changes: list[ChangeItem]
    methodology_changed: bool
    confidence: str


def scope_id(read_model_type: str, *, ticker: str | None = None, portfolio_id: str | None = None) -> str:
    if ticker:
        return f"company:{ticker.upper()}"
    if portfolio_id:
        return f"portfolio:{portfolio_id}"
    return f"global:{read_model_type}"


def input_fingerprint(read_model_type: str, *, ticker: str | None = None, portfolio_id: str | None = None) -> str:
    return stable_fingerprint({"read_model_type": read_model_type, "ticker": ticker.upper() if ticker else None,
                               "portfolio_id": str(portfolio_id) if portfolio_id else None})


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _quality(available: list[str], missing: list[str]) -> EvidenceQuality:
    if not available:
        level = "INSUFFICIENT_DATA"
    elif not missing:
        level = "HIGH"
    elif len(available) >= len(missing):
        level = "MODERATE"
    else:
        level = "LOW"
    return EvidenceQuality(level=level, available_domains=available, missing_domains=missing)


def _lineage(domain: str, dataset: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [parse_timestamp(row.get("fetched_at") or row.get("observed_at") or row.get("date") or row.get("period_end")) for row in rows]
    dates = [value for value in dates if value]
    return {"domain": domain, "dataset": dataset,
            "providers": sorted({str(row.get("provider") or "stored") for row in rows}),
            "effective_at": max(dates).isoformat() if dates else None,
            "source_version": stable_fingerprint(rows)}


def build_company_analysis(ticker: str, stored: dict[str, Any], research_row: dict[str, Any], *,
                           thesis_state: dict[str, Any] | None = None) -> CompanyAnalysisResult:
    from .research_read_model import build_shared_research_model

    ticker = ticker.upper()
    securities = [row for row in stored.get("securities", []) if str(row.get("ticker")).upper() == ticker]
    fundamentals = [row for row in stored.get("fundamentals", []) if str(row.get("ticker")).upper() == ticker]
    prices = sorted([row for row in stored.get("prices", []) if str(row.get("ticker")).upper() == ticker],
                    key=lambda row: str(row.get("date") or ""))
    news = sorted([row for row in stored.get("news", []) if str(row.get("ticker")).upper() == ticker],
                  key=lambda row: str(row.get("published_at") or ""), reverse=True)
    security = securities[0] if securities else {}
    asset_type = str(security.get("asset_type") or "equity").lower()
    trend = phase4_analytics.build_fundamental_trend(fundamentals).model_dump(mode="json")
    stats = dict(research_row.get("fundamental_statistics") or {})
    valuation = dict(research_row.get("valuation_evidence") or {})
    market_stats = dict(research_row.get("market_statistics") or {})
    available = []
    missing = []
    for name, present in (("identity", bool(security)), ("prices", bool(prices)),
                          ("fundamentals", bool(fundamentals)), ("news", bool(news)),
                          ("earnings", bool(research_row.get("earnings_state"))),
                          ("thesis", bool(thesis_state))):
        (available if present else missing).append(name)
    inappropriate = asset_type in {"etf", "fund", "mutual_fund", "index"}
    shared = build_shared_research_model(ticker, bundle=stored) if not inappropriate else {}
    shared_financials = shared.get("financial_health") or {}
    shared_valuation = shared.get("valuation") or {}
    shared_market = shared.get("market") or {}
    return CompanyAnalysisResult(
        ticker=ticker,
        identity={"name": research_row.get("company") or security.get("company_name") or ticker,
                  "asset_type": asset_type, "methodology_eligible": not inappropriate,
                  "methodology_note": "Issuer fundamentals are not applied to funds." if inappropriate else None},
        sector=research_row.get("sector") or security.get("sector"),
        industry=research_row.get("industry") or security.get("industry"),
        price_state={"price": research_row.get("price"), "as_of": research_row.get("price_as_of"),
                     "data_status": "STALE" if _is_stale(research_row.get("price_as_of"), 7) else "CURRENT" if prices else "UNAVAILABLE"},
        performance={key: market_stats.get(key) for key in ("return_1d", "return_1m", "return_3m", "return_1y", "annualized_return", "max_drawdown")},
        fundamentals={**stats, **shared_financials, "as_of": shared_financials.get("as_of") or research_row.get("fundamentals_as_of")},
        fundamental_trend=trend,
        profitability={"net_margin": shared_financials.get("net_margin", research_row.get("net_margin")), "net_income": stats.get("net_income"),
                       "free_cash_flow": shared_financials.get("free_cash_flow", stats.get("free_cash_flow"))},
        balance_sheet={"total_assets": stats.get("total_assets"), "total_debt": shared_financials.get("debt", stats.get("total_debt")),
                       "cash": shared_financials.get("cash"), "net_cash_debt": shared_financials.get("net_cash_debt"),
                       "debt_to_assets": stats.get("debt_to_assets")},
        valuation={**valuation, **shared_valuation, "score": research_row.get("valuation_score")},
        momentum={"score": research_row.get("technical_score"), "price_change_1y": research_row.get("price_change_1y"),
                  "rsi_14": shared_market.get("rsi_14", market_stats.get("rsi_14")),
                  "sma_50": (shared_market.get("moving_averages") or {}).get("sma_50", market_stats.get("sma_50")),
                  "sma_200": (shared_market.get("moving_averages") or {}).get("sma_200", market_stats.get("sma_200"))},
        earnings_state=dict(research_row.get("earnings_state") or {"status": "UNAVAILABLE", "reason": "Structured earnings state is not stored."}),
        news_state={**dict(research_row.get("news_sentiment") or {}), "latest": research_row.get("latest_news")},
        eagleeyes_score=research_row.get("final_score"),
        score_components={key: research_row.get(key) for key in ("growth_rating", "fundamental_score", "valuation_score", "industry_score", "technical_score", "news_score")},
        thesis_state=thesis_state or {"status": "UNAVAILABLE", "reason": "No saved thesis state is available."},
        evidence_quality=_quality(available, missing),
        freshness={"price_as_of": research_row.get("price_as_of"), "fundamentals_as_of": research_row.get("fundamentals_as_of"),
                   "news_as_of": news[0].get("published_at") if news else None},
        lineage=[_lineage("company", "security_metadata", securities), _lineage("company", "prices", prices),
                 _lineage("company", "fundamentals", fundamentals), _lineage("company", "news", news)],
        research_capabilities=shared,
    )


def _is_stale(value: Any, days: int) -> bool:
    parsed = parse_timestamp(value)
    return bool(parsed and datetime.now(timezone.utc) - parsed > timedelta(days=days))


def build_company_comparison(companies: list[CompanyAnalysisResult], holdings: list[dict[str, Any]] | None = None) -> CompanyComparisonResult:
    weights = {str(row.get("ticker") or "").upper(): _number(row.get("weight")) or 0.0 for row in holdings or []}
    total = sum(weights.values())
    if total > 1.5:
        weights = {key: value / 100 for key, value in weights.items()}
    def rows(field: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        output = []
        for company in companies:
            value = getattr(company, field)
            output.append({"ticker": company.ticker, **{key: value.get(key) for key in keys}})
        return output
    missing: dict[str, list[str]] = {}
    advantages: dict[str, list[str]] = {company.ticker: [] for company in companies}
    disadvantages: dict[str, list[str]] = {company.ticker: [] for company in companies}
    for company in companies:
        missing[company.ticker] = list(company.evidence_quality.missing_domains)
        if (_number(company.fundamental_trend.get("score")) or 0) > 0:
            advantages[company.ticker].append("fundamentals are improving on the stored comparable periods")
        if (_number(company.profitability.get("net_margin")) or 0) > .15:
            advantages[company.ticker].append("strong stored net margin")
        if (_number(company.valuation.get("score")) or 50) < 40:
            disadvantages[company.ticker].append("weak valuation score indicates relatively expensive stored evidence")
        if company.price_state.get("data_status") == "STALE":
            disadvantages[company.ticker].append("price evidence is stale")
    levels = [company.evidence_quality.level for company in companies]
    confidence = "INSUFFICIENT_DATA" if not companies else "HIGH" if all(x == "HIGH" for x in levels) else "MODERATE" if all(x in {"HIGH", "MODERATE"} for x in levels) else "LOW"
    return CompanyComparisonResult(
        companies=[{"ticker": item.ticker, "name": item.identity.get("name"), "score": item.eagleeyes_score} for item in companies],
        growth_comparison=rows("fundamentals", ("revenue", "as_of")),
        profitability_comparison=rows("profitability", ("net_margin", "net_income", "free_cash_flow")),
        valuation_comparison=rows("valuation", ("score", "method", "price_to_earnings", "price_to_sales")),
        balance_sheet_comparison=rows("balance_sheet", ("total_assets", "total_debt", "debt_to_assets")),
        momentum_comparison=rows("momentum", ("score", "price_change_1y", "rsi_14")),
        earnings_comparison=rows("earnings_state", ("status", "next_event", "surprise")),
        evidence_quality={item.ticker: item.evidence_quality.level for item in companies},
        portfolio_fit=[{"ticker": item.ticker, "current_portfolio_weight": round(weights.get(item.ticker, 0) * 100, 2),
                        "methodology": "Current holding weight only; no return forecast."} for item in companies] if holdings is not None else [],
        portfolio_context_available=holdings is not None,
        advantages=advantages, disadvantages=disadvantages, missing_fields=missing, confidence=confidence,
    )


def _series(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("series_id")), []).append(row)
    for values in grouped.values():
        values.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    return grouped


def _macro_factor(name: str, series_ids: tuple[str, ...], grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    evidence = []
    for series_id in series_ids:
        values = grouped.get(series_id) or []
        if not values:
            continue
        latest, previous = values[0], values[1] if len(values) > 1 else None
        evidence.append({"series_id": series_id, "value": _number(latest.get("value")), "date": latest.get("date"),
                         "change": None if previous is None else round((_number(latest.get("value")) or 0) - (_number(previous.get("value")) or 0), 4)})
    return {"factor": name, "evidence": evidence, "status": "AVAILABLE" if evidence else "UNAVAILABLE",
            "as_of": max((str(row.get("date")) for row in evidence), default=None)}


def build_macro_state(rows: list[dict[str, Any]], regime_rows: list[dict[str, Any]] | None = None) -> MacroStateResult:
    grouped = _series(rows)
    rates = _macro_factor("rates", ("FEDFUNDS", "DGS10", "T10Y2Y"), grouped)
    inflation = _macro_factor("inflation", ("CPIAUCSL", "PCEPI"), grouped)
    growth = _macro_factor("growth", ("INDPRO", "RSAFS", "PCE"), grouped)
    labor = _macro_factor("labor", ("UNRATE", "PAYEMS", "ICSA"), grouped)
    liquidity = _macro_factor("liquidity", ("BAMLH0A0HYM2", "DRCCLACBS", "TOTALSL"), grouped)
    factors = [rates, inflation, growth, labor, liquidity]
    available = [row["factor"] for row in factors if row["status"] == "AVAILABLE"]
    missing = [row["factor"] for row in factors if row["status"] != "AVAILABLE"]
    latest_regime = (regime_rows or [{}])[0] if regime_rows else {}
    changes: list[ChangeItem] = []
    thresholds = {"FEDFUNDS": .25, "DGS10": .25, "CPIAUCSL": .2, "PCEPI": .2, "UNRATE": .2,
                  "BAMLH0A0HYM2": .5, "INDPRO": .5, "PAYEMS": 50.0}
    for factor in factors:
        for item in factor["evidence"]:
            delta = item.get("change")
            if delta is None:
                continue
            threshold = thresholds.get(item["series_id"], 1.0)
            magnitude = abs(delta)
            changes.append(ChangeItem(domain="macro", metric=item["series_id"], absolute_change=delta,
                                      direction="UP" if delta > 0 else "DOWN" if delta < 0 else "UNCHANGED",
                                      materiality="HIGH" if magnitude >= threshold * 2 else "MEDIUM" if magnitude >= threshold else "LOW" if magnitude else "NONE",
                                      methodology=f"Domain threshold {threshold:g} in series units."))
    dates = [parse_timestamp(row.get("date")) for row in rows]
    dates = [value for value in dates if value]
    risks = []
    unrate = next((item for item in labor["evidence"] if item["series_id"] == "UNRATE"), None)
    spread = next((item for item in liquidity["evidence"] if item["series_id"] == "BAMLH0A0HYM2"), None)
    if unrate and (_number(unrate.get("value")) or 0) >= 5:
        risks.append("Elevated unemployment in the stored observation set.")
    if spread and (_number(spread.get("value")) or 0) >= 6:
        risks.append("Elevated high-yield credit spreads in the stored observation set.")
    return MacroStateResult(
        effective_date=max(dates) if dates else None,
        observed_state={"type": "OBSERVED", "note": "Current and historical observations only; forecasts are separate."},
        rates=rates, inflation=inflation, growth=growth, labor=labor, liquidity=liquidity, factor_states=factors,
        regime={"name": latest_regime.get("dominant_regime") or "UNCLASSIFIED", "as_of": latest_regime.get("as_of_date"),
                "model_version": latest_regime.get("model_version"), "confidence": latest_regime.get("confidence")},
        changes=changes, risks=risks, evidence_quality=_quality(available, missing),
        freshness={"effective_through": min(dates).isoformat() if dates else None,
                   "newest_input": max(dates).isoformat() if dates else None},
        lineage=[_lineage("macro", "macro_observations", rows)],
    )


def _returns(values: list[dict[str, Any]], periods: int) -> float | None:
    ordered = sorted(values, key=lambda row: str(row.get("date") or ""))
    if len(ordered) <= periods:
        return None
    start, end = _number(ordered[-periods - 1].get("close")), _number(ordered[-1].get("close"))
    return None if start is None or end is None or start == 0 else end / start - 1


def build_market_state(price_rows: list[dict[str, Any]], previous: MarketStateResult | None = None) -> MarketStateResult:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in price_rows:
        grouped.setdefault(str(row.get("ticker") or "").upper(), []).append(row)
    returns_1m = {ticker: _returns(rows, 21) for ticker, rows in grouped.items()}
    returns_3m = {ticker: _returns(rows, 63) for ticker, rows in grouped.items()}
    spy_rows = sorted(grouped.get("SPY", []), key=lambda row: str(row.get("date") or ""))
    spy_returns = []
    for before, after in zip(spy_rows, spy_rows[1:]):
        a, b = _number(before.get("close")), _number(after.get("close"))
        if a and b:
            spy_returns.append(b / a - 1)
    annual_vol = statistics.stdev(spy_returns[-63:]) * math.sqrt(252) if len(spy_returns) >= 20 else None
    broad_values = [returns_3m.get(ticker) for ticker in MARKET_INDEXES if returns_3m.get(ticker) is not None]
    breadth_values = [returns_1m.get(ticker) for ticker in (*MARKET_INDEXES, *MARKET_SECTORS) if returns_1m.get(ticker) is not None]
    positive_breadth = sum(value > 0 for value in breadth_values) / len(breadth_values) if breadth_values else None
    sector_rows = sorted(({"ticker": ticker, "return_1m": returns_1m.get(ticker), "return_3m": returns_3m.get(ticker)} for ticker in MARKET_SECTORS if ticker in grouped),
                         key=lambda row: row.get("return_1m") if row.get("return_1m") is not None else -999, reverse=True)
    trend = "UP" if broad_values and statistics.mean(broad_values) > .02 else "DOWN" if broad_values and statistics.mean(broad_values) < -.02 else "SIDEWAYS" if broad_values else "UNAVAILABLE"
    risk_state = "RISK_ON" if trend == "UP" and (positive_breadth or 0) >= .55 and (annual_vol is None or annual_vol < .25) else "RISK_OFF" if trend == "DOWN" or (annual_vol or 0) >= .3 else "MIXED"
    changes: list[ChangeItem] = []
    if previous:
        old = previous.risk_on_off_state.get("state")
        if old != risk_state:
            changes.append(ChangeItem(domain="market", metric="risk_on_off_state", previous=old, current=risk_state,
                                      direction="MIXED", materiality="HIGH", methodology="Categorical market-state transition."))
    dates = [parse_timestamp(row.get("date")) for row in price_rows]
    dates = [value for value in dates if value]
    available = [name for name, present in (("broad_market_trend", bool(broad_values)), ("breadth", positive_breadth is not None),
                                             ("volatility", annual_vol is not None), ("sector_leadership", bool(sector_rows))) if present]
    missing = [name for name in ("broad_market_trend", "breadth", "volatility", "sector_leadership") if name not in available]
    return MarketStateResult(
        effective_date=max(dates) if dates else None,
        broad_market_trend={"state": trend, "index_returns_3m": {ticker: returns_3m.get(ticker) for ticker in MARKET_INDEXES}},
        volatility_state={"annualized_realized_volatility": annual_vol, "state": "HIGH" if (annual_vol or 0) >= .3 else "NORMAL" if annual_vol is not None else "UNAVAILABLE"},
        breadth={"positive_1m_fraction": positive_breadth, "state": "BROAD" if (positive_breadth or 0) >= .65 else "NARROW" if positive_breadth is not None and positive_breadth < .45 else "MIXED" if positive_breadth is not None else "UNAVAILABLE"},
        factor_leadership=[], sector_leadership=sector_rows,
        risk_on_off_state={"state": risk_state, "methodology": "Broad trend + breadth + realized volatility; descriptive, not predictive."},
        valuation_state={"status": "UNAVAILABLE", "reason": "A broad-market valuation series is not connected."},
        regime=f"{risk_state}:{trend}", material_changes=changes, evidence_quality=_quality(available, missing),
        freshness={"effective_through": min(dates).isoformat() if dates else None,
                   "newest_input": max(dates).isoformat() if dates else None},
    )


def build_prediction_market_state(intelligence: dict[str, Any], holdings: list[dict[str, Any]] | None = None) -> PredictionMarketResult:
    weights = {str(row.get("ticker") or "").upper(): _number(row.get("weight")) or 0.0 for row in holdings or []}
    if sum(weights.values()) > 1.5:
        weights = {key: value / 100 for key, value in weights.items()}
    markets = []
    changes = []
    dates = []
    for source in intelligence.get("markets") or []:
        row = dict(source)
        probability = dict(row.get("probability") or {})
        probability["source_type"] = str(probability.get("source_type") or "MARKET_IMPLIED")
        if probability["source_type"] not in {"MARKET_IMPLIED", "MODEL", "USER_DEFINED", "COMPOSITE"}:
            probability["source_type"] = "MARKET_IMPLIED"
        mapped = sorted(set(row.get("affected_holdings") or []).intersection(weights))
        mapped_weight = sum(weights.get(ticker, 0) for ticker in mapped)
        row["probability"] = probability
        row["mapped_holdings"] = mapped
        row["mapped_portfolio_weight"] = round(mapped_weight * 100, 2) if holdings is not None else None
        row["mapping_methodology"] = "Deterministic direct-company/factor rules; not an impact estimate."
        row["mapping_confidence"] = "MODERATE" if mapped else "UNAVAILABLE"
        markets.append(row)
        changed = row.get("change") or {}
        current_probability = _number(probability.get("probability"))
        if current_probability is not None:
            changes.append(PredictionMarketChange(event=str(row.get("title") or row.get("event_key")),
                                                  previous_probability=_number(changed.get("previous_probability")),
                                                  current_probability=current_probability,
                                                  delta_pp=_number(changed.get("percentage_point_change")),
                                                  time_window="previous stored venue observation",
                                                  mapped_portfolio_weight=row["mapped_portfolio_weight"],
                                                  relevance=str(row.get("category") or "UNKNOWN")))
        parsed = parse_timestamp(probability.get("as_of"))
        if parsed:
            dates.append(parsed)
    available = ["probabilities"] if markets else []
    missing = [] if markets else ["probabilities"]
    if holdings is None:
        missing.append("portfolio_mappings")
    calibration = "UNAVAILABLE"
    if any((row.get("quality") or {}).get("level") == "HIGH" for row in markets):
        available.append("market_quality")
    else:
        missing.append("high_quality_market")
    return PredictionMarketResult(
        markets=markets, changes=changes,
        probability_types=sorted({str((row.get("probability") or {}).get("source_type")) for row in markets}),
        provider_disagreements=list(intelligence.get("disagreements") or []), calibration_quality=calibration,
        portfolio_context_available=holdings is not None, evidence_quality=_quality(available, missing),
        freshness={"effective_through": min(dates).isoformat() if dates else None, "newest_input": max(dates).isoformat() if dates else None},
        lineage=[{"domain": "prediction_markets", "dataset": "stored venue observations",
                  "providers": sorted({str(row.get("provider")) for row in markets}),
                  "source_version": stable_fingerprint(markets)}],
    )


def portfolio_macro_exposures(macro: MacroStateResult, holdings: list[dict[str, Any]],
                              security_rows: list[dict[str, Any]] | None = None) -> list[PortfolioMacroExposureResult]:
    sectors = {str(row.get("ticker") or "").upper(): str(row.get("sector") or "") for row in security_rows or []}
    weights = {str(row.get("ticker") or "").upper(): _number(row.get("weight")) or 0 for row in holdings}
    if sum(weights.values()) > 1.5:
        weights = {key: value / 100 for key, value in weights.items()}
    rules = {
        "rates": {"Technology", "Real Estate", "Utilities", "Financials"},
        "inflation": {"Consumer Cyclical", "Technology", "Energy"},
        "growth": {"Consumer Cyclical", "Industrials", "Financials"},
        "labor": {"Consumer Cyclical", "Industrials"},
        "liquidity": {"Financials", "Real Estate", "Consumer Cyclical"},
    }
    results = []
    for factor in macro.factor_states:
        exposed = sorted(ticker for ticker in weights if sectors.get(ticker) in rules.get(factor["factor"], set()))
        results.append(PortfolioMacroExposureResult(
            macro_factor=factor["factor"], direction_state=factor["status"], exposed_holdings=exposed,
            portfolio_weight=round(sum(weights[ticker] for ticker in exposed) * 100, 2),
            mapping_evidence="Deterministic sector-to-macro-factor mapping; this is exposure coverage, not estimated loss.",
            confidence="MODERATE" if exposed else "LOW",
        ))
    return results


def market_portfolio_fit(market: MarketStateResult, holdings: list[dict[str, Any]],
                         security_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sectors = {str(row.get("ticker") or "").upper(): str(row.get("sector") or "") for row in security_rows or []}
    weights = {str(row.get("ticker") or "").upper(): _number(row.get("weight")) or 0 for row in holdings}
    if sum(weights.values()) > 1.5:
        weights = {key: value / 100 for key, value in weights.items()}
    leaders = {row.get("ticker") for row in market.sector_leadership[:3]}
    # Existing data identifies sector ETFs but does not provide a universal
    # GICS-to-ETF dictionary. Fit therefore stays qualitative unless a direct
    # sector label/ETF match is present.
    aligned = sorted(ticker for ticker in weights if ticker in leaders or sectors.get(ticker) in leaders)
    return {"state": "PARTIAL" if holdings else "UNAVAILABLE", "aligned_holdings": aligned,
            "aligned_portfolio_weight": round(sum(weights.get(ticker, 0) for ticker in aligned) * 100, 2),
            "market_regime": market.regime,
            "evidence": "Current holdings and deterministic market leadership only.",
            "limitation": "Fit/mismatch is descriptive; it is not a validated return forecast."}


def _read_model_metadata(read_model_type: str, scope: str, fingerprint: str, data: dict[str, Any],
                         descriptors: dict[str, dict[str, str | None]], status: AnalysisStatus) -> read_models.ReadModelMetadata:
    now = datetime.now(timezone.utc)
    dependencies = read_models.READ_MODEL_DEPENDENCIES[read_model_type]
    tracked = (*dependencies["required"], *dependencies["optional"])
    freshness = build_freshness([(name, descriptors.get(name, {}).get("effective_through")) for name in dependencies["required"]], calculated_at=now)
    return read_models.ReadModelMetadata(
        read_model_type=read_model_type, schema_version=DOMAIN_SCHEMA_VERSION,
        calculation_version=read_models.READ_MODEL_CALCULATION_VERSIONS[read_model_type],
        input_fingerprint=fingerprint, portfolio_id=scope, calculated_at=now,
        effective_through=freshness.effective_through, oldest_required_input=freshness.oldest_required_input,
        upstream_versions={name: descriptors[name]["version"] for name in tracked if name in descriptors},
        analysis_status=status, coverage=Coverage.not_tracked(), freshness=freshness,
        builder_version="phase6-domain-builder-v1",
    )


def persist_domain_model(user_id: str, read_model_type: str, scope: str, fingerprint: str,
                         data: BaseModel | dict[str, Any], descriptors: dict[str, dict[str, str | None]],
                         status: AnalysisStatus) -> read_models.CapabilityReadModel:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    for name, descriptor in descriptors.items():
        database.upsert_analytical_dataset_version(user_id, scope, name, str(descriptor["version"]), descriptor.get("effective_through"))
    metadata = _read_model_metadata(read_model_type, scope, fingerprint, payload, descriptors, status)
    stored = database.save_capability_read_model(user_id, scope, metadata.model_dump(mode="json"), payload)
    return read_models.CapabilityReadModel(id=stored["id"], metadata=metadata, data=payload)


def materialize_company(user_id: str, ticker: str, *, stored: dict[str, Any] | None = None,
                        research_row: dict[str, Any] | None = None, thesis_state: dict[str, Any] | None = None) -> read_models.CapabilityReadModel:
    from .analysis import security_research
    from .earnings_intelligence import build_earnings_intelligence
    ticker = ticker.upper()
    stored = stored if stored is not None else database.research_capability_data([ticker, "SPY", "QQQ", "XLK", "SOXX"], price_limit=1400)
    research_row = research_row or security_research([ticker], stored=stored)[0]
    if not research_row.get("earnings_state"):
        research_row = {**research_row, "earnings_state": build_earnings_intelligence(
            ticker, [row for row in stored.get("fundamentals") or [] if str(row.get("ticker") or "").upper() == ticker],
        )}
    data = build_company_analysis(ticker, stored, research_row, thesis_state=thesis_state)
    scope = scope_id("company_analysis", ticker=ticker)
    descriptors = {
        "prices": read_models.dataset_descriptor(stored.get("prices") or []),
        "fundamentals": read_models.dataset_descriptor(stored.get("fundamentals") or []),
        "security_metadata": read_models.dataset_descriptor(stored.get("securities") or []),
        "earnings": read_models.dataset_descriptor(research_row.get("earnings_state") or {}),
        "news": read_models.dataset_descriptor(stored.get("news") or []),
        "score_model": {"version": COMPANY_CALCULATION_VERSION, "effective_through": None},
        "thesis_state": read_models.dataset_descriptor(thesis_state or {}),
    }
    usable = bool(stored.get("prices")) and bool(stored.get("fundamentals")) and data.identity.get("methodology_eligible") is not False
    status = AnalysisStatus.SUCCESS if data.evidence_quality.level == "HIGH" else AnalysisStatus.PARTIAL if usable else AnalysisStatus.UNAVAILABLE
    return persist_domain_model(user_id, "company_analysis", scope, input_fingerprint("company_analysis", ticker=ticker), data, descriptors, status)


def materialize_macro(user_id: str, *, rows: list[dict[str, Any]] | None = None,
                      regime_rows: list[dict[str, Any]] | None = None) -> read_models.CapabilityReadModel:
    rows = rows if rows is not None else database.macro_observation_history(list(MACRO_SERIES), 14)
    regime_rows = regime_rows if regime_rows is not None else database.regime_history(2)
    data = build_macro_state(rows, regime_rows)
    scope = scope_id("macro_state")
    descriptors = {"macro_observations": read_models.dataset_descriptor(rows),
                   "macro_regime_labels": read_models.dataset_descriptor(regime_rows),
                   "macro_calendar": read_models.dataset_descriptor([])}
    status = AnalysisStatus.SUCCESS if data.evidence_quality.level == "HIGH" else AnalysisStatus.PARTIAL if rows else AnalysisStatus.UNAVAILABLE
    return persist_domain_model(user_id, "macro_state", scope, input_fingerprint("macro_state"), data, descriptors, status)


def materialize_market(user_id: str, *, rows: list[dict[str, Any]] | None = None) -> read_models.CapabilityReadModel:
    rows = rows if rows is not None else database.price_history(list((*MARKET_INDEXES, *MARKET_SECTORS)), 260)
    previous_loaded = load_domain_model(user_id, "market_state", scope_id("market_state"), input_fingerprint("market_state"))
    previous = MarketStateResult.model_validate(previous_loaded.model.data) if previous_loaded.model else None
    data = build_market_state(rows, previous)
    scope = scope_id("market_state")
    indexes = [row for row in rows if row.get("ticker") in MARKET_INDEXES]
    sectors = [row for row in rows if row.get("ticker") in MARKET_SECTORS]
    descriptors = {"market_prices": read_models.dataset_descriptor(indexes), "volatility": read_models.dataset_descriptor(indexes),
                   "breadth": read_models.dataset_descriptor(rows), "sector_data": read_models.dataset_descriptor(sectors)}
    status = AnalysisStatus.SUCCESS if data.evidence_quality.level == "HIGH" else AnalysisStatus.PARTIAL if indexes else AnalysisStatus.UNAVAILABLE
    return persist_domain_model(user_id, "market_state", scope, input_fingerprint("market_state"), data, descriptors, status)


def materialize_prediction_markets(user_id: str, *, portfolio_id: str | None = None,
                                   intelligence: dict[str, Any] | None = None,
                                   holdings: list[dict[str, Any]] | None = None) -> read_models.CapabilityReadModel:
    from . import forecasting
    if holdings is None and portfolio_id:
        portfolio = database.get_portfolio(portfolio_id, user_id)
        holdings = list(portfolio.get("holdings") or [])
    intelligence = intelligence if intelligence is not None else forecasting.build_intelligence(user_id, holdings=holdings)
    data = build_prediction_market_state(intelligence, holdings)
    scope = scope_id("prediction_market_state", portfolio_id=portfolio_id)
    descriptors = {"prediction_market_observations": read_models.dataset_descriptor(intelligence.get("markets") or []),
                   "calibration": read_models.dataset_descriptor({}),
                   "portfolio_mappings": read_models.dataset_descriptor(holdings or [])}
    status = AnalysisStatus.SUCCESS if data.evidence_quality.level == "HIGH" else AnalysisStatus.PARTIAL if data.markets else AnalysisStatus.UNAVAILABLE
    return persist_domain_model(user_id, "prediction_market_state", scope,
                                input_fingerprint("prediction_market_state", portfolio_id=portfolio_id), data, descriptors, status)


def load_domain_model(user_id: str, read_model_type: str, scope: str, fingerprint: str) -> read_models.CompatibleReadModel:
    return read_models.load_compatible_read_model(user_id, scope, read_model_type, fingerprint,
                                                  schema_version=DOMAIN_SCHEMA_VERSION,
                                                  calculation_version=read_models.READ_MODEL_CALCULATION_VERSIONS[read_model_type])


def load_company(user_id: str, ticker: str) -> read_models.CompatibleReadModel:
    return load_domain_model(user_id, "company_analysis", scope_id("company_analysis", ticker=ticker),
                             input_fingerprint("company_analysis", ticker=ticker))


def load_company_pair(user_id: str, tickers: list[str]) -> list[read_models.CompatibleReadModel]:
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(tickers))), thread_name_prefix="company-read") as pool:
        return list(pool.map(lambda value: load_company(user_id, value), tickers))


def invalidate_domain(user_id: str, dataset_type: str, version: str, *,
                      tickers: list[str] | None = None, portfolio_ids: list[str] | None = None,
                      effective_through: str | None = None) -> list[str]:
    """Invalidate only domain scopes whose declared dependency advanced."""
    scopes: list[tuple[str, str]] = []
    normalized = [value.upper() for value in tickers or []]
    if dataset_type in {"prices", "fundamentals", "security_metadata", "earnings", "news", "score_model", "thesis_state"}:
        scopes.extend((scope_id("company_analysis", ticker=ticker), "company_analysis") for ticker in normalized)
    if dataset_type in {"macro_observations", "macro_regime_labels", "macro_calendar"}:
        scopes.append((scope_id("macro_state"), "macro_state"))
    if dataset_type in {"market_prices", "volatility", "breadth", "sector_data"}:
        scopes.append((scope_id("market_state"), "market_state"))
    if dataset_type in {"prediction_market_observations", "calibration", "portfolio_mappings"}:
        scopes.append((scope_id("prediction_market_state"), "prediction_market_state"))
        scopes.extend((scope_id("prediction_market_state", portfolio_id=value), "prediction_market_state")
                      for value in portfolio_ids or [])
    invalidated = []
    for scope, model_type in dict.fromkeys(scopes):
        database.upsert_analytical_dataset_version(user_id, scope, dataset_type, version, effective_through)
        history = database.capability_read_model_history(user_id, scope, model_type, 1)
        if history:
            database.update_capability_read_model_state(history[0]["id"], read_models.ReadModelState.STALE,
                                                        f"{dataset_type} advanced to {version}.")
            invalidated.append(f"{scope}:{model_type}")
    return invalidated


def _canonical_from_loaded(capability: str, loaded: read_models.CompatibleReadModel, calculation_version: str,
                           fingerprint: str, requested: list[str] | None = None) -> AnalysisResult:
    now = datetime.now(timezone.utc)
    requested = requested or []
    if not loaded.model:
        return AnalysisResult(
            capability=capability, calculation_version=calculation_version, input_fingerprint=fingerprint,
            status=AnalysisStatus.UNAVAILABLE, data={}, coverage=Coverage(requested_entities=requested),
            freshness=Freshness(calculated_at=now, stale=None),
            dependencies=[DependencyResult(name=loaded.reason, required=True, status=AnalysisStatus.UNAVAILABLE, cache_state=loaded.state.value)],
            limitations=[loaded.reason], prerequisites=[Prerequisite(name="compatible_read_model", satisfied=False, reason=loaded.reason)],
            verification=VerificationResult(passed=True, answer_allowed=True, recommendation_allowed=False),
        )
    metadata = loaded.model.metadata
    status = metadata.analysis_status
    if loaded.state == read_models.CompatibilityState.STALE and status == AnalysisStatus.SUCCESS:
        status = AnalysisStatus.PARTIAL
    return AnalysisResult(
        capability=capability, calculation_version=calculation_version, input_fingerprint=fingerprint,
        status=status, data=loaded.model.data,
        coverage=Coverage(requested_entities=requested, evaluated_entities=requested if status != AnalysisStatus.UNAVAILABLE else []),
        freshness=metadata.freshness,
        lineage=[LineageItem(domain=capability, dataset=metadata.read_model_type,
                             source_version=loaded.model.id, effective_at=metadata.effective_through)],
        dependencies=[DependencyResult(name=metadata.read_model_type, required=True, status=status,
                                       freshness=metadata.freshness, cache_state=loaded.state.value)],
        limitations=[loaded.reason] if loaded.state == read_models.CompatibilityState.STALE else [],
        verification=VerificationResult(passed=True, answer_allowed=True, recommendation_allowed=False,
                                        checks=[VerificationCheck(name="version_compatibility", passed=True,
                                                                  severity=VerificationSeverity.INFO,
                                                                  message=loaded.reason)]),
    )


def company_analysis_result(user_id: str, ticker: str) -> AnalysisResult:
    normalized = ticker.upper()
    return _canonical_from_loaded("company_analysis", load_company(user_id, normalized), COMPANY_CALCULATION_VERSION,
                                  input_fingerprint("company_analysis", ticker=normalized), [normalized])


def company_comparison_from_stored(tickers: list[str], stored: dict[str, Any],
                                   research_rows: list[dict[str, Any]],
                                   holdings: list[dict[str, Any]] | None = None) -> AnalysisResult:
    """Build a bounded comparison from already-stored evidence without read-model writes."""
    normalized = list(dict.fromkeys(value.upper() for value in tickers))
    research_by_ticker = {str(row.get("ticker") or "").upper(): row for row in research_rows}
    models = [
        build_company_analysis(ticker, stored, research_by_ticker[ticker])
        for ticker in normalized if ticker in research_by_ticker
    ]
    evaluated = [model.ticker for model in models if model.evidence_quality.level != "INSUFFICIENT_DATA"]
    data = build_company_comparison(models, holdings).model_dump(mode="json") if len(models) >= 2 else {}
    status = (
        AnalysisStatus.SUCCESS if len(evaluated) == len(normalized) and holdings is not None
        else AnalysisStatus.PARTIAL if len(models) >= 2
        else AnalysisStatus.UNAVAILABLE
    )
    effective_dates = [value for model in models for value in model.freshness.values() if value]
    return AnalysisResult(
        capability="company_comparison", calculation_version=COMPARISON_CALCULATION_VERSION,
        input_fingerprint=stable_fingerprint({
            "tickers": normalized,
            "stored": read_models.dataset_descriptor(stored),
            "portfolio_context": holdings or None,
        }),
        status=status, data=data,
        coverage=Coverage(requested_entities=normalized, evaluated_entities=evaluated),
        freshness=build_freshness([("stored_company_evidence", value) for value in effective_dates]),
        dependencies=[DependencyResult(
            name=f"stored_company_evidence:{ticker}", required=True,
            status=AnalysisStatus.SUCCESS if ticker in evaluated else AnalysisStatus.UNAVAILABLE,
            cache_state="STORED_EVIDENCE",
        ) for ticker in normalized] + [DependencyResult(
            name="portfolio_fit", required=False,
            status=AnalysisStatus.SUCCESS if holdings is not None else AnalysisStatus.UNAVAILABLE,
        )],
        limitations=[] if status == AnalysisStatus.SUCCESS else [
            "Some requested stored company evidence or portfolio context is unavailable."
        ],
        verification=VerificationResult(
            passed=status != AnalysisStatus.UNAVAILABLE,
            answer_allowed=status != AnalysisStatus.FAILED,
            recommendation_allowed=False,
        ),
    )


def company_comparison_result(user_id: str, tickers: list[str], holdings: list[dict[str, Any]] | None = None) -> AnalysisResult:
    normalized = list(dict.fromkeys(value.upper() for value in tickers))
    loaded = load_company_pair(user_id, normalized)
    models = [CompanyAnalysisResult.model_validate(item.model.data) for item in loaded if item.model]
    missing = [ticker for ticker, item in zip(normalized, loaded) if not item.model]
    if len(models) < 2:
        status = AnalysisStatus.UNAVAILABLE
        data: dict[str, Any] = {}
    else:
        comparison = build_company_comparison(models, holdings)
        data = comparison.model_dump(mode="json")
        status = AnalysisStatus.PARTIAL if missing or any(item.state == read_models.CompatibilityState.STALE for item in loaded) or holdings is None else AnalysisStatus.SUCCESS
    fingerprint = stable_fingerprint({"tickers": normalized, "company_model_ids": [item.model.id if item.model else None for item in loaded],
                                      "portfolio_context": holdings or None})
    return AnalysisResult(
        capability="company_comparison", calculation_version=COMPARISON_CALCULATION_VERSION,
        input_fingerprint=fingerprint, status=status, data=data,
        coverage=Coverage(requested_entities=normalized, evaluated_entities=[model.ticker for model in models]),
        freshness=build_freshness([("company_read_models", item.model.metadata.effective_through) for item in loaded if item.model]),
        dependencies=[DependencyResult(name=f"company_analysis:{ticker}", required=True,
                                       status=AnalysisStatus.SUCCESS if item.model else AnalysisStatus.UNAVAILABLE,
                                       cache_state=item.state.value) for ticker, item in zip(normalized, loaded)] +
                     [DependencyResult(name="portfolio_fit", required=False,
                                       status=AnalysisStatus.SUCCESS if holdings is not None else AnalysisStatus.UNAVAILABLE)],
        limitations=[f"Missing compatible company read models: {', '.join(missing)}"] if missing else
                    (["Portfolio-fit enrichment is unavailable; company facts remain usable."] if holdings is None else []),
        verification=VerificationResult(passed=True, answer_allowed=status != AnalysisStatus.FAILED, recommendation_allowed=False),
    )


def macro_state_result(user_id: str) -> AnalysisResult:
    fingerprint = input_fingerprint("macro_state")
    return _canonical_from_loaded("macro_state", load_domain_model(user_id, "macro_state", scope_id("macro_state"), fingerprint),
                                  MACRO_CALCULATION_VERSION, fingerprint)


def market_state_result(user_id: str) -> AnalysisResult:
    fingerprint = input_fingerprint("market_state")
    return _canonical_from_loaded("market_state", load_domain_model(user_id, "market_state", scope_id("market_state"), fingerprint),
                                  MARKET_CALCULATION_VERSION, fingerprint)


def prediction_market_result(user_id: str, portfolio_id: str | None = None) -> AnalysisResult:
    fingerprint = input_fingerprint("prediction_market_state", portfolio_id=portfolio_id)
    return _canonical_from_loaded("prediction_markets", load_domain_model(user_id, "prediction_market_state",
                                  scope_id("prediction_market_state", portfolio_id=portfolio_id), fingerprint),
                                  PREDICTION_CALCULATION_VERSION, fingerprint)


def historical_comparison(user_id: str, read_model_type: str, scope: str, *, selection: str = "previous_snapshot",
                          baseline_at: datetime | None = None) -> HistoricalComparison:
    history = database.capability_read_model_history(user_id, scope, read_model_type, 100)
    current_row = next((row for row in history if row["metadata"].get("read_model_state") in {"CURRENT", "STALE"}), None)
    current = current_row or {}
    if selection == "last_review" and baseline_at is None:
        return HistoricalComparison(domain=read_model_type, status=HistoricalStatus.NO_BASELINE,
                                    current=current.get("data") or {},
                                    baseline=BaselineReference(compatible=False, selection=selection,
                                                               reason_if_incompatible="No genuine user review timestamp exists; a snapshot was not substituted."),
                                    changes=[], methodology_changed=False, confidence="UNAVAILABLE")
    candidates = [row for row in history if row is not current_row]
    if baseline_at:
        candidates = [row for row in candidates if (parse_timestamp(row["metadata"].get("calculated_at")) or datetime.max.replace(tzinfo=timezone.utc)) <= baseline_at]
    baseline_row = candidates[0] if candidates else None
    if not current_row or not baseline_row:
        return HistoricalComparison(domain=read_model_type, status=HistoricalStatus.NO_BASELINE,
                                    current=current.get("data") or {},
                                    baseline=BaselineReference(compatible=False, selection=selection,
                                                               reason_if_incompatible="No genuine compatible baseline exists for the requested selection."),
                                    changes=[], methodology_changed=False, confidence="UNAVAILABLE")
    current_meta, baseline_meta = current_row["metadata"], baseline_row["metadata"]
    compatible = (current_meta.get("schema_version") == baseline_meta.get("schema_version") and
                  current_meta.get("calculation_version") == baseline_meta.get("calculation_version"))
    reference = BaselineReference(
        baseline_id=baseline_row["id"], timestamp=parse_timestamp(baseline_meta.get("calculated_at")),
        calculation_version=baseline_meta.get("calculation_version"), schema_version=baseline_meta.get("schema_version"),
        input_fingerprint=baseline_meta.get("input_fingerprint"), compatible=compatible, selection=selection,
        reason_if_incompatible=None if compatible else "Schema or calculation version differs; no delta was computed.",
    )
    if not compatible:
        return HistoricalComparison(domain=read_model_type, status=HistoricalStatus.INCOMPATIBLE_BASELINE,
                                    current=current_row["data"], baseline=reference, changes=[], methodology_changed=True,
                                    confidence="UNAVAILABLE")
    changes = deterministic_changes(read_model_type, baseline_row["data"], current_row["data"])
    return HistoricalComparison(domain=read_model_type,
                                status=HistoricalStatus.MATERIAL_CHANGE if changes else HistoricalStatus.NO_MATERIAL_CHANGE,
                                current=current_row["data"], baseline=reference, changes=changes,
                                methodology_changed=False, confidence="MODERATE" if changes else "HIGH")


def resolve_last_company_review_at(user_id: str, ticker: str) -> datetime | None:
    """Resolve a genuine review/decision timestamp; never fall back to a model snapshot."""
    from . import theses, thesis_monitor
    candidates: list[datetime] = []
    thesis = theses.active_thesis(user_id, ticker.upper())
    if thesis:
        for row in thesis_monitor.review_history(user_id, str(thesis["id"])):
            parsed = parse_timestamp(row.get("reviewed_at") or row.get("created_at"))
            if parsed:
                candidates.append(parsed)
    for row in theses.list_decisions(user_id):
        if str(row.get("ticker") or "").upper() != ticker.upper():
            continue
        parsed = parse_timestamp(row.get("decision_date") or row.get("created_at"))
        if parsed:
            candidates.append(parsed)
    return max(candidates) if candidates else None


def deterministic_changes(read_model_type: str, previous: dict[str, Any], current: dict[str, Any]) -> list[ChangeItem]:
    if read_model_type == "macro_state":
        old = {row.get("series_id"): row for factor in previous.get("factor_states") or [] for row in factor.get("evidence") or []}
        new = {row.get("series_id"): row for factor in current.get("factor_states") or [] for row in factor.get("evidence") or []}
        thresholds = {"FEDFUNDS": .25, "DGS10": .25, "CPIAUCSL": .2, "PCEPI": .2,
                      "UNRATE": .2, "BAMLH0A0HYM2": .5, "INDPRO": .5, "PAYEMS": 50.0}
        output = []
        for metric in sorted(set(old) & set(new)):
            before, after = _number(old[metric].get("value")), _number(new[metric].get("value"))
            threshold = thresholds.get(metric, 1.0)
            if before is None or after is None or abs(after - before) < threshold:
                continue
            delta = after - before
            output.append(ChangeItem(domain="macro", metric=metric, previous=before, current=after,
                                     absolute_change=delta, direction="UP" if delta > 0 else "DOWN",
                                     materiality="HIGH" if abs(delta) >= threshold * 2 else "MEDIUM",
                                     methodology=f"Deterministic macro threshold: {threshold:g} series units."))
        old_regime, new_regime = (previous.get("regime") or {}).get("name"), (current.get("regime") or {}).get("name")
        if old_regime and new_regime and old_regime != new_regime:
            output.append(ChangeItem(domain="macro", metric="regime", previous=old_regime, current=new_regime,
                                     direction="MIXED", materiality="HIGH", methodology="Categorical regime transition."))
        return output
    if read_model_type == "company_analysis":
        metrics = (("eagleeyes_score", 3.0), ("fundamentals.revenue", 0.0),
                   ("profitability.net_margin", .02), ("valuation.score", 5.0),
                   ("momentum.score", 5.0))
        output = []
        def nested(source: Any, dotted: str) -> Any:
            for part in dotted.split("."):
                source = source.get(part) if isinstance(source, dict) else None
            return source
        for path, threshold in metrics:
            before, after = _number(nested(previous, path)), _number(nested(current, path))
            if before is None or after is None:
                continue
            effective_threshold = threshold if threshold else max(abs(before) * .05, 1e-9)
            if abs(after - before) < effective_threshold:
                continue
            delta = after - before
            output.append(ChangeItem(domain="company", metric=path, previous=before, current=after,
                                     absolute_change=delta, direction="UP" if delta > 0 else "DOWN",
                                     materiality="HIGH" if abs(delta) >= effective_threshold * 2 else "MEDIUM",
                                     methodology=f"Deterministic company threshold: {effective_threshold:g}."))
        return output
    fields: dict[str, tuple[str, float]] = {
        "market_state": ("breadth.positive_1m_fraction", .1),
        "portfolio_change": ("health.score", 3.0),
        "prediction_market_state": ("changes.0.delta_pp", 5.0),
    }
    path, threshold = fields.get(read_model_type, ("", 0))
    if not path:
        return []
    def value(source: Any, dotted: str) -> Any:
        for part in dotted.split("."):
            if isinstance(source, list) and part.isdigit():
                source = source[int(part)] if int(part) < len(source) else None
            elif isinstance(source, dict):
                source = source.get(part)
            else:
                return None
        return source
    before, after = _number(value(previous, path)), _number(value(current, path))
    if before is None or after is None or abs(after - before) < threshold:
        return []
    delta = after - before
    return [ChangeItem(domain=read_model_type, metric=path, previous=before, current=after, absolute_change=delta,
                       direction="UP" if delta > 0 else "DOWN", materiality="HIGH" if abs(delta) >= threshold * 2 else "MEDIUM",
                       methodology=f"Deterministic Phase 6 threshold: {threshold:g} units.")]


def render_company(data: CompanyAnalysisResult) -> str:
    missing = ", ".join(data.evidence_quality.missing_domains) or "none"
    return (f"{data.identity.get('name')} ({data.ticker})\n\n"
            f"Price: {data.price_state.get('price')} as of {data.price_state.get('as_of') or 'unavailable'}\n"
            f"EagleEyes score: {data.eagleeyes_score if data.eagleeyes_score is not None else 'unavailable'}\n"
            f"Fundamental trend: {data.fundamental_trend.get('direction', 'UNAVAILABLE')}\n"
            f"Revenue growth: {data.fundamentals.get('revenue_growth', data.fundamental_trend.get('revenue_growth')) or 'unavailable'}\n"
            f"Net margin: {data.profitability.get('net_margin') if data.profitability.get('net_margin') is not None else 'unavailable'}\n"
            f"Valuation score: {data.valuation.get('score') if data.valuation.get('score') is not None else 'unavailable'}\n"
            f"Evidence quality: {data.evidence_quality.level}. Missing: {missing}.")


def render_comparison(data: CompanyComparisonResult) -> str:
    def by_ticker(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(row.get("ticker") or "").upper(): row for row in rows}

    def number(value: Any, *, percent: bool = False) -> str:
        parsed = _number(value)
        if parsed is None:
            return "unavailable"
        return f"{parsed:.1%}" if percent else f"{parsed:,.1f}"

    def money(value: Any) -> str:
        parsed = _number(value)
        if parsed is None:
            return "unavailable"
        if abs(parsed) >= 1_000_000_000:
            return f"${parsed / 1_000_000_000:.1f}B"
        if abs(parsed) >= 1_000_000:
            return f"${parsed / 1_000_000:.1f}M"
        return f"${parsed:,.1f}"

    growth = by_ticker(data.growth_comparison)
    profitability = by_ticker(data.profitability_comparison)
    valuation = by_ticker(data.valuation_comparison)
    momentum = by_ticker(data.momentum_comparison)
    fit = by_ticker(data.portfolio_fit)
    tickers = [str(row["ticker"]) for row in data.companies]
    lines = [f"**{' vs '.join(tickers)} — stored evidence comparison**", ""]
    scored = [(ticker, _number(next((row.get("score") for row in data.companies if row["ticker"] == ticker), None))) for ticker in tickers]
    scored = [(ticker, value) for ticker, value in scored if value is not None]
    margins = [(ticker, _number(profitability.get(ticker, {}).get("net_margin"))) for ticker in tickers]
    margins = [(ticker, value) for ticker, value in margins if value is not None]
    valuations = [(ticker, _number(valuation.get(ticker, {}).get("score"))) for ticker in tickers]
    valuations = [(ticker, value) for ticker, value in valuations if value is not None]
    if scored:
        overall = max(scored, key=lambda row: row[1])
        summary = f"On the currently stored evidence, **{overall[0]} ranks ahead overall** with an EagleEyes score of **{overall[1]:.1f}**"
        if valuations:
            valuation_leader = max(valuations, key=lambda row: row[1])
            summary += f" and **{valuation_leader[0]} has the stronger relative valuation score**"
        if margins:
            margin_leader = max(margins, key=lambda row: row[1])
            summary += f", while **{margin_leader[0]} has the higher stored net margin**"
        lines.extend(["**Bottom line**", summary + ". The portfolio-fit conclusion is limited to current position weights; sector and economic-dependency overlap still need a separate concentration check.", ""])
    for ticker in tickers:
        company = next((row for row in data.companies if row["ticker"] == ticker), {})
        lines.extend([
            f"**{ticker}**",
            f"- EagleEyes score: **{number(company.get('score'))}**",
            f"- Latest stored revenue: **{money(growth.get(ticker, {}).get('revenue'))}**; net margin: **{number(profitability.get(ticker, {}).get('net_margin'), percent=True)}**",
            f"- Valuation score: **{number(valuation.get(ticker, {}).get('score'))}**; momentum score: **{number(momentum.get(ticker, {}).get('score'))}**",
        ])
        strengths = data.advantages.get(ticker) or []
        risks = data.disadvantages.get(ticker) or []
        if strengths:
            lines.append(f"- Strongest stored evidence: {strengths[0]}.")
        if risks:
            lines.append(f"- Main caution: {risks[0]}.")
        lines.append("")
    lines.append("**Portfolio fit**")
    if data.portfolio_context_available:
        lines.extend(
            f"- **{ticker}: {number(fit.get(ticker, {}).get('current_portfolio_weight'))}%** of the saved portfolio."
            for ticker in tickers
        )
        lines.append("This fit measure is current holding weight only. It shows existing concentration, not incremental diversification or expected return.")
    else:
        lines.append("Saved portfolio context is unavailable; the company comparison remains usable, but portfolio fit cannot be claimed.")
    missing = [f"{ticker}: {', '.join(values)}" for ticker, values in data.missing_fields.items() if values]
    if missing:
        lines.extend(["", "**Missing evidence**", *[f"- {row}" for row in missing]])
    lines.extend(["", f"Evidence confidence: **{data.confidence.lower()}**. This is a comparison of stored evidence, not a buy recommendation."])
    return "\n".join(lines)


def render_macro(data: MacroStateResult) -> str:
    lines = ["Current macro state", "", f"Regime: {data.regime.get('name', 'UNCLASSIFIED')}"]
    for factor in (data.rates, data.inflation, data.growth, data.labor, data.liquidity):
        lines.append(f"{factor['factor'].title()}: {factor['status']} ({len(factor['evidence'])} stored series)")
    material = [row for row in data.changes if row.materiality in {"HIGH", "MEDIUM"}]
    lines.append("\nBiggest changes:")
    lines.extend(f"- {row.metric}: {row.absolute_change:+g} ({row.materiality})" for row in material[:5])
    if not material:
        lines.append("- No material observed-series change in the comparison window.")
    lines.append(f"\nEvidence quality: {data.evidence_quality.level}. Forecasts are separate from this observed state.")
    return "\n".join(lines)


def render_market(data: MarketStateResult) -> str:
    leaders = ", ".join(row["ticker"] for row in data.sector_leadership[:3]) or "unavailable"
    return (f"Current market state\n\nBroad trend: {data.broad_market_trend.get('state')}\n"
            f"Risk state: {data.risk_on_off_state.get('state')}\n"
            f"Volatility: {data.volatility_state.get('state')}\n"
            f"Breadth: {data.breadth.get('state')}\nSector leaders: {leaders}\n"
            f"Evidence quality: {data.evidence_quality.level}. This is descriptive, not a forecast.")


def render_prediction(data: PredictionMarketResult) -> str:
    lines = ["Prediction-market state", "", "All probabilities below are market-implied evidence, not factual outcomes."]
    for row in data.markets[:8]:
        probability = row.get("probability") or {}
        lines.append(f"- {row.get('title')}: {(_number(probability.get('probability')) or 0) * 100:.1f}% "
                     f"({probability.get('source_type')}); mapped portfolio weight: {row.get('mapped_portfolio_weight', 'unavailable')}%")
    if not data.markets:
        lines.append("- No compatible stored prediction-market read model is available.")
    lines.append(f"\nEvidence quality: {data.evidence_quality.level}; calibration: {data.calibration_quality}.")
    return "\n".join(lines)
