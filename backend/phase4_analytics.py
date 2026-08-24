from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .analytical_contract import stable_fingerprint


class EvidenceConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


class TrendDirection(StrEnum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DECLINING = "DECLINING"
    UNAVAILABLE = "UNAVAILABLE"


class EligibilityResult(BaseModel):
    eligible: bool
    required_checks: dict[str, bool]
    missing_fields: list[str] = Field(default_factory=list)
    placeholder_fields: list[str] = Field(default_factory=list)
    confidence: EvidenceConfidence
    reason: str


class FundamentalTrend(BaseModel):
    direction: TrendDirection
    magnitude: float | None = None
    supporting_metrics: list[dict[str, Any]] = Field(default_factory=list)
    periods_compared: list[str] = Field(default_factory=list)
    confidence: EvidenceConfidence = EvidenceConfidence.UNAVAILABLE
    methodology: str = "reported-period-trend-v2"


class OpportunityCandidate(BaseModel):
    ticker: str
    opportunity_score: float | None
    eligibility: EligibilityResult
    fundamental_quality: float | None
    fundamental_trend: FundamentalTrend
    valuation: float | None
    momentum: float | None
    balance_sheet_quality: float | None
    portfolio_fit: float | None
    thesis_state: str | None
    supporting_evidence: list[str] = Field(default_factory=list)
    opposing_evidence: list[str] = Field(default_factory=list)
    confidence: EvidenceConfidence
    missing_fields: list[str] = Field(default_factory=list)
    calculation_version: str = "opportunity-v2"


class RelativeValuationResult(BaseModel):
    ticker: str
    eligibility: EligibilityResult
    valuation_level: float | None
    growth_support: float | None
    quality_support: float | None
    relative_value_gap: float | None
    peer_context: dict[str, Any]
    confidence: EvidenceConfidence
    inputs: dict[str, float | None]
    calculation_version: str = "relative-valuation-v2"


class PortfolioFitDelta(BaseModel):
    sector: str | None
    sector_weight_before: float | None
    sector_weight_after: float | None
    sector_weight_delta: float | None
    candidate_portfolio_correlation: float | None
    concentration_effect: str
    confidence: EvidenceConfidence


class WatchlistDominanceResult(BaseModel):
    candidate: str
    compared_incumbents: list[str]
    advantages: list[str]
    disadvantages: list[str]
    diversification_effect: PortfolioFitDelta
    confidence: EvidenceConfidence
    dominance_status: str
    candidate_type: str
    decision_score: float | None
    calculation_version: str = "watchlist-dominance-v2"


class ReplacementComparison(BaseModel):
    incumbent: str
    candidate: str
    incumbent_score: float | None
    candidate_score: float | None
    fundamental_delta: float | None
    valuation_delta: float | None
    momentum_delta: float | None
    thesis_delta: float | None
    risk_delta: float | None
    portfolio_fit: PortfolioFitDelta
    data_quality_delta: float | None
    replacement_dominance: str
    confidence: EvidenceConfidence
    calculation_version: str = "replacement-v2"


class CashAllocationResult(BaseModel):
    cash_hurdle: dict[str, Any]
    candidates: list[dict[str, Any]]
    recommended_action: str
    sizing_guidance: str
    evidence: list[str]
    risks: list[str]
    confidence: EvidenceConfidence
    calculation_version: str = "cash-allocation-v2"


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _by_ticker(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            grouped[ticker].append(row)
    return grouped


def _metric(row: dict[str, Any], name: str) -> float | None:
    return _number((row.get("metrics") or {}).get(name))


def build_fundamental_trend(periods: list[dict[str, Any]]) -> FundamentalTrend:
    """Measure reported change; never equate a high current level with improvement."""
    ordered = sorted(periods, key=lambda row: str(row.get("period_end") or ""))
    if len(ordered) < 3:
        return FundamentalTrend(direction=TrendDirection.UNAVAILABLE, periods_compared=[
            str(row.get("period_end")) for row in ordered
        ])
    latest_three = ordered[-3:]
    period_labels = [str(row.get("period_end")) for row in latest_three]
    signals: list[dict[str, Any]] = []

    def growth_signal(metric: str, label: str) -> None:
        values = [_metric(row, metric) for row in latest_three]
        if any(value is None for value in values) or values[0] == 0 or values[1] == 0:
            return
        first_growth = values[1] / abs(values[0]) - 1
        second_growth = values[2] / abs(values[1]) - 1
        delta = second_growth - first_growth
        signals.append({"metric": label, "latest": round(second_growth, 4),
                        "previous": round(first_growth, 4), "change": round(delta, 4),
                        "direction_score": _clip(delta * 250, -100, 100)})

    growth_signal("revenue", "revenue_growth_change")
    growth_signal("eps_diluted", "eps_growth_change")
    growth_signal("free_cash_flow", "free_cash_flow_growth_change")

    def ratio_signal(numerator: str, denominator: str, label: str, inverse: bool = False) -> None:
        values = []
        for row in latest_three:
            top, bottom = _metric(row, numerator), _metric(row, denominator)
            values.append(top / bottom if top is not None and bottom not in {None, 0} else None)
        if any(value is None for value in values):
            return
        change = values[-1] - values[0]
        if inverse:
            change *= -1
        signals.append({"metric": label, "latest": round(values[-1], 4),
                        "previous": round(values[0], 4), "change": round(change, 4),
                        "direction_score": _clip(change * 500, -100, 100)})

    ratio_signal("operating_income", "revenue", "operating_margin_change")
    ratio_signal("free_cash_flow", "revenue", "free_cash_flow_margin_change")
    ratio_signal("total_debt", "total_assets", "leverage_change", inverse=True)
    if len(signals) < 2:
        return FundamentalTrend(direction=TrendDirection.UNAVAILABLE, supporting_metrics=signals,
                                periods_compared=period_labels, confidence=EvidenceConfidence.LOW)
    magnitude = statistics.mean(float(row["direction_score"]) for row in signals)
    direction = (TrendDirection.IMPROVING if magnitude >= 8 else
                 TrendDirection.DECLINING if magnitude <= -8 else TrendDirection.STABLE)
    confidence = EvidenceConfidence.HIGH if len(signals) >= 4 and len(ordered) >= 5 else EvidenceConfidence.MEDIUM
    return FundamentalTrend(direction=direction, magnitude=round(magnitude, 2), supporting_metrics=signals,
                            periods_compared=period_labels, confidence=confidence)


def _price_rows(bundle: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    return sorted([row for row in bundle.get("prices") or [] if str(row.get("ticker") or "").upper() == ticker],
                  key=lambda row: str(row.get("date") or ""))


def _returns(rows: list[dict[str, Any]]) -> dict[str, float]:
    output: dict[str, float] = {}
    previous = None
    for row in rows:
        price = _number(row.get("close"))
        if price is not None and price > 0 and previous not in {None, 0}:
            output[str(row.get("date"))] = price / previous - 1
        if price is not None and price > 0:
            previous = price
    return output


def _volatility(rows: list[dict[str, Any]]) -> float | None:
    values = list(_returns(rows).values())
    return statistics.stdev(values) * math.sqrt(252) if len(values) >= 30 else None


def _correlation(left: dict[str, float], right: dict[str, float]) -> float | None:
    dates = sorted(set(left) & set(right))
    if len(dates) < 60:
        return None
    x, y = [left[key] for key in dates], [right[key] for key in dates]
    mx, my = statistics.mean(x), statistics.mean(y)
    denominator = math.sqrt(sum((v - mx) ** 2 for v in x) * sum((v - my) ** 2 for v in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / denominator if denominator else None


def _portfolio_returns(holdings: list[dict[str, Any]], bundle: dict[str, Any]) -> dict[str, float]:
    combined: dict[str, float] = defaultdict(float)
    covered: dict[str, float] = defaultdict(float)
    for holding in holdings:
        ticker, weight = str(holding.get("ticker") or "").upper(), _number(holding.get("weight")) or 0
        for date, value in _returns(_price_rows(bundle, ticker)).items():
            combined[date] += weight * value
            covered[date] += weight
    return {date: value / covered[date] for date, value in combined.items() if covered[date] > .5}


def _sector_map(bundle: dict[str, Any]) -> dict[str, str | None]:
    return {str(row.get("ticker") or "").upper(): row.get("sector") for row in bundle.get("securities") or []}


def eligibility_for_security(ticker: str, factor_row: dict[str, Any], bundle: dict[str, Any], *,
                             require_trend: bool = False) -> tuple[EligibilityResult, FundamentalTrend]:
    fundamentals = _by_ticker(bundle.get("fundamentals") or []).get(ticker, [])
    prices = _price_rows(bundle, ticker)
    trend = build_fundamental_trend(fundamentals)
    factor_keys = {
        "fundamental_quality": factor_row.get("fundamental_score"),
        "valuation": factor_row.get("valuation_score"),
        "momentum": factor_row.get("momentum_score", factor_row.get("technical_score")),
    }
    latest_price_date = _parse_date(prices[-1].get("date")) if prices else None
    freshness_days = (datetime.now(timezone.utc) - latest_price_date).days if latest_price_date else None
    latest_fundamental_date = max((_parse_date(row.get("period_end")) for row in fundamentals), default=None)
    fundamental_age_days = ((datetime.now(timezone.utc) - latest_fundamental_date).days
                            if latest_fundamental_date else None)
    quality_scores = [_number(row.get("data_quality_score")) for row in fundamentals]
    observed_quality = [value for value in quality_scores if value is not None]
    checks = {
        "required_factor_scores": all(_number(value) is not None for value in factor_keys.values()),
        "fundamental_history": len(fundamentals) >= 3,
        "fundamental_freshness": fundamental_age_days is not None and fundamental_age_days <= 180,
        "provider_quality": bool(observed_quality) and statistics.mean(observed_quality) >= .5,
        "momentum_history": len(prices) >= 126,
        "price_freshness": freshness_days is not None and freshness_days <= 10,
        "fundamental_trend": trend.direction != TrendDirection.UNAVAILABLE if require_trend else True,
    }
    missing = [name for name, passed in checks.items() if not passed]
    # Legacy factor defaults are not independently observed. They may remain visible,
    # but eligibility requires raw history rather than trusting a default-shaped number.
    placeholders = [name for name, value in factor_keys.items()
                    if _number(value) in {45.0, 50.0, 55.0, 57.0} and len(fundamentals) < 2]
    eligible = all(checks.values()) and not placeholders
    confidence = (EvidenceConfidence.HIGH if eligible and trend.confidence == EvidenceConfidence.HIGH else
                  EvidenceConfidence.MEDIUM if eligible else EvidenceConfidence.LOW)
    reason = "All required raw histories and factor fields are available." if eligible else (
        "Not rankable: " + ", ".join([*missing, *(f"placeholder:{name}" for name in placeholders)])
    )
    return EligibilityResult(eligible=eligible, required_checks=checks, missing_fields=missing,
                             placeholder_fields=placeholders, confidence=confidence, reason=reason), trend


def _balance_sheet_quality(periods: list[dict[str, Any]]) -> float | None:
    if not periods:
        return None
    latest = max(periods, key=lambda row: str(row.get("period_end") or ""))
    debt, assets, cash = _metric(latest, "total_debt"), _metric(latest, "total_assets"), _metric(latest, "cash")
    if assets in {None, 0} or debt is None:
        return None
    leverage = debt / assets
    cash_offset = min(.25, (cash or 0) / assets)
    return round(_clip(100 - leverage * 120 + cash_offset * 80), 2)


def _portfolio_fit(ticker: str, row: dict[str, Any], holdings: list[dict[str, Any]], bundle: dict[str, Any]) -> float:
    sector_map = _sector_map(bundle)
    sector = sector_map.get(ticker)
    sector_weight = sum((_number(item.get("weight")) or 0) for item in holdings
                        if sector and sector_map.get(str(item.get("ticker") or "").upper()) == sector)
    position_weight = _number(row.get("weight")) or 0
    risk = _number(row.get("risk_contribution")) or position_weight
    return round(_clip(100 - max(0, sector_weight - .25) * 120 - position_weight * 100 - risk * 50), 2)


def build_opportunity_candidates(holdings: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    fundamentals = _by_ticker(bundle.get("fundamentals") or [])
    output: list[OpportunityCandidate] = []
    for row in holdings:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        eligibility, trend = eligibility_for_security(ticker, row, bundle)
        quality = _number(row.get("fundamental_score"))
        valuation = _number(row.get("valuation_score"))
        momentum = _number(row.get("momentum_score"))
        balance = _balance_sheet_quality(fundamentals.get(ticker, []))
        fit = _portfolio_fit(ticker, row, holdings, bundle)
        trend_score = None if trend.magnitude is None else _clip(50 + trend.magnitude / 2)
        components = [quality, valuation, momentum, balance, fit, trend_score]
        score = None if not eligibility.eligible or any(value is None for value in components) else round(
            quality * .25 + trend_score * .20 + valuation * .20 + momentum * .15 + balance * .10 + fit * .10, 2
        )
        supporting = []
        opposing = []
        if trend.direction == TrendDirection.IMPROVING:
            supporting.append("Reported fundamental trend is improving across comparable stored periods.")
        elif trend.direction == TrendDirection.DECLINING:
            opposing.append("Reported fundamental trend is declining.")
        if valuation is not None and valuation >= 60:
            supporting.append("Stored valuation evidence is supportive relative to the portfolio scale.")
        elif valuation is not None and valuation < 45:
            opposing.append("Stored valuation evidence is demanding or weak.")
        if momentum is not None and momentum >= 60:
            supporting.append("Stored price momentum is positive.")
        if fit < 45:
            opposing.append("Current position/sector concentration reduces incremental portfolio fit.")
        output.append(OpportunityCandidate(
            ticker=ticker, opportunity_score=score, eligibility=eligibility,
            fundamental_quality=quality, fundamental_trend=trend, valuation=valuation,
            momentum=momentum, balance_sheet_quality=balance, portfolio_fit=fit,
            thesis_state=row.get("thesis_status"), supporting_evidence=supporting,
            opposing_evidence=opposing, confidence=eligibility.confidence,
            missing_fields=eligibility.missing_fields,
        ))
    return [row.model_dump(mode="json") for row in sorted(
        output, key=lambda item: (item.eligibility.eligible, item.opportunity_score or -1), reverse=True
    )]


def _valuation_inputs(ticker: str, bundle: dict[str, Any]) -> dict[str, float | None]:
    periods = _by_ticker(bundle.get("fundamentals") or []).get(ticker, [])
    prices = _price_rows(bundle, ticker)
    if not periods or not prices:
        return {"pe": None, "price_to_sales": None, "free_cash_flow_yield": None, "eps_growth": None}
    latest = max(periods, key=lambda row: str(row.get("period_end") or ""))
    previous = sorted(periods, key=lambda row: str(row.get("period_end") or ""))[-2] if len(periods) >= 2 else {}
    price = _number(prices[-1].get("close"))
    eps, shares = _metric(latest, "eps_diluted"), _metric(latest, "shares_diluted")
    revenue, fcf = _metric(latest, "revenue"), _metric(latest, "free_cash_flow")
    prior_eps = _metric(previous, "eps_diluted")
    market_cap = price * shares if price and shares else None
    return {
        "pe": price / eps if price and eps and eps > 0 else None,
        "price_to_sales": market_cap / revenue if market_cap and revenue and revenue > 0 else None,
        "free_cash_flow_yield": fcf / market_cap if fcf is not None and market_cap else None,
        "eps_growth": eps / abs(prior_eps) - 1 if eps is not None and prior_eps not in {None, 0} else None,
    }


def build_relative_valuation(holdings: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    sectors = _sector_map(bundle)
    interim = []
    for row in holdings:
        ticker = str(row.get("ticker") or "").upper()
        eligibility, _ = eligibility_for_security(ticker, row, bundle)
        inputs = _valuation_inputs(ticker, bundle)
        available = [inputs[key] for key in ("pe", "price_to_sales", "free_cash_flow_yield") if inputs[key] is not None]
        valuation_level = None
        if available:
            burdens = []
            if inputs["pe"] is not None: burdens.append(_clip((inputs["pe"] - 10) * 2.5))
            if inputs["price_to_sales"] is not None: burdens.append(_clip(inputs["price_to_sales"] * 10))
            if inputs["free_cash_flow_yield"] is not None: burdens.append(_clip(70 - inputs["free_cash_flow_yield"] * 800))
            valuation_level = statistics.mean(burdens)
        growth = inputs["eps_growth"]
        growth_support = _clip(50 + growth * 100) if growth is not None else None
        quality = _number(row.get("fundamental_score"))
        gap = None if valuation_level is None or growth_support is None or quality is None else round(
            valuation_level - growth_support * .55 - quality * .45, 2
        )
        interim.append({"ticker": ticker, "row": row, "eligibility": eligibility, "inputs": inputs,
                        "valuation_level": valuation_level, "growth_support": growth_support,
                        "quality": quality, "gap": gap, "sector": sectors.get(ticker)})
    output = []
    for item in interim:
        peers = [other["gap"] for other in interim if other["ticker"] != item["ticker"] and
                 other["sector"] and other["sector"] == item["sector"] and other["gap"] is not None]
        peer_context = ({"available": True, "sector": item["sector"], "peer_count": len(peers),
                         "peer_median_gap": round(statistics.median(peers), 2)} if len(peers) >= 2 else
                        {"available": False, "sector": item["sector"], "peer_count": len(peers),
                         "reason": "Fewer than two eligible stored sector peers."})
        confidence = (EvidenceConfidence.HIGH if item["eligibility"].eligible and peer_context["available"] else
                      EvidenceConfidence.MEDIUM if item["eligibility"].eligible and item["gap"] is not None else EvidenceConfidence.LOW)
        output.append(RelativeValuationResult(
            ticker=item["ticker"], eligibility=item["eligibility"],
            valuation_level=None if item["valuation_level"] is None else round(item["valuation_level"], 2),
            growth_support=None if item["growth_support"] is None else round(item["growth_support"], 2),
            quality_support=item["quality"], relative_value_gap=item["gap"], peer_context=peer_context,
            confidence=confidence, inputs=item["inputs"],
        ).model_dump(mode="json"))
    return sorted(output, key=lambda row: row.get("relative_value_gap") if row.get("relative_value_gap") is not None else -999,
                  reverse=True)


def portfolio_fit_delta(candidate: str, holdings: list[dict[str, Any]], bundle: dict[str, Any], *,
                        allocation: float = .01, replace_ticker: str | None = None) -> PortfolioFitDelta:
    sectors = _sector_map(bundle)
    sector = sectors.get(candidate)
    before = sum((_number(row.get("weight")) or 0) for row in holdings
                 if sector and sectors.get(str(row.get("ticker") or "").upper()) == sector)
    removed = next(((_number(row.get("weight")) or 0) for row in holdings
                    if str(row.get("ticker") or "").upper() == replace_ticker), 0)
    removed_same_sector = removed if replace_ticker and sectors.get(replace_ticker) == sector else 0
    add = removed if replace_ticker else allocation
    after = before - removed_same_sector + add
    if not replace_ticker:
        after = after / (1 + add)
    correlation = _correlation(_returns(_price_rows(bundle, candidate)), _portfolio_returns(holdings, bundle))
    effect = "IMPROVES" if after < before - .005 else "WORSENS" if after > before + .005 else "NEUTRAL"
    return PortfolioFitDelta(
        sector=sector, sector_weight_before=round(before, 4) if sector else None,
        sector_weight_after=round(after, 4) if sector else None,
        sector_weight_delta=round(after - before, 4) if sector else None,
        candidate_portfolio_correlation=None if correlation is None else round(correlation, 4),
        concentration_effect=effect,
        confidence=EvidenceConfidence.HIGH if sector and correlation is not None else EvidenceConfidence.MEDIUM if sector else EvidenceConfidence.LOW,
    )


def _candidate_decision_score(row: dict[str, Any], bundle: dict[str, Any]) -> float | None:
    values = [_number(row.get(key)) for key in ("fundamental_score", "valuation_score", "technical_score")]
    confidence = _number(row.get("confidence"))
    vol = _volatility(_price_rows(bundle, str(row.get("ticker") or "").upper()))
    if any(value is None for value in values) or confidence is None or vol is None:
        return None
    risk_score = _clip(100 - vol * 100)
    return round(values[0] * .25 + values[1] * .20 + values[2] * .20 + confidence * .15 + risk_score * .20, 2)


def build_watchlist_dominance(research: list[dict[str, Any]], holdings: list[dict[str, Any]],
                              bundle: dict[str, Any]) -> list[dict[str, Any]]:
    weakest = sorted(holdings, key=lambda row: _number(row.get("health_score")) or 0)[:5]
    confidence_map = {"LOW": 35.0, "MEDIUM": 65.0, "HIGH": 90.0}

    def incumbent_decision_score(row: dict[str, Any]) -> float | None:
        factors = [_number(row.get(key)) for key in ("fundamental_score", "valuation_score", "momentum_score")]
        confidence = confidence_map.get(str(row.get("data_confidence") or "").upper())
        vol = _volatility(_price_rows(bundle, str(row.get("ticker") or "").upper()))
        if any(value is None for value in factors) or confidence is None or vol is None:
            return None
        return factors[0] * .25 + factors[1] * .20 + factors[2] * .20 + confidence * .15 + _clip(100 - vol * 100) * .20

    incumbent_composites = [incumbent_decision_score(item) for item in weakest]
    output = []
    for row in research:
        ticker = str(row.get("ticker") or "").upper()
        candidate_type = str(row.get("candidate_eligibility") or row.get("candidate_type") or "NEW_POSITION")
        fit = portfolio_fit_delta(ticker, holdings, bundle)
        score = _candidate_decision_score(row, bundle)
        incumbent_floor = statistics.mean([value for value in incumbent_composites if value is not None]) if any(
            value is not None for value in incumbent_composites
        ) else None
        advantages, disadvantages = [], []
        if score is not None and incumbent_floor is not None and score >= incumbent_floor + 5:
            advantages.append("Composite evidence/risk score exceeds the weakest-holding comparison set by at least five points.")
        if fit.concentration_effect == "IMPROVES": advantages.append("Incremental sector concentration improves.")
        if fit.concentration_effect == "WORSENS": disadvantages.append("Incremental sector concentration worsens.")
        if fit.candidate_portfolio_correlation is not None and fit.candidate_portfolio_correlation > .75:
            disadvantages.append("Stored return history is highly correlated with the current portfolio.")
        dominated = bool(score is not None and incumbent_floor is not None and score >= incumbent_floor + 5 and
                         fit.concentration_effect != "WORSENS" and candidate_type != "ADD_TO_EXISTING")
        status = "DOMINATES" if dominated else "ADD_TO_EXISTING_SUPPORTED" if candidate_type == "ADD_TO_EXISTING" and score is not None else "NO_CLEAR_DOMINANCE"
        confidence = EvidenceConfidence.HIGH if score is not None and fit.confidence == EvidenceConfidence.HIGH else EvidenceConfidence.MEDIUM if score is not None else EvidenceConfidence.LOW
        output.append(WatchlistDominanceResult(
            candidate=ticker, compared_incumbents=[str(item.get("ticker")) for item in weakest],
            advantages=advantages, disadvantages=disadvantages, diversification_effect=fit,
            confidence=confidence, dominance_status=status, candidate_type=candidate_type,
            decision_score=score,
        ).model_dump(mode="json") | {"factor_scores": {
            "fundamentals": _number(row.get("fundamental_score")),
            "valuation": _number(row.get("valuation_score")),
            "momentum": _number(row.get("technical_score")),
            "confidence": _number(row.get("confidence")),
            "volatility": _volatility(_price_rows(bundle, ticker)),
        }})
    return sorted(output, key=lambda row: row.get("decision_score") or -1, reverse=True)


def build_replacement_comparisons(theses: list[dict[str, Any]], dominance: list[dict[str, Any]],
                                  holdings: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if not theses:
        return []
    thesis_tickers = {str(row.get("ticker") or "").upper() for row in theses}
    incumbents = sorted([row for row in holdings if str(row.get("ticker") or "").upper() in thesis_tickers],
                        key=lambda row: _number(row.get("health_score")) or 0)
    if not incumbents:
        return []
    incumbent = incumbents[0]
    output = []
    for candidate in dominance:
        if candidate.get("candidate_type") == "ADD_TO_EXISTING":
            continue
        ticker = str(candidate["candidate"])
        research_score = _number(candidate.get("decision_score"))
        incumbent_score = _number(incumbent.get("health_score"))
        fit = portfolio_fit_delta(ticker, holdings, bundle, replace_ticker=str(incumbent.get("ticker")))
        factors = candidate.get("factor_scores") or {}
        fundamental_delta = (None if _number(factors.get("fundamentals")) is None or _number(incumbent.get("fundamental_score")) is None
                             else round(_number(factors.get("fundamentals")) - _number(incumbent.get("fundamental_score")), 2))
        valuation_delta = (None if _number(factors.get("valuation")) is None or _number(incumbent.get("valuation_score")) is None
                           else round(_number(factors.get("valuation")) - _number(incumbent.get("valuation_score")), 2))
        momentum_delta = (None if _number(factors.get("momentum")) is None or _number(incumbent.get("momentum_score")) is None
                          else round(_number(factors.get("momentum")) - _number(incumbent.get("momentum_score")), 2))
        candidate_vol = _number(factors.get("volatility"))
        incumbent_vol = _volatility(_price_rows(bundle, str(incumbent.get("ticker") or "").upper()))
        risk_delta = None if candidate_vol is None or incumbent_vol is None else round(incumbent_vol - candidate_vol, 4)
        quality_map = {"LOW": 35.0, "MEDIUM": 65.0, "HIGH": 90.0}
        incumbent_quality = quality_map.get(str(incumbent.get("data_confidence") or "").upper())
        data_quality_delta = None if _number(factors.get("confidence")) is None or incumbent_quality is None else round(
            _number(factors.get("confidence")) - incumbent_quality, 2
        )
        required_deltas = [fundamental_delta, valuation_delta, momentum_delta, risk_delta]
        dominates_dimensions = sum(value is not None and value > 0 for value in required_deltas)
        dominance_status = "REPLACEMENT_SUPPORTED" if (
            candidate.get("dominance_status") == "DOMINATES" and fit.concentration_effect != "WORSENS"
            and all(value is not None for value in required_deltas) and dominates_dimensions >= 3
        ) else "NO_CLEAR_REPLACEMENT"
        output.append(ReplacementComparison(
            incumbent=str(incumbent.get("ticker")), candidate=ticker,
            incumbent_score=incumbent_score, candidate_score=research_score,
            fundamental_delta=fundamental_delta, valuation_delta=valuation_delta, momentum_delta=momentum_delta,
            thesis_delta=None, risk_delta=risk_delta, portfolio_fit=fit, data_quality_delta=data_quality_delta,
            replacement_dominance=dominance_status,
            confidence=EvidenceConfidence.MEDIUM if research_score is not None else EvidenceConfidence.LOW,
        ).model_dump(mode="json"))
    return output


def build_cash_allocation(dominance: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    configured_yield = _number(profile.get("cash_hurdle_yield"))
    if configured_yield is None:
        configured_yield = _number(profile.get("cash_yield"))
    hurdle = {
        "available": configured_yield is not None,
        "annual_yield": configured_yield,
        "source": profile.get("cash_hurdle_source") or ("user_profile" if configured_yield is not None else None),
        "as_of": profile.get("cash_hurdle_as_of"),
        "reason": None if configured_yield is not None else "No supported cash/risk-free yield is stored for this portfolio.",
    }
    candidates = [row for row in dominance if row.get("dominance_status") in {"DOMINATES", "ADD_TO_EXISTING_SUPPORTED"}]
    if configured_yield is None:
        action, confidence = "NO_CLEAR_EDGE", EvidenceConfidence.UNAVAILABLE
    elif not candidates:
        action, confidence = "HOLD_CASH", EvidenceConfidence.MEDIUM
    else:
        action, confidence = "PARTIAL_DEPLOYMENT", EvidenceConfidence.MEDIUM
    return CashAllocationResult(
        cash_hurdle=hurdle, candidates=candidates[:5], recommended_action=action,
        sizing_guidance=("No deployment sizing is supported until a cash hurdle is available." if configured_yield is None
                         else "Stage deployment; exact sizing requires the configured risk budget and transaction-cost model."),
        evidence=["Candidate ordering uses stored fundamentals, valuation, momentum, volatility, confidence, and incremental concentration."],
        risks=["No expected-return forecast is used.", "Transaction costs and tax lots are not inferred."],
        confidence=confidence,
    ).model_dump(mode="json")


def build_score_attributions(holdings: list[dict[str, Any]], *, methodology_version: str = "portfolio-health-v1",
                             baseline_calculation_version: str | None = None) -> list[dict[str, Any]]:
    weights = {"fundamentals": .30, "valuation": .20, "momentum": .15, "risk_contribution": -20.0}
    output = []
    for row in holdings:
        changes = dict(row.get("component_changes") or {})
        current = _number(row.get("health_score"))
        total_delta = _number(row.get("change"))
        contributions = []
        for component, delta_value in changes.items():
            delta = _number(delta_value)
            if delta is None or component not in weights:
                continue
            impact = delta * weights[component]
            contributions.append({"component": component, "input_delta": delta, "score_impact": round(impact, 4)})
        explained = sum(row["score_impact"] for row in contributions)
        methodology_change = (None if not baseline_calculation_version or baseline_calculation_version == methodology_version else
                              {"previous": baseline_calculation_version, "current": methodology_version})
        comparable = bool(contributions and row.get("baseline_timestamp") and methodology_change is None)
        output.append({
            "ticker": row.get("ticker"), "current_score": current,
            "previous_score": None if current is None or total_delta is None else round(current - total_delta, 4),
            "total_delta": total_delta, "component_deltas": sorted(contributions, key=lambda item: abs(item["score_impact"]), reverse=True),
            "input_changes": changes, "methodology_change": methodology_change,
            "baseline_timestamp": row.get("baseline_timestamp"),
            "unexplained_delta": None if total_delta is None or not contributions else round(total_delta - explained, 4),
            "confidence": EvidenceConfidence.MEDIUM.value if comparable else EvidenceConfidence.LOW.value,
            "comparable_baseline": comparable,
            "calculation_version": "score-attribution-v2", "methodology_version": methodology_version,
        })
    return output


def build_material_change_set(changes: list[dict[str, Any]], holdings: list[dict[str, Any]], *,
                              baseline_available: bool, baseline_identity: dict[str, Any] | None) -> dict[str, Any]:
    if not baseline_available:
        return {"baseline_status": "NO_BASELINE", "changes": [], "calculation_version": "portfolio-change-v2",
                "materiality_thresholds": {"health_score_points": 2.0, "factor_points": 5.0, "weight_points": .01}}
    material = []
    for row in changes:
        delta = abs(_number(row.get("delta")) or 0)
        if delta >= 2 or str(row.get("type") or "").upper() not in {"HEALTH_SCORE", "COMPONENT"}:
            material.append({"domain": row.get("type") or "PORTFOLIO", "entity": row.get("ticker"),
                             "before": row.get("before"), "after": row.get("after"), "delta": row.get("delta"),
                             "materiality": "HIGH" if delta >= 5 else "MEDIUM", "reason": row.get("title") or row.get("reason")})
    for holding in holdings:
        for component, delta_value in (holding.get("component_changes") or {}).items():
            delta = _number(delta_value)
            threshold = .01 if component == "risk_contribution" else 5
            if delta is not None and abs(delta) >= threshold:
                material.append({"domain": "HOLDING_COMPONENT", "entity": holding.get("ticker"),
                                 "before": None, "after": None, "delta": delta,
                                 "materiality": "HIGH" if abs(delta) >= threshold * 2 else "MEDIUM",
                                 "reason": f"{component} crossed the materiality threshold."})
    return {"baseline_status": "MATERIAL_CHANGE" if material else "NO_MATERIAL_CHANGE", "changes": material,
            "baseline_identity": baseline_identity, "calculation_version": "portfolio-change-v2",
            "materiality_thresholds": {"health_score_points": 2.0, "factor_points": 5.0, "weight_points": .01}}


def build_thesis_invalidation(theses: list[dict[str, Any]], holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ticker = {str(row.get("ticker") or "").upper(): row for row in theses}
    largest = sorted(holdings, key=lambda row: _number(row.get("weight")) or 0, reverse=True)[:10]
    output = []
    for holding in largest:
        ticker = str(holding.get("ticker") or "").upper()
        thesis = by_ticker.get(ticker)
        breakers = list((thesis or {}).get("thesis_breakers") or [
            row for row in (thesis or {}).get("factors") or [] if row.get("factor_type") == "BREAKER"
        ])
        output.append({"ticker": ticker, "thesis_exists": thesis is not None,
                       "explicit_breakers": breakers, "monitored_evidence": (thesis or {}).get("assumptions") or [],
                       "current_breaker_status": [row.get("status") for row in breakers],
                       "missing_evidence": [] if thesis else ["saved_thesis"],
                       "calculation_version": "thesis-invalidation-v2"})
    return output


def build_countercase(opportunities: list[dict[str, Any]], holdings: list[dict[str, Any]],
                      intelligence: dict[str, Any], input_fingerprint: str) -> dict[str, Any]:
    candidate = next((row for row in opportunities if row.get("eligibility", {}).get("eligible")), None)
    if not candidate:
        return {"recommendation_id": None, "ticker": None, "strongest_counterarguments": [],
                "unresolved_unknowns": ["No eligible leading opportunity exists."], "confidence": "UNAVAILABLE",
                "calculation_version": "countercase-v2"}
    ticker = candidate["ticker"]
    holding = next((row for row in holdings if str(row.get("ticker") or "").upper() == ticker), {})
    arguments = [{"category": "OPPORTUNITY_EVIDENCE", "severity": "MEDIUM", "evidence": text}
                 for text in candidate.get("opposing_evidence") or []]
    risk = _number(holding.get("risk_contribution"))
    if risk is not None and risk >= .05:
        arguments.append({"category": "PORTFOLIO_RISK", "severity": "HIGH",
                          "evidence": f"Modeled risk contribution is {risk:.1%}."})
    for exposure in intelligence.get("economic_dependencies") or []:
        if ticker in (exposure.get("holdings") or []):
            arguments.append({"category": "ECONOMIC_DEPENDENCY", "severity": str(exposure.get("strength") or "MEDIUM"),
                              "evidence": f"Exposed to {exposure.get('factor')}: {exposure.get('mechanism')}."})
    identity = stable_fingerprint({"ticker": ticker, "input_fingerprint": input_fingerprint,
                                   "calculation_version": "opportunity-v2"})
    return {"recommendation_id": identity, "calculation_version": "countercase-v2",
            "source_calculation_version": "opportunity-v2", "input_fingerprint": input_fingerprint,
            "ticker": ticker, "timestamp": datetime.now(timezone.utc).isoformat(),
            "strongest_counterarguments": arguments[:8], "severity": "HIGH" if any(row["severity"] == "HIGH" for row in arguments) else "MEDIUM",
            "unresolved_unknowns": candidate.get("missing_fields") or [], "confidence": candidate.get("confidence")}


SCENARIO_FACTOR_REGISTRY = {
    "interest_rates:increase": {"canonical_name": "interest_rates", "aliases": ["rates rose", "higher rates"],
                                 "supported_model": "cached empirical simulation", "direction": "increase"},
    "economic_growth:decrease": {"canonical_name": "economic_growth", "aliases": ["recession"],
                                  "supported_model": "cached empirical simulation", "direction": "decrease"},
    "ai_capex:decrease": {"canonical_name": "ai_capex", "aliases": ["AI spending slowed", "AI capex slowdown"],
                           "supported_model": "mapped economic dependency exposure", "direction": "decrease"},
}


def build_scenario_support(simulation: dict[str, Any] | None, intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = ((simulation or {}).get("input") or {}).get("scenario") or {}
    output = []
    if scenario.get("rate_state") == "tightening":
        output.append({"factor": "interest_rates", "direction": "increase", "support_type": "EMPIRICAL_SIMULATION",
                       "model": (simulation or {}).get("model_version"), "exact": True})
    if scenario.get("economic_state") == "recession":
        output.append({"factor": "economic_growth", "direction": "decrease", "support_type": "EMPIRICAL_SIMULATION",
                       "model": (simulation or {}).get("model_version"), "exact": True})
    ai = next((row for row in intelligence.get("economic_dependencies") or []
               if row.get("factor") == "AI_INFRASTRUCTURE_DEMAND"), None)
    if ai:
        output.append({"factor": "ai_capex", "direction": "decrease", "support_type": "QUALITATIVE_EXPOSURE_STRESS",
                       "model": "economic-dependency-mapping-v1", "exact": True,
                       "affected_holdings": ai.get("holdings") or [],
                       "mapped_portfolio_weight": ai.get("mapped_portfolio_weight"),
                       "methodology": "Exposure mapping only; no simulated loss magnitude is claimed."})
    return output


def build_portfolio_events(events: list[dict[str, Any]], holdings: list[dict[str, Any]]) -> dict[str, Any]:
    weights = {str(row.get("ticker") or "").upper(): _number(row.get("weight")) or 0 for row in holdings}
    normalized = []
    covered_categories = set()
    for event in events:
        event_date = _parse_date(event.get("starts_at") or event.get("date"))
        if event_date and event_date < datetime.now(timezone.utc):
            continue
        raw_type = str(event.get("event_type") or event.get("type") or event.get("category") or "").upper()
        title = str(event.get("title") or event.get("name") or "")
        if "EARN" in raw_type or "EARN" in title.upper(): category = "EARNINGS"
        elif any(token in raw_type for token in ("ECONOMIC", "MACRO", "FED", "CPI")): category = "MACRO"
        elif "PREDICTION" in raw_type or event.get("provider") in {"polymarket", "kalshi"}: category = "PREDICTION_MARKET_EVENT"
        elif "THESIS" in raw_type: category = "THESIS_REVIEW"
        else: category = "COMPANY_CATALYST"
        tickers = [str(value).upper() for value in (event.get("affected_holdings") or event.get("tickers") or [])]
        affected_weight = sum(weights.get(ticker, 0) for ticker in set(tickers))
        materiality = "HIGH" if affected_weight >= .10 else "MEDIUM" if affected_weight >= .03 else "LOW"
        confidence = "HIGH" if event.get("verified_at") and event.get("starts_at") else "MEDIUM" if event.get("starts_at") else "LOW"
        normalized.append({"event_type": category, "date": event.get("starts_at") or event.get("date"),
                           "title": title, "affected_entities": tickers,
                           "affected_portfolio_weight": round(affected_weight, 4),
                           "estimated_materiality": materiality,
                           "reason": f"Maps to {affected_weight:.1%} of current portfolio weight.",
                           "source": event.get("provider") or event.get("source_url"),
                           "freshness": event.get("verified_at"), "confidence": confidence})
        covered_categories.add(category)
    requested = {ticker for ticker in weights if ticker != "CASH"}
    earnings_entities = {
        ticker for row in normalized if row["event_type"] == "EARNINGS"
        for ticker in row.get("affected_entities") or [] if ticker in requested
    }
    earnings_weight = sum(weights.get(ticker, 0) for ticker in earnings_entities)
    newest_by_category: dict[str, str | None] = {}
    for category in covered_categories:
        newest_by_category[category] = max(
            (str(row.get("freshness") or "") for row in normalized if row["event_type"] == category),
            default="",
        ) or None
    completeness = {
        "earnings": "CURRENT" if requested and earnings_entities == requested else "PARTIAL" if earnings_entities else "MISSING",
        "macro_calendar": "CURRENT" if "MACRO" in covered_categories else "MISSING",
        "company_catalysts": "CURRENT" if "COMPANY_CATALYST" in covered_categories else "MISSING",
        "prediction_markets": "CURRENT" if "PREDICTION_MARKET_EVENT" in covered_categories else "MISSING",
    }
    health = {
        "earnings": {"status": completeness["earnings"], "entity_coverage": len(earnings_entities) / len(requested) if requested else None,
                     "portfolio_weight_coverage": earnings_weight, "freshness": newest_by_category.get("EARNINGS")},
        "macro": {"status": completeness["macro_calendar"], "event_count": sum(row["event_type"] == "MACRO" for row in normalized),
                  "freshness": newest_by_category.get("MACRO")},
        "company_catalysts": {"status": completeness["company_catalysts"],
                              "event_count": sum(row["event_type"] == "COMPANY_CATALYST" for row in normalized),
                              "freshness": newest_by_category.get("COMPANY_CATALYST")},
        "prediction_market_events": {"status": completeness["prediction_markets"],
                                     "event_count": sum(row["event_type"] == "PREDICTION_MARKET_EVENT" for row in normalized),
                                     "freshness": newest_by_category.get("PREDICTION_MARKET_EVENT")},
    }
    return {"events": sorted(normalized, key=lambda row: (row.get("date") or "", row["title"])),
            "category_completeness": completeness,
            "event_coverage_health": health,
            "provider_limitations": {
                "earnings": "No configured ingestion adapter currently supplies an earnings calendar." if completeness["earnings"] == "MISSING" else None,
                "macro": "FRED observations do not supply a forward release calendar in the configured adapter." if completeness["macro_calendar"] == "MISSING" else None,
                "company_catalysts": "Stored structured events only; arbitrary news is not promoted to a guaranteed catalyst." if completeness["company_catalysts"] != "CURRENT" else None,
            },
            "complete": all(completeness[key] == "CURRENT" for key in ("earnings", "macro_calendar", "company_catalysts")),
            "calculation_version": "portfolio-events-v3"}


def build_data_quality(holdings: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for row in holdings:
        ticker = str(row.get("ticker") or "").upper()
        eligibility, trend = eligibility_for_security(ticker, row, bundle)
        passed = sum(eligibility.required_checks.values())
        total = len(eligibility.required_checks)
        trust = ("NOT_RANKABLE" if not eligibility.eligible else "HIGH" if passed == total and trend.confidence == EvidenceConfidence.HIGH
                 else "MEDIUM" if passed >= total - 1 else "LOW")
        output.append({"ticker": ticker, "trust_classification": trust,
                       "rankable": eligibility.eligible, "eligibility": eligibility.model_dump(mode="json"),
                       "fundamental_trend_available": trend.direction != TrendDirection.UNAVAILABLE,
                       "lineage_available": bool(_by_ticker(bundle.get("fundamentals") or []).get(ticker)),
                       "calculation_version": "data-quality-v2"})
    order = {"NOT_RANKABLE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    return sorted(output, key=lambda row: (order[row["trust_classification"]], row["ticker"]))


def build_rebalance_contract(optimizer: dict[str, Any] | None, input_fingerprint: str,
                             holdings: list[dict[str, Any]]) -> dict[str, Any]:
    optimizer = optimizer or {}
    run_fingerprint = optimizer.get("portfolio_context_version") or optimizer.get("input_fingerprint")
    alternatives = optimizer.get("alternatives") or []
    selected = next((row for row in alternatives if row.get("name") == "Balanced"), None)
    diagnostics = optimizer.get("model_diagnostics") or {}
    status = str((selected or {}).get("constraint_status") or diagnostics.get("constraint_status") or optimizer.get("constraint_status") or "").upper()
    feasible = status in {"FEASIBLE", "SATISFIED", "OPTIMAL", "SUCCESS"}
    fingerprint_match = bool(run_fingerprint and run_fingerprint == input_fingerprint)
    tax_lots = optimizer.get("tax_lots") or []
    cost_model = optimizer.get("trading_cost_model") or optimizer.get("transaction_cost_assumptions")
    actionable = bool(optimizer and selected and feasible and fingerprint_match)
    return {"actionable": actionable, "feasibility": status or "NOT_TRACKED",
            "current_weights": optimizer.get("current_weights") or {row.get("ticker"): row.get("weight") for row in holdings},
            "target_weights": (selected or {}).get("allocations") if actionable else None,
            "trades": (selected or {}).get("trades") if actionable else None,
            "expected_turnover": (selected or {}).get("turnover"),
            "estimated_costs": (selected or {}).get("estimated_costs") if cost_model else None,
            "trading_cost_model": cost_model or "UNAVAILABLE",
            "tax_aware": bool(tax_lots and (selected or {}).get("tax")), "tax_data_available": bool(tax_lots),
            "constraint_violations": (selected or {}).get("conflicts") or [],
            "portfolio_fingerprint_match": fingerprint_match,
            "portfolio_effects": {"effective_holdings": (selected or {}).get("effective_holdings")},
            "confidence": "HIGH" if actionable and cost_model and tax_lots else "MEDIUM" if actionable else "UNAVAILABLE",
            "calculation_version": "rebalance-actionability-v2"}
