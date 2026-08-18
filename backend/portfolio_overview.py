from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any


VERSION = "portfolio-health-v1"
COMPONENT_WEIGHTS = {
    "risk": 0.20,
    "diversification": 0.20,
    "fundamentals": 0.20,
    "valuation": 0.15,
    "momentum": 0.10,
    "data_quality": 0.15,
}
MISSING_SCORE = 40.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _clip(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    values = [_number(row.get("market_value")) for row in holdings]
    raw = values if sum(values) > 0 else [_number(row.get("weight")) for row in holdings]
    total = sum(raw)
    if total <= 0:
        return {}
    return {
        str(row.get("ticker") or "").upper(): value / total
        for row, value in zip(holdings, raw) if value > 0
    }


def _covered_weighted(rows: list[tuple[float, float | None]]) -> tuple[float, float]:
    covered = sum(weight for weight, value in rows if value is not None)
    raw = sum(weight * _number(value) for weight, value in rows if value is not None)
    return _clip(raw + max(0.0, 1.0 - covered) * MISSING_SCORE), min(1.0, covered)


def _band(score: float) -> str:
    if score >= 85:
        return "Strong"
    if score >= 70:
        return "Healthy"
    if score >= 55:
        return "Needs attention"
    if score >= 40:
        return "Weak"
    return "Critical"


def _confidence(coverage: float) -> str:
    return "High" if coverage >= 0.90 else "Medium" if coverage >= 0.70 else "Low"


def input_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _action_key(source: str, key: str) -> str:
    return hashlib.md5(f"{source}:{key}".encode(), usedforsecurity=False).hexdigest()


def _priority(materiality: str, exposure: float, thesis: bool, urgency: str, confidence: str) -> float:
    materiality_points = {"CRITICAL": 55, "HIGH": 42, "MEDIUM": 28, "LOW": 12}.get(materiality.upper(), 12)
    urgency_points = {"IMMEDIATE": 16, "SOON": 10, "MONITOR": 4}.get(urgency.upper(), 4)
    confidence_points = {"HIGH": 10, "MEDIUM": 6, "LOW": 2}.get(confidence.upper(), 2)
    return round(materiality_points + min(18, max(0, exposure) * 30) + (8 if thesis else 0) + urgency_points + confidence_points, 1)


def _normalized_action(*, source: str, source_key: str, action: str, title: str, reason: str,
                       holdings: list[str], materiality: str = "MEDIUM", urgency: str = "SOON",
                       confidence: str = "MEDIUM", exposure: float = 0.0, thesis: bool = False,
                       evidence_date: str | None = None, next_step: str = "Review the supporting evidence.",
                       follow_up_date: str | None = None) -> dict[str, Any]:
    return {
        "source_key": _action_key(source, source_key), "source": source, "action": action,
        "title": title, "reason": reason, "affected_holdings": sorted(set(holdings)),
        "materiality": materiality, "urgency": urgency, "confidence": confidence,
        "portfolio_exposure": round(exposure, 6), "evidence_date": evidence_date,
        "suggested_next_step": next_step,
        "follow_up_date": follow_up_date or (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat(),
        "priority": _priority(materiality, exposure, thesis, urgency, confidence),
    }


def _build_actions(*, score: float, coverage: float, weights: dict[str, float], holdings: list[dict[str, Any]],
                   monitors: list[dict[str, Any]], attention_items: list[dict[str, Any]],
                   guidance: dict[str, Any] | None, holding_rows: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    largest = max(((ticker, weight) for ticker, weight in weights.items() if ticker != "CASH"), key=lambda item: item[1], default=("", 0.0))
    if largest[1] > 0.20:
        actions.append(_normalized_action(
            source="portfolio_health", source_key=f"concentration:{largest[0]}", action="REDUCE",
            title=f"Review {largest[0]} concentration", holdings=[largest[0]], exposure=largest[1], materiality="HIGH",
            urgency="SOON", confidence="HIGH", evidence_date=as_of,
            reason=f"{largest[0]} represents {largest[1]:.1%} of the saved portfolio, above the default 20% review threshold.",
            next_step="Review taxes, account location, and a staged or contribution-only reduction before changing the position.",
        ))
    for monitor in monitors:
        ticker = str(monitor.get("ticker") or "").upper()
        status = str(monitor.get("overall_status") or "")
        if monitor.get("requires_review"):
            critical = "BREAKER" in status
            actions.append(_normalized_action(
                source="thesis_monitor", source_key=f"{monitor.get('thesis_id')}:{status}", action="REVIEW",
                title=f"{ticker} thesis requires review", holdings=[ticker], exposure=weights.get(ticker, 0), thesis=True,
                materiality="CRITICAL" if critical else "HIGH", urgency="IMMEDIATE" if critical else "SOON",
                confidence=str(monitor.get("evidence_quality") or "MEDIUM"), evidence_date=monitor.get("evaluated_at") or as_of,
                reason=status.replace("_", " ").title(), next_step="Open the saved thesis and review weakening assumptions or triggered breakers.",
            ))
    if score < 55:
        actions.append(_normalized_action(
            source="portfolio_health", source_key="overall_health", action="REVIEW", title="Portfolio health needs attention",
            reason=f"The deterministic portfolio health score is {score:.0f}/100.", holdings=list(weights), exposure=1,
            materiality="HIGH" if score < 40 else "MEDIUM", urgency="SOON", confidence=_confidence(coverage), evidence_date=as_of,
            next_step="Start with the lowest-scoring component and highest-priority holding; do not change every position at once.",
        ))
    if coverage < 0.70:
        actions.append(_normalized_action(
            source="portfolio_health", source_key="coverage", action="INVESTIGATE", title="Portfolio evidence coverage is incomplete",
            reason=f"Only {coverage:.0%} of weighted portfolio evidence is covered.", holdings=list(weights), exposure=1,
            materiality="MEDIUM", urgency="SOON", confidence="HIGH", evidence_date=as_of,
            next_step="Refresh or add evidence for the largest uncovered holdings before relying on the health score.",
        ))
    for row in holding_rows:
        if row["health_score"] < 45 and row["weight"] >= 0.02:
            actions.append(_normalized_action(
                source="holding_health", source_key=row["ticker"], action="REVIEW", title=f"Investigate {row['ticker']} weakness",
                reason=f"Holding health is {row['health_score']:.0f}/100 with {row['data_confidence'].lower()} evidence confidence.",
                holdings=[row["ticker"]], exposure=row["weight"], materiality="MEDIUM", urgency="SOON",
                confidence=row["data_confidence"], evidence_date=row.get("evidence_date") or as_of,
                next_step="Review fundamentals, valuation, thesis state, and risk contribution before deciding to hold or reduce.",
            ))
    for item in attention_items:
        action_label = str(item.get("action_label") or "REVIEW").upper()
        action = "INVESTIGATE" if "INVEST" in action_label or "WHY" in action_label else "REVIEW"
        affected = [str(value).upper() for value in item.get("affected", [])]
        exposure = _number((item.get("linked_portfolio_exposure") or {}).get("portfolio_weight"))
        actions.append(_normalized_action(
            source="today_attention", source_key=str(item.get("group_key") or item.get("id")), action=action,
            title=str(item.get("title") or "Review material change"), reason=str(item.get("why_it_matters") or item.get("summary") or "Material evidence changed."),
            holdings=affected, exposure=exposure, materiality=str(item.get("materiality") or "MEDIUM"),
            urgency=str(item.get("urgency") or "SOON"), confidence=str(item.get("evidence_quality") or "MEDIUM"),
            evidence_date=item.get("occurred_at") or as_of, next_step=str(item.get("action_label") or "Review the evidence and portfolio relevance."),
        ))
    for recommendation in (guidance or {}).get("recommendations", []):
        proposed = str(recommendation.get("proposed_action") or "Review portfolio guidance")
        upper = proposed.upper()
        action = "REDUCE" if any(word in upper for word in ("REDUCE", "MOVE", "SELL")) else "ADD" if any(word in upper for word in ("ADD", "CONTRIBUT")) else "HOLD" if "NO IMMEDIATE SALE" in upper else "REVIEW"
        affected = [ticker for ticker in weights if ticker in upper]
        actions.append(_normalized_action(
            source="plan_guidance", source_key=str(recommendation.get("key") or proposed), action=action,
            title=proposed, reason=str(recommendation.get("why_it_matters") or "Saved policy guidance changed."),
            holdings=affected, exposure=sum(weights.get(ticker, 0) for ticker in affected), materiality="MEDIUM",
            urgency="MONITOR", confidence=str(recommendation.get("confidence") or "MEDIUM"), evidence_date=as_of,
            next_step=proposed, follow_up_date=recommendation.get("review_date"),
        ))
    deduplicated = {item["source_key"]: item for item in actions}
    return sorted(deduplicated.values(), key=lambda item: (-item["priority"], item["title"]))


def build_portfolio_overview(*, portfolio: dict[str, Any], diagnostics: dict[str, Any], research: list[dict[str, Any]],
                             theses: list[dict[str, Any]] | None = None, monitors: list[dict[str, Any]] | None = None,
                             decisions: list[dict[str, Any]] | None = None, attention_items: list[dict[str, Any]] | None = None,
                             guidance: dict[str, Any] | None = None, previous_nightly: dict[str, Any] | None = None,
                             trigger: str = "MANUAL") -> dict[str, Any]:
    holdings = portfolio.get("holdings", [])
    weights = _weights(holdings)
    as_of = datetime.now(timezone.utc).isoformat()
    research_by_ticker = {str(row.get("ticker") or "").upper(): row for row in research}
    thesis_by_ticker = {str(row.get("ticker") or "").upper(): row for row in (theses or [])}
    monitor_by_ticker = {str(row.get("ticker") or "").upper(): row for row in (monitors or [])}
    latest_decision: dict[str, dict[str, Any]] = {}
    for row in decisions or []:
        ticker = str(row.get("ticker") or "").upper()
        if ticker and ticker not in latest_decision:
            latest_decision[ticker] = row
    intelligence = diagnostics.get("intelligence") or {}
    risk_positions = {str(row.get("ticker") or "").upper(): row for row in (diagnostics.get("marginal_risk") or {}).get("positions", [])}
    previous_holdings = {row.get("ticker"): row for row in (previous_nightly or {}).get("holdings", [])}

    largest_weight = max((weight for ticker, weight in weights.items() if ticker != "CASH"), default=0.0)
    max_risk = max((_number(row.get("risk_contribution")) for ticker, row in risk_positions.items() if ticker != "CASH"), default=0.0)
    risk_score = _clip(100 - max(0, largest_weight - 0.10) * 125 - max(0, max_risk - 0.25) * 80)
    effective = _number((intelligence.get("concentration") or {}).get("effective_holdings"), 1 / sum(value * value for value in weights.values()) if weights else 0)
    largest_sector = max((_number(row.get("weight")) for row in diagnostics.get("sector_exposure", [])), default=1.0 if weights else 0.0)
    largest_dependency = max((_number(row.get("mapped_portfolio_weight")) for row in intelligence.get("economic_dependencies", [])), default=0.0)
    diversification_score = _clip(min(100, effective * 10) * 0.45 + (100 - max(0, largest_sector - 0.25) * 120) * 0.35 + (100 - largest_dependency * 70) * 0.20)

    fundamentals, fundamental_coverage = _covered_weighted([(weight, research_by_ticker.get(ticker, {}).get("fundamental_score")) for ticker, weight in weights.items()])
    valuation, valuation_coverage = _covered_weighted([(weight, research_by_ticker.get(ticker, {}).get("valuation_score")) for ticker, weight in weights.items()])
    momentum, momentum_coverage = _covered_weighted([(weight, research_by_ticker.get(ticker, {}).get("technical_score")) for ticker, weight in weights.items()])
    quality_rows = [(weight, research_by_ticker.get(ticker, {}).get("confidence")) for ticker, weight in weights.items()]
    data_quality, quality_coverage = _covered_weighted(quality_rows)
    coverage = round((fundamental_coverage + valuation_coverage + momentum_coverage + quality_coverage) / 4, 4)
    components = {
        "risk": {"score": risk_score, "weight": COMPONENT_WEIGHTS["risk"], "coverage": 1.0 if weights else 0.0},
        "diversification": {"score": diversification_score, "weight": COMPONENT_WEIGHTS["diversification"], "coverage": 1.0 if weights else 0.0},
        "fundamentals": {"score": fundamentals, "weight": COMPONENT_WEIGHTS["fundamentals"], "coverage": fundamental_coverage},
        "valuation": {"score": valuation, "weight": COMPONENT_WEIGHTS["valuation"], "coverage": valuation_coverage},
        "momentum": {"score": momentum, "weight": COMPONENT_WEIGHTS["momentum"], "coverage": momentum_coverage},
        "data_quality": {"score": data_quality, "weight": COMPONENT_WEIGHTS["data_quality"], "coverage": quality_coverage},
    }
    score = _clip(sum(item["score"] * item["weight"] for item in components.values())) if weights else 0.0
    holding_rows = []
    for holding in holdings:
        ticker = str(holding.get("ticker") or "").upper()
        weight = weights.get(ticker, 0.0)
        research_row = research_by_ticker.get(ticker, {})
        confidence = _number(research_row.get("confidence")) if research_row else None
        risk_contribution = risk_positions.get(ticker, {}).get("risk_contribution")
        holding_health = _clip(
            _number(research_row.get("fundamental_score"), MISSING_SCORE) * .30
            + _number(research_row.get("valuation_score"), MISSING_SCORE) * .20
            + _number(research_row.get("technical_score"), MISSING_SCORE) * .15
            + _clip(100 - _number(risk_contribution, weight) * 100) * .20
            + _number(confidence, MISSING_SCORE) * .15
        )
        prior = previous_holdings.get(ticker, {})
        monitor = monitor_by_ticker.get(ticker, {})
        decision = latest_decision.get(ticker, {})
        stats = research_row.get("market_statistics") or {}
        holding_rows.append({
            "ticker": ticker, "company": research_row.get("company") or ticker, "weight": round(weight, 6),
            "market_value": holding.get("market_value"), "health_score": holding_health,
            "health_contribution": round(weight * holding_health, 2),
            "fundamental_score": research_row.get("fundamental_score"), "valuation_score": research_row.get("valuation_score"),
            "momentum_score": research_row.get("technical_score"), "risk_contribution": risk_contribution,
            "performance": {"1d": stats.get("return_1d"), "1m": stats.get("return_1m"), "1y": stats.get("return_1y")},
            "thesis_status": (thesis_by_ticker.get(ticker) or {}).get("status") or "NO_THESIS",
            "thesis_monitor_status": monitor.get("overall_status") or "NOT_MONITORED",
            "conviction": decision.get("user_confidence"), "data_confidence": _confidence((_number(confidence) / 100) if confidence is not None else 0),
            "data_quality": research_row.get("data_quality") or "low", "evidence_date": research_row.get("fundamentals_as_of") or research_row.get("price_as_of"),
            "change": round(holding_health - _number(prior.get("health_score"), holding_health), 1), "active_action_count": 0,
        })
    holding_rows.sort(key=lambda row: (-row["weight"], row["ticker"]))
    actions = _build_actions(score=score, coverage=coverage, weights=weights, holdings=holdings, monitors=monitors or [],
                             attention_items=attention_items or [], guidance=guidance, holding_rows=holding_rows, as_of=as_of)
    action_counts: dict[str, int] = {}
    for action in actions:
        for ticker in action["affected_holdings"]:
            action_counts[ticker] = action_counts.get(ticker, 0) + 1
    for row in holding_rows:
        row["active_action_count"] = action_counts.get(row["ticker"], 0)
    holding_rows.sort(key=lambda row: (-row["active_action_count"], row["health_score"], -row["weight"], row["ticker"]))

    previous_score = (previous_nightly or {}).get("health", {}).get("score")
    changes = []
    if previous_score is not None and abs(score - _number(previous_score)) >= 0.1:
        changes.append({"type": "HEALTH_SCORE", "title": f"Portfolio health moved from {_number(previous_score):.0f} to {score:.0f}", "delta": round(score - _number(previous_score), 1), "occurred_at": as_of})
    previous_components = (previous_nightly or {}).get("health", {}).get("components", {})
    for key, item in components.items():
        prior_score = (previous_components.get(key) or {}).get("score")
        if prior_score is not None and abs(item["score"] - _number(prior_score)) >= 3:
            changes.append({"type": "COMPONENT", "component": key, "title": f"{key.replace('_', ' ').title()} {'improved' if item['score'] > _number(prior_score) else 'weakened'}", "delta": round(item["score"] - _number(prior_score), 1), "occurred_at": as_of})
    for row in holding_rows:
        if abs(row["change"]) >= 3:
            changes.append({"type": "HOLDING", "ticker": row["ticker"], "title": f"{row['ticker']} health {'improved' if row['change'] > 0 else 'deteriorated'}", "delta": row["change"], "occurred_at": as_of})
    for monitor in monitors or []:
        if monitor.get("requires_review"):
            changes.append({"type": "THESIS", "ticker": monitor.get("ticker"), "title": f"{monitor.get('ticker')} thesis requires review", "status": monitor.get("overall_status"), "occurred_at": monitor.get("evaluated_at") or as_of})

    ranked_components = sorted(components.items(), key=lambda item: item[1]["score"])
    warnings = []
    if coverage < .90:
        warnings.append(f"Weighted research coverage is {coverage:.0%}; missing evidence receives a conservative score of {MISSING_SCORE:.0f}.")
    return {
        "version": VERSION, "portfolio": {"id": str(portfolio.get("id")), "name": portfolio.get("name")},
        "as_of": as_of, "trigger": trigger, "health": {"score": score, "band": _band(score), "confidence": _confidence(coverage),
        "coverage": coverage, "delta": None if previous_score is None else round(score - _number(previous_score), 1),
        "components": components, "largest_positive": ranked_components[-1][0] if ranked_components else None,
        "largest_negative": ranked_components[0][0] if ranked_components else None},
        "holdings": holding_rows, "actions": actions, "changes": changes, "warnings": warnings,
        "methodology": "Deterministic portfolio-health-v1; no language model or live provider is required.",
    }
