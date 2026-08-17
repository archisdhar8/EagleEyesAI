from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


AttentionType = Literal[
    "THESIS_BREAKER_TRIGGERED", "THESIS_BREAKER_WARNING", "THESIS_WEAKENED", "THESIS_STRENGTHENED",
    "IMPORTANT_ASSUMPTION_CHANGE", "MATERIAL_ESTIMATE_REVISION", "MATERIAL_EARNINGS_CHANGE",
    "GUIDANCE_CHANGE", "MATERIAL_NEWS_EVENT", "PREDICTION_MARKET_CHANGE", "MACRO_CHANGE",
    "PORTFOLIO_RISK_CHANGE", "UPCOMING_EARNINGS", "UPCOMING_REVIEW", "WATCHLIST_THRESHOLD",
    "SCENARIO_RISK_CHANGE", "DATA_QUALITY_WARNING",
]
Materiality = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
Relevance = Literal["DIRECT", "HIGH", "MODERATE", "LOW", "NONE"]
Quality = Literal["HIGH", "MODERATE", "LOW", "INSUFFICIENT_DATA"]
Freshness = Literal["CURRENT", "STALE", "UNAVAILABLE"]
Urgency = Literal["IMMEDIATE", "SOON", "NORMAL", "LOW"]
Exposure = Literal["HIGH", "MODERATE", "LOW", "NONE"]
AttentionState = Literal["UNREAD", "READ", "DISMISSED", "SNOOZED", "RESOLVED"]


class AttentionSource(BaseModel):
    label: str
    provider: str
    as_of: str | None = None
    url: str | None = None


class AttentionItem(BaseModel):
    id: str
    type: AttentionType
    entity_type: str
    entity_key: str
    title: str
    summary: str
    what_changed: str
    why_it_matters: str
    materiality: Materiality
    thesis_relevance: Relevance = "NONE"
    portfolio_relevance: Relevance = "NONE"
    evidence_quality: Quality
    freshness: Freshness
    urgency: Urgency
    occurred_at: str
    sources: list[AttentionSource] = Field(default_factory=list)
    linked_thesis_id: str | None = None
    linked_decision_id: str | None = None
    linked_portfolio_exposure: dict[str, Any] | None = None
    linked_scenario: str | None = None
    action_label: str
    action_target: str
    ask_prompts: list[str] = Field(default_factory=list)
    affected: list[str] = Field(default_factory=list)
    details: list[dict[str, Any]] = Field(default_factory=list)
    state: AttentionState = "UNREAD"
    state_until: str | None = None
    ranking_inputs: dict[str, str]
    group_key: str
    attention_score: float = Field(exclude=True)


MATERIALITY_FACTOR = {"CRITICAL": 5.0, "HIGH": 4.0, "MEDIUM": 2.5, "LOW": 1.0, "UNKNOWN": .6}
RELEVANCE_FACTOR = {"DIRECT": 2.0, "HIGH": 1.75, "MODERATE": 1.25, "LOW": .75, "NONE": .25}
QUALITY_FACTOR = {"HIGH": 1.2, "MODERATE": 1.0, "LOW": .65, "INSUFFICIENT_DATA": .35}
URGENCY_FACTOR = {"IMMEDIATE": 1.4, "SOON": 1.2, "NORMAL": 1.0, "LOW": .8}
EXPOSURE_FACTOR = {"HIGH": 1.5, "MODERATE": 1.25, "LOW": 1.0, "NONE": .75}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any, fallback: datetime) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return str(value) if value else fallback.isoformat()


def _utc_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return fallback


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _id(group_key: str, occurred_at: str) -> str:
    # The date bucket keeps state stable through same-day refreshes without
    # suppressing a genuinely new event on a later day.
    material = f"{group_key}|{occurred_at[:10]}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def rank_attention(*, materiality: Materiality, thesis_relevance: Relevance,
                   portfolio_relevance: Relevance, evidence_quality: Quality,
                   urgency: Urgency, exposure: Exposure, breaker: bool = False) -> tuple[float, dict[str, str]]:
    relevance = max(RELEVANCE_FACTOR[thesis_relevance], RELEVANCE_FACTOR[portfolio_relevance])
    score = (MATERIALITY_FACTOR[materiality] * relevance * QUALITY_FACTOR[evidence_quality]
             * URGENCY_FACTOR[urgency] * EXPOSURE_FACTOR[exposure] * 10)
    if breaker:
        score += 50
    inputs = {
        "materiality": materiality, "thesis_relevance": thesis_relevance,
        "portfolio_relevance": portfolio_relevance, "evidence_quality": evidence_quality,
        "urgency": urgency, "exposure": exposure, "breaker_override": "YES" if breaker else "NO",
    }
    return round(score, 4), inputs


def _exposure(weight: float) -> Exposure:
    return "HIGH" if weight >= .20 else "MODERATE" if weight >= .05 else "LOW" if weight > 0 else "NONE"


def _relevance(weight: float, direct: bool = False) -> Relevance:
    if direct:
        return "DIRECT"
    return "HIGH" if weight >= .20 else "MODERATE" if weight >= .05 else "LOW" if weight > 0 else "NONE"


def _quality(value: Any) -> Quality:
    return {"MEDIUM": "MODERATE", "UNAVAILABLE": "INSUFFICIENT_DATA"}.get(str(value or "").upper(), str(value or "INSUFFICIENT_DATA").upper())  # type: ignore[return-value]


def _freshness(value: Any) -> Freshness:
    return "CURRENT" if str(value).upper() in {"HIGH", "CURRENT"} else "STALE" if str(value).upper() in {"MEDIUM", "LOW", "STALE"} else "UNAVAILABLE"


def _weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for row in holdings:
        ticker = str(row.get("ticker") or "").upper()
        value = _number(row.get("market_value")) or _number(row.get("weight")) or 0
        if ticker and value > 0:
            raw[ticker] = raw.get(ticker, 0) + value
    total = sum(raw.values())
    return {ticker: value / total for ticker, value in raw.items()} if total else {}


def _source(label: str, provider: str, as_of: Any, url: str | None = None) -> AttentionSource:
    return AttentionSource(label=label, provider=provider, as_of=str(as_of) if as_of else None, url=url)


def _monitor_candidates(monitoring: list[dict[str, Any]], thesis_by_id: dict[str, dict[str, Any]],
                        weights: dict[str, float], now: datetime) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    for result in monitoring:
        thesis_id = str(result.get("thesis_id") or "")
        thesis = thesis_by_id.get(thesis_id, {})
        ticker = str(result.get("ticker") or thesis.get("ticker") or "").upper()
        status = str(result.get("overall_status") or "INSUFFICIENT_EVIDENCE")
        mapping: dict[str, tuple[AttentionType, Materiality, str, bool]] = {
            "THESIS_BREAKER_TRIGGERED": ("THESIS_BREAKER_TRIGGERED", "CRITICAL", "Review thesis", True),
            "MATERIAL_REVIEW_REQUIRED": ("THESIS_BREAKER_WARNING", "HIGH", "Review thesis", False),
            "WEAKENING": ("THESIS_WEAKENED", "HIGH", "Review thesis", False),
            "STRENGTHENING": ("THESIS_STRENGTHENED", "MEDIUM", "Review thesis", False),
        }
        if status not in mapping:
            continue
        item_type, materiality, action_label, breaker = mapping[status]
        assumptions = [row for row in result.get("assumption_results", []) if row.get("state") in {"WEAKENS", "CONTRADICTS", "SUPPORTS"}]
        breakers = [row for row in result.get("thesis_breaker_results", []) if row.get("state") in {"WARNING", "TRIGGERED"}]
        strongest = (breakers or sorted(assumptions, key=lambda row: row.get("importance") == "HIGH", reverse=True))[:3]
        evidence_rows = [evidence for row in strongest for evidence in row.get("evidence", [])][:6]
        primary = strongest[0] if strongest else None
        changed = (primary or {}).get("description") or f"The stored thesis monitor status changed to {status.replace('_', ' ').lower()}."
        weight = weights.get(ticker, 0)
        quality = _quality(result.get("evidence_quality"))
        freshness = _freshness(result.get("freshness"))
        thesis_rel: Relevance = "DIRECT"
        portfolio_rel = _relevance(weight)
        score, inputs = rank_attention(materiality=materiality, thesis_relevance=thesis_rel,
                                       portfolio_relevance=portfolio_rel, evidence_quality=quality,
                                       urgency="IMMEDIATE" if result.get("requires_review") else "NORMAL",
                                       exposure=_exposure(weight), breaker=breaker)
        occurred = _timestamp(result.get("evaluated_at") or result.get("created_at"), now)
        group_key = f"thesis:{thesis_id}"
        sources = [_source(str(row.get("label") or row.get("metric") or "Thesis evidence"),
                           str(row.get("source") or "Stored evidence"), row.get("current_as_of"),
                           (row.get("source_references") or [None])[0]) for row in evidence_rows]
        output.append(AttentionItem(
            id=_id(group_key, occurred), type=item_type, entity_type="SECURITY", entity_key=ticker,
            title=f"{ticker} thesis {status.replace('_', ' ').lower()}",
            summary=str((primary or {}).get("explanation") or changed), what_changed=str(changed),
            why_it_matters="This affects the saved investment thesis and should be reviewed before changing the position.",
            materiality=materiality, thesis_relevance=thesis_rel, portfolio_relevance=portfolio_rel,
            evidence_quality=quality, freshness=freshness,
            urgency="IMMEDIATE" if result.get("requires_review") else "NORMAL", occurred_at=occurred,
            sources=sources, linked_thesis_id=thesis_id,
            linked_portfolio_exposure={"level": _exposure(weight), "portfolio_weight": weight} if weight else None,
            action_label=action_label, action_target=f"/decisions?ticker={ticker}&monitor=1",
            ask_prompts=[f"Why does the {ticker} thesis need attention?", f"What changed in my {ticker} thesis?"],
            affected=[ticker], details=strongest, ranking_inputs=inputs, group_key=group_key, attention_score=score,
        ))
    return output


def _forecast_candidates(markets: list[dict[str, Any]], weights: dict[str, float], now: datetime) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    for market in markets:
        change = market.get("change") or {}
        materiality_value = str(change.get("materiality") or "UNKNOWN")
        if materiality_value not in {"MEDIUM", "HIGH"}:
            continue
        holdings = [str(value).upper() for value in market.get("affected_holdings", [])]
        linked_theses = market.get("affected_theses") or []
        if not holdings and not linked_theses:
            continue
        portfolio_weight = sum(weights.get(ticker, 0) for ticker in holdings)
        quality = _quality((market.get("quality") or {}).get("level"))
        materiality: Materiality = "HIGH" if materiality_value == "HIGH" else "MEDIUM"
        thesis_rel: Relevance = "DIRECT" if linked_theses else "NONE"
        portfolio_rel = _relevance(portfolio_weight)
        exposure = _exposure(portfolio_weight)
        score, inputs = rank_attention(materiality=materiality, thesis_relevance=thesis_rel,
                                       portfolio_relevance=portfolio_rel, evidence_quality=quality,
                                       urgency="NORMAL", exposure=exposure)
        probability = float((market.get("probability") or {}).get("probability", 0))
        previous = change.get("previous_probability")
        points = change.get("percentage_point_change")
        changed = (f"Market-implied probability moved from {float(previous) * 100:.1f}% to {probability * 100:.1f}% "
                   f"({float(points):+.1f} percentage points)." if previous is not None and points is not None
                   else f"Market-implied probability is {probability * 100:.1f}%; comparable history is unavailable.")
        first_thesis = linked_theses[0] if linked_theses else None
        group_key = f"thesis:{first_thesis['thesis_id']}" if first_thesis else f"forecast:{market.get('event_key')}"
        occurred = _timestamp((market.get("probability") or {}).get("as_of"), now)
        exposure_rows = market.get("exposures") or []
        mechanism = (exposure_rows[0] or {}).get("mechanism") if exposure_rows else None
        output.append(AttentionItem(
            id=_id(group_key, occurred), type="PREDICTION_MARKET_CHANGE", entity_type="MARKET",
            entity_key=str(market.get("event_key") or market.get("market_id")), title=str(market.get("title")),
            summary=changed, what_changed=changed,
            why_it_matters=(f"{mechanism}." if mechanism else "This outcome maps to a saved holding or thesis.") ,
            materiality=materiality, thesis_relevance=thesis_rel, portfolio_relevance=portfolio_rel,
            evidence_quality=quality, freshness="STALE" if (market.get("quality") or {}).get("stale") else "CURRENT",
            urgency="NORMAL", occurred_at=occurred,
            sources=[_source(str(market.get("title")), str(market.get("provider")), occurred, market.get("source_url"))],
            linked_thesis_id=(first_thesis or {}).get("thesis_id"),
            linked_portfolio_exposure={"level": exposure, "portfolio_weight": portfolio_weight,
                                       "holdings": holdings} if holdings else None,
            linked_scenario=str(market.get("event_key")), action_label="View market",
            action_target="/research?view=prediction-markets",
            ask_prompts=["Why does this probability change matter?", "Which holdings are most exposed?", "What if this scenario happens?"],
            affected=sorted(set(holdings + [str(row.get("ticker")) for row in linked_theses])),
            details=[{"market_probability": probability, "previous_probability": previous,
                      "percentage_point_change": points, "quality": market.get("quality"),
                      "exposures": exposure_rows}], ranking_inputs=inputs, group_key=group_key, attention_score=score,
        ))
    return output


def _upcoming_candidates(events: list[dict[str, Any]], theses: list[dict[str, Any]],
                         weights: dict[str, float], now: datetime) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    today = now.date()
    for event in events:
        event_date = _date(event.get("starts_at"))
        if event_date is None or not 0 <= (event_date - today).days <= 7:
            continue
        tickers = [str(value).upper() for value in event.get("tickers", [])]
        portfolio_weight = sum(weights.get(ticker, 0) for ticker in tickers)
        if portfolio_weight <= 0:
            continue
        event_type: AttentionType = "UPCOMING_EARNINGS" if event.get("event_type") == "earnings" else "MACRO_CHANGE"
        exposure = _exposure(portfolio_weight)
        score, inputs = rank_attention(materiality="MEDIUM", thesis_relevance="NONE",
                                       portfolio_relevance=_relevance(portfolio_weight), evidence_quality="HIGH",
                                       urgency="SOON", exposure=exposure)
        occurred = _timestamp(event.get("verified_at") or now, now)
        group_key = f"event:{event.get('event_type')}:{','.join(tickers)}:{event_date.isoformat()}"
        output.append(AttentionItem(
            id=_id(group_key, occurred), type=event_type, entity_type="EVENT", entity_key=str(event.get("id")),
            title=str(event.get("title")), summary=f"Scheduled for {event_date.isoformat()}.",
            what_changed="A verified event is within the next seven days.",
            why_it_matters=f"The affected holdings represent a {_exposure(portfolio_weight).lower()} share of saved portfolio exposure.",
            materiality="MEDIUM", portfolio_relevance=_relevance(portfolio_weight), evidence_quality="HIGH",
            freshness="CURRENT", urgency="SOON", occurred_at=occurred,
            sources=[_source(str(event.get("title")), str(event.get("provider")), event.get("verified_at"), event.get("source_url"))],
            linked_portfolio_exposure={"level": exposure, "portfolio_weight": portfolio_weight, "holdings": tickers},
            action_label="Review before event", action_target=f"/research?q={tickers[0]}" if tickers else "/research",
            ask_prompts=["What should I review before this event?"], affected=tickers,
            details=[{"starts_at": event.get("starts_at"), "event_type": event.get("event_type")}],
            ranking_inputs=inputs, group_key=group_key, attention_score=score,
        ))
    for thesis in theses:
        review_date = _date(thesis.get("review_date"))
        if review_date is None or (review_date - today).days > 14:
            continue
        overdue = review_date < today
        ticker = str(thesis.get("ticker") or "").upper()
        weight = weights.get(ticker, 0)
        materiality: Materiality = "HIGH" if overdue else "MEDIUM"
        urgency: Urgency = "IMMEDIATE" if overdue else "SOON"
        score, inputs = rank_attention(materiality=materiality, thesis_relevance="DIRECT",
                                       portfolio_relevance=_relevance(weight), evidence_quality="HIGH",
                                       urgency=urgency, exposure=_exposure(weight))
        occurred = now.isoformat()
        group_key = f"thesis:{thesis['id']}"
        output.append(AttentionItem(
            id=_id(group_key, occurred), type="UPCOMING_REVIEW", entity_type="SECURITY", entity_key=ticker,
            title=f"{ticker} thesis review {'is overdue' if overdue else 'is approaching'}",
            summary=f"Saved review date: {review_date.isoformat()}.",
            what_changed="The saved thesis review date has reached the review window.",
            why_it_matters="A scheduled review is part of the saved decision process; it does not imply that the thesis changed.",
            materiality=materiality, thesis_relevance="DIRECT", portfolio_relevance=_relevance(weight),
            evidence_quality="HIGH", freshness="CURRENT", urgency=urgency, occurred_at=occurred,
            sources=[_source("Saved thesis review date", "EagleEyes decision memory", thesis.get("updated_at"))],
            linked_thesis_id=str(thesis["id"]), linked_portfolio_exposure={"level": _exposure(weight), "portfolio_weight": weight} if weight else None,
            action_label="Review thesis", action_target=f"/decisions?ticker={ticker}&monitor=1",
            ask_prompts=[f"What should I review in my {ticker} thesis?"], affected=[ticker],
            details=[{"review_date": review_date.isoformat(), "overdue": overdue}], ranking_inputs=inputs,
            group_key=group_key, attention_score=score,
        ))
    return output


def _risk_candidates(diagnostics: dict[str, Any], now: datetime) -> list[AttentionItem]:
    risk = diagnostics.get("marginal_risk") or {}
    positions = risk.get("positions") or []
    if risk.get("status") != "ready" or not positions:
        return []
    leading = positions[0]
    contribution = _number(leading.get("risk_contribution")) or 0
    if contribution < .35:
        return []
    ticker = str(leading.get("ticker"))
    materiality: Materiality = "HIGH" if contribution >= .50 else "MEDIUM"
    exposure = _exposure(_number(leading.get("portfolio_weight")) or 0)
    score, inputs = rank_attention(materiality=materiality, thesis_relevance="NONE",
                                   portfolio_relevance="HIGH", evidence_quality="HIGH", urgency="NORMAL", exposure=exposure)
    occurred = _timestamp(diagnostics.get("as_of"), now)
    group_key = f"portfolio-risk:{ticker}"
    return [AttentionItem(
        id=_id(group_key, occurred), type="PORTFOLIO_RISK_CHANGE", entity_type="PORTFOLIO", entity_key=ticker,
        title=f"{ticker} dominates modeled portfolio risk", summary=f"{contribution:.0%} of modeled variance contribution.",
        what_changed="The latest deterministic portfolio diagnostic is above the concentration review threshold.",
        why_it_matters="Risk contribution can be materially larger than portfolio weight.", materiality=materiality,
        portfolio_relevance="HIGH", evidence_quality="HIGH", freshness="CURRENT", urgency="NORMAL", occurred_at=occurred,
        sources=[_source("Portfolio marginal risk", "EagleEyes deterministic covariance", diagnostics.get("as_of"))],
        linked_portfolio_exposure={"level": exposure, "portfolio_weight": leading.get("portfolio_weight"),
                                   "risk_contribution": contribution}, action_label="Review portfolio risk",
        action_target="/portfolio?view=analysis", ask_prompts=["Which holdings contribute most to portfolio risk?"],
        affected=[ticker], details=[leading, {"method": risk.get("method"), "sample_count": risk.get("sample_count")}],
        ranking_inputs=inputs, group_key=group_key, attention_score=score,
    )]


def _decision_review_candidates(reviews: list[dict[str, Any]], weights: dict[str, float], now: datetime) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    for row in sorted(reviews, key=lambda item: str(item.get("due_at") or ""))[:3]:
        decision = row.get("decision") or {}; ticker = str(decision.get("ticker") or "").upper()
        due = _utc_datetime(row.get("due_at"), now); overdue_days = max(0, (now - due).days)
        weight = weights.get(ticker, 0); materiality: Materiality = "MEDIUM" if overdue_days >= 30 else "LOW"
        urgency: Urgency = "SOON" if overdue_days < 30 else "IMMEDIATE"
        score, inputs = rank_attention(materiality=materiality, thesis_relevance="DIRECT",
                                       portfolio_relevance=_relevance(weight), evidence_quality="HIGH",
                                       urgency=urgency, exposure=_exposure(weight))
        group_key = f"decision-review:{decision.get('id')}"
        output.append(AttentionItem(
            id=_id(group_key, due.isoformat()), type="UPCOMING_REVIEW", entity_type="DECISION",
            entity_key=str(decision.get("id")), title=f"{ticker} decision review is due",
            summary=f"Review the {decision.get('decision_type')} decision recorded {str(decision.get('decision_date'))[:10]}.",
            what_changed="The review horizon saved with this decision has matured.",
            why_it_matters="A retrospective compares the original reasoning with subsequent evidence without treating return as process quality.",
            materiality=materiality, thesis_relevance="DIRECT", portfolio_relevance=_relevance(weight),
            evidence_quality="HIGH", freshness="CURRENT", urgency=urgency, occurred_at=due.isoformat(),
            sources=[_source("Saved decision review horizon", "EagleEyes decision journal", decision.get("created_at"))],
            linked_thesis_id=decision.get("thesis_id"), linked_decision_id=str(decision.get("id")),
            action_label="Review decision", action_target=f"/decisions?journal={decision.get('id')}",
            ask_prompts=[f"What did I originally expect when I recorded {decision.get('decision_type')} for {ticker}?"],
            affected=[ticker], details=[{"due_at": row.get("due_at"), "horizon_days": row.get("horizon_days"), "overdue_days": overdue_days}],
            ranking_inputs=inputs, group_key=group_key, attention_score=score,
        ))
    return output


def _earnings_candidates(earnings: list[dict[str, Any]], weights: dict[str, float], now: datetime) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    for report in earnings:
        if report.get("status") != "AVAILABLE":
            continue
        reported = _date(report.get("reported_at"))
        if reported is None or abs((now.date() - reported).days) > 14:
            continue
        ticker = str(report.get("ticker") or "").upper(); weight = weights.get(ticker, 0)
        assumptions = (report.get("thesis_impact") or {}).get("assumptions") or []
        weakened = [row for row in assumptions if row.get("state") in {"WEAKENS", "CONTRADICTS"}]
        supported = [row for row in assumptions if row.get("state") == "SUPPORTS"]
        material_numbers = []
        for item in (report.get("actual_vs_expectations") or {}).values():
            if item.get("surprise_percent") is not None: material_numbers.append(abs(float(item["surprise_percent"])))
        for item in report.get("changes", []):
            if item.get("change_basis_points") is not None: material_numbers.append(abs(float(item["change_basis_points"])) / 10000)
        materiality: Materiality = "HIGH" if weakened else "MEDIUM" if max(material_numbers or [0]) >= .05 else "LOW"
        thesis_id = (report.get("thesis_impact") or {}).get("thesis_id")
        group_key = f"thesis:{thesis_id}" if thesis_id else f"earnings:{ticker}:{(report.get('period') or {}).get('period_end')}"
        score, inputs = rank_attention(materiality=materiality, thesis_relevance="DIRECT" if thesis_id else "LOW",
                                       portfolio_relevance=_relevance(weight), evidence_quality="HIGH", urgency="SOON",
                                       exposure=_exposure(weight))
        source = report.get("source") or {}
        output.append(AttentionItem(
            id=_id(group_key, str(report.get("reported_at"))), type="MATERIAL_EARNINGS_CHANGE", entity_type="SECURITY", entity_key=ticker,
            title=f"{ticker} earnings changed {len(weakened) + len(supported)} thesis assumption{'s' if len(weakened) + len(supported) != 1 else ''}",
            summary=f"{len(supported)} supported · {len(weakened)} weakened; missing consensus or guidance remains explicit.",
            what_changed=f"A verified {(report.get('period') or {}).get('fiscal_period') or 'financial'} period was added with {len(report.get('changes', []))} structured comparisons.",
            why_it_matters="Earnings evidence is evaluated through the existing thesis monitor, not a separate earnings opinion.",
            materiality=materiality, thesis_relevance="DIRECT" if thesis_id else "LOW", portfolio_relevance=_relevance(weight),
            evidence_quality="HIGH", freshness="CURRENT", urgency="SOON", occurred_at=str(report.get("reported_at")),
            sources=[_source("Reported financial period", str(source.get("provider") or "stored fundamentals"), report.get("reported_at"), source.get("url"))],
            linked_thesis_id=thesis_id, linked_portfolio_exposure={"level": _exposure(weight), "portfolio_weight": weight} if weight else None,
            action_label="Review earnings change", action_target=f"/research?ticker={ticker}&earnings=1",
            ask_prompts=[f"What changed in {ticker} earnings?", f"Did {ticker} earnings weaken my thesis?"], affected=[ticker],
            details=[{"actual_vs_expectations": report.get("actual_vs_expectations"), "guidance_changes": report.get("guidance_changes"),
                      "estimate_revisions": report.get("estimate_revisions"), "thesis_impact": report.get("thesis_impact"), "coverage": report.get("coverage")}],
            ranking_inputs=inputs, group_key=group_key, attention_score=score))
    return output


def _watchlist_candidates(research: list[dict[str, Any]], watchlist: list[str], weights: dict[str, float],
                          now: datetime) -> list[AttentionItem]:
    output: list[AttentionItem] = []
    watched = {value.upper() for value in watchlist} - set(weights)
    for row in research:
        ticker = str(row.get("ticker") or "").upper()
        score_value, confidence = _number(row.get("final_score")), _number(row.get("confidence"))
        if ticker not in watched or score_value is None or confidence is None or score_value < 75 or confidence < 70:
            continue
        score, inputs = rank_attention(materiality="LOW", thesis_relevance="NONE", portfolio_relevance="LOW",
                                       evidence_quality="HIGH", urgency="LOW", exposure="NONE")
        occurred = _timestamp(row.get("fundamentals_as_of") or row.get("price_as_of"), now)
        group_key = f"watchlist:{ticker}"
        output.append(AttentionItem(
            id=_id(group_key, occurred), type="WATCHLIST_THRESHOLD", entity_type="SECURITY", entity_key=ticker,
            title=f"{ticker} is worth a research review", summary="The saved watchlist name meets the deterministic evidence-review threshold.",
            what_changed="Current stored research has at least 75/100 comparative evidence and 70/100 coverage confidence.",
            why_it_matters="This is a prompt to review the evidence, not a buy signal.", materiality="LOW",
            portfolio_relevance="LOW", evidence_quality="HIGH", freshness="CURRENT", urgency="LOW", occurred_at=occurred,
            sources=[_source("Stored security research", str(row.get("data_source") or "EagleEyes research"), occurred, row.get("source"))],
            action_label="Review research", action_target=f"/research?q={ticker}",
            ask_prompts=[f"What changed in the research for {ticker}?"], affected=[ticker], details=[],
            ranking_inputs=inputs, group_key=group_key, attention_score=score,
        ))
    return output


def _data_quality_candidates(warnings: list[str], now: datetime) -> list[AttentionItem]:
    if not warnings:
        return []
    score, inputs = rank_attention(materiality="LOW", thesis_relevance="NONE", portfolio_relevance="LOW",
                                   evidence_quality="INSUFFICIENT_DATA", urgency="LOW", exposure="NONE")
    group_key = "data-quality:today"
    return [AttentionItem(
        id=_id(group_key, now.isoformat()), type="DATA_QUALITY_WARNING", entity_type="SYSTEM", entity_key="today",
        title="Some attention sources are unavailable", summary=warnings[0], what_changed="One or more structured inputs could not be loaded.",
        why_it_matters="Missing evidence is not interpreted as no risk or a neutral probability.", materiality="LOW",
        evidence_quality="INSUFFICIENT_DATA", freshness="UNAVAILABLE", urgency="LOW", occurred_at=now.isoformat(),
        sources=[], action_label="Review data health", action_target="/advanced?view=lineage",
        ask_prompts=["Which evidence is missing today?"], affected=[], details=[{"warnings": warnings}],
        ranking_inputs=inputs, group_key=group_key, attention_score=score,
    )]


def group_attention(items: list[AttentionItem]) -> list[AttentionItem]:
    grouped: dict[str, list[AttentionItem]] = {}
    for item in items:
        grouped.setdefault(item.group_key, []).append(item)
    output: list[AttentionItem] = []
    for rows in grouped.values():
        rows.sort(key=lambda item: item.attention_score, reverse=True)
        lead = rows[0]
        if len(rows) > 1:
            lead.summary = f"{lead.summary} {len(rows) - 1} related development{'s' if len(rows) > 2 else ''} grouped below."
            lead.details = [*lead.details, *[{"related_type": item.type, "title": item.title,
                                             "what_changed": item.what_changed, "sources": [source.model_dump() for source in item.sources]}
                                            for item in rows[1:]]]
            lead.sources = list({(source.label, source.provider, source.as_of, source.url): source
                                 for item in rows for source in item.sources}.values())
            lead.affected = sorted({value for item in rows for value in item.affected})
            lead.attention_score = max(item.attention_score for item in rows) + min(10, len(rows) - 1)
        output.append(lead)
    return sorted(output, key=lambda item: (-item.attention_score, item.id))


def apply_states(items: list[AttentionItem], states: dict[str, dict[str, Any]], now: datetime) -> list[AttentionItem]:
    output = []
    for item in items:
        stored = states.get(item.id)
        if stored:
            state = str(stored.get("state") or "UNREAD")
            until = stored.get("snoozed_until")
            if state == "SNOOZED" and until:
                parsed = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
                if parsed <= now:
                    state, until = "UNREAD", None
            item.state = state  # type: ignore[assignment]
            item.state_until = str(until) if until else None
        output.append(item)
    return output


def portfolio_summary(movements: list[dict[str, Any]], holdings: list[dict[str, Any]]) -> dict[str, Any]:
    weights = _weights(holdings)
    by_ticker = {str(row.get("ticker")): row for row in movements}
    contributions = []
    for ticker, weight in weights.items():
        change = _number((by_ticker.get(ticker) or {}).get("change_1d"))
        if change is not None:
            contributions.append({"ticker": ticker, "weight": weight, "change_1d": change,
                                  "contribution": weight * change})
    daily = sum(row["contribution"] for row in contributions) if contributions else None
    value = sum(_number(row.get("market_value")) or 0 for row in holdings) or None
    benchmark = _number((by_ticker.get("SPY") or {}).get("change_1d"))
    return {
        "change_1d": daily, "dollar_change": None if daily is None or value is None else daily * value,
        "portfolio_value": value, "benchmark_ticker": "SPY", "benchmark_change_1d": benchmark,
        "contributors": sorted(contributions, key=lambda row: abs(row["contribution"]), reverse=True)[:3],
        "methodology": "Current normalized saved weights multiplied by latest available one-session adjusted-price returns.",
        "available": daily is not None,
    }


def price_context(movements: list[dict[str, Any]], monitoring: list[dict[str, Any]],
                  holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    monitored = {str(row.get("ticker")) for row in monitoring
                 if row.get("overall_status") not in {"STABLE", "INSUFFICIENT_EVIDENCE"}}
    held = set(_weights(holdings))
    return [{"ticker": row["ticker"], "change_1d": row.get("change_1d"),
             "evidence_status": "MATERIAL_THESIS_CHANGE" if row["ticker"] in monitored else "NO_MATERIAL_EVIDENCE_CHANGE",
             "message": "Material thesis evidence also changed." if row["ticker"] in monitored else "No material change was detected in the evidence supporting the saved thesis."}
            for row in movements if row.get("ticker") in held and row.get("change_1d") is not None
            and abs(float(row["change_1d"])) >= .04]


def daily_brief(summary: dict[str, Any], items: list[AttentionItem]) -> dict[str, Any]:
    visible = [item for item in items if item.state not in {"DISMISSED", "SNOOZED", "RESOLVED"}]
    material = [item for item in visible if item.materiality in {"CRITICAL", "HIGH", "MEDIUM"}]
    performance = "Portfolio performance is unavailable from current stored prices."
    if summary.get("change_1d") is not None:
        performance = f"Your portfolio {'gained' if summary['change_1d'] >= 0 else 'declined'} {abs(summary['change_1d']) * 100:.1f}% in the latest session."
    if not material:
        text = f"{performance} No material changes were detected across your active theses and relevant forward-looking evidence today."
    else:
        developments = "; ".join(item.title for item in material[:3])
        text = f"{performance} {len(material)} development{'s' if len(material) != 1 else ''} deserve attention: {developments}."
    return {"text": text, "claim_item_ids": [item.id for item in material[:3]],
            "methodology": "Template synthesis from ranked structured attention items; no LLM-generated financial claim."}


def compose_attention(*, holdings: list[dict[str, Any]], thesis_workspace: dict[str, Any],
                      monitoring_results: list[dict[str, Any]], forecasting_payload: dict[str, Any],
                      events: list[dict[str, Any]], diagnostics: dict[str, Any], research: list[dict[str, Any]],
                      watchlist: list[str], movements: list[dict[str, Any]], states: dict[str, dict[str, Any]],
                      warnings: list[str] | None = None, earnings: list[dict[str, Any]] | None = None,
                      decision_reviews: list[dict[str, Any]] | None = None,
                      now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    weights = _weights(holdings)
    active = thesis_workspace.get("active_theses", [])
    by_id = {str(row["id"]): row for row in active}
    candidates = [
        *_monitor_candidates(monitoring_results, by_id, weights, current),
        *_forecast_candidates(forecasting_payload.get("markets", []), weights, current),
        *_upcoming_candidates(events, active, weights, current),
        *_earnings_candidates(earnings or [], weights, current),
        *_decision_review_candidates(decision_reviews or [], weights, current),
        *_risk_candidates(diagnostics, current),
        *_watchlist_candidates(research, watchlist, weights, current),
        *_data_quality_candidates(warnings or forecasting_payload.get("warnings", []), current),
    ]
    ranked = apply_states(group_attention(candidates), states, current)
    visible = [item for item in ranked if item.state not in {"DISMISSED", "SNOOZED", "RESOLVED"}]
    portfolio = portfolio_summary(movements, holdings)
    return {
        "items": [item.model_dump(mode="json") for item in visible],
        "all_item_count": len(ranked), "material_item_count": sum(item.materiality in {"CRITICAL", "HIGH", "MEDIUM"} for item in visible),
        "unread_count": sum(item.state == "UNREAD" for item in visible),
        "no_material_change": not any(item.materiality in {"CRITICAL", "HIGH", "MEDIUM"} for item in visible),
        "portfolio_summary": portfolio, "price_context": price_context(movements, monitoring_results, holdings),
        "daily_brief": daily_brief(portfolio, ranked),
        "ranking_methodology": {"version": "attention-ranking-v1", "description": "Deterministic product of materiality, strongest personal relevance, evidence quality, urgency, and exposure; thesis breakers receive an explicit override.",
                                "factors": ["materiality", "thesis relevance", "portfolio relevance", "evidence quality", "freshness", "urgency", "exposure"]},
    }
