from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def _weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(row.get("market_value") or 0) for row in holdings]
    if sum(values) > 0:
        return {row["ticker"]: value / sum(values) for row, value in zip(holdings, values)}
    raw = [float(row.get("weight") or 0) for row in holdings]
    total = sum(raw)
    return {row["ticker"]: value / total for row, value in zip(holdings, raw)} if total else {}


def build_guidance(
    holdings: list[dict[str, Any]], goals: list[dict[str, Any]], policy: dict[str, Any],
    research: list[dict[str, Any]], data_status: dict[str, Any], projections: list[dict[str, Any]],
    monitoring: dict[str, Any] | None = None, profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or {}
    suitability = profile.get("suitability_profile") or {}
    weights = _weights(holdings)
    research_by_ticker = {row.get("ticker"): row for row in research}
    max_weight = float(policy.get("max_single_stock_weight", .20))
    concentration = sorted(((ticker, weight) for ticker, weight in weights.items() if ticker != "CASH"), key=lambda item: item[1], reverse=True)
    alerts: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    if concentration and concentration[0][1] > max_weight:
        ticker, weight = concentration[0]
        cost_basis = next((float(row.get("cost_basis") or 0) for row in holdings if row["ticker"] == ticker), 0)
        market_value = next((float(row.get("market_value") or 0) for row in holdings if row["ticker"] == ticker), 0)
        estimated_gain = max(0, market_value - cost_basis) if market_value and cost_basis else None
        alerts.append({
            "key": "single_position", "severity": "high", "title": f"{ticker} is outside the approved single-stock range",
            "detail": f"Current weight {weight:.1%}; policy maximum {max_weight:.1%}.", "affected": [ticker],
            "trigger": "Single-position concentration became excessive.",
        })
        recommendations.append({
            "key": "reduce_concentration", "proposed_action": f"Move {ticker} gradually toward {max_weight:.0%} or below.",
            "why_it_matters": "One company currently has more influence on portfolio outcomes than the approved policy allows.",
            "expected_benefit": "Lower company-specific concentration and less dependence on one earnings path.",
            "costs_taxes_risks": "Selling can realize taxable gains and can reduce upside if the holding outperforms." if estimated_gain is not None else "Tax impact is unavailable because market value or cost basis is missing.",
            "alternatives": ["Direct new contributions elsewhere", "Reduce the position in stages", "Raise the limit only after revising and re-approving the policy"],
            "doing_nothing": f"{ticker} remains above the approved {max_weight:.0%} limit and continues to dominate company-specific risk.",
            "confidence": "high", "missing_information": [] if estimated_gain is not None else ["Market value and aggregate cost basis"],
            "review_date": (date.today() + timedelta(days=90)).isoformat(),
            "reversal_evidence": "A formally approved policy change, material household exposure changes, or evidence that the saved position data is incorrect.",
        })

    projection_by_goal = {row.get("goal_id"): row for row in projections}
    for goal in sorted(goals, key=lambda row: row.get("priority", 3)):
        projection = projection_by_goal.get(goal.get("id"))
        if projection and float(projection.get("goal_probability") or 0) < .45:
            alerts.append({
                "key": f"goal_{goal.get('id')}", "severity": "medium", "title": f"{goal['name']} needs attention",
                "detail": f"Modeled attainment frequency is {float(projection['goal_probability']):.0%}.", "affected": [goal["name"]],
                "trigger": "Goal probability materially deteriorated.",
            })

    stale = [row for row in data_status.get("providers", []) if row.get("status") != "success"]
    if stale:
        alerts.append({
            "key": "stale_data", "severity": "medium", "title": "Some recommendation evidence is stale",
            "detail": "Stale inputs are down-weighted and should be refreshed before a major decision.",
            "affected": [row.get("provider", "provider") for row in stale[:4]], "trigger": "Required recommendation data is stale.",
        })

    cash_weight = weights.get("CASH", 0)
    cash_target = float(policy.get("target_allocation", {}).get("cash", .10))
    fixed_income_target = float(policy.get("target_allocation", {}).get("fixed_income", .20))
    fixed_income_tickers = {"BND", "AGG", "SCHZ", "VGIT", "IEF", "TLT"}
    fixed_income_weight = sum(weight for ticker, weight in weights.items() if ticker in fixed_income_tickers)
    if cash_weight + .005 < cash_target:
        destination, rationale = "Cash reserve", f"Cash is {cash_weight:.1%} versus the approved {cash_target:.1%} target."
        instrument = "CASH"
    elif fixed_income_weight + .02 < fixed_income_target:
        destination, rationale = "Broad fixed income", f"Recognized bond exposure is {fixed_income_weight:.1%} versus the approved {fixed_income_target:.1%} target."
        instrument = "BND"
    else:
        candidates = [row for row in research if row.get("ticker") not in weights and row.get("ticker") in {"VTI", "SPY", "VXUS", "SCHB"}]
        instrument = candidates[0]["ticker"] if candidates else "VTI"
        destination, rationale = "Diversified equity exposure", "Cash and recognized bond allocations do not show the largest policy gap; broad exposure avoids adding to the largest single-stock position."
    account_types = sorted({str(row.get("account_type") or "taxable") for row in holdings})
    next_dollar = {
        "amount": 1000, "destination": destination, "illustrative_symbol": instrument,
        "allocation": [{"destination": instrument, "amount": 1000, "share": 1.0}],
        "why": rationale, "account_context": f"Current saved account types: {', '.join(account_types) or 'unknown'}.",
        "tax_context": "Prefer contribution-only rebalancing when it can close the gap without realizing gains.",
        "employer_match": "Employer-match information is not stored; capture any available match before using this result.",
        "goal_context": f"Based on {len(goals)} saved goal(s) and the approved allocation policy.",
        "confidence": "medium" if goals and policy.get("status") == "approved" else "low",
        "limitations": ["Illustrative research guidance only", "Does not verify fund availability, fees, or employer-plan menus"],
        "recommended_account": profile.get("account_type", account_types[0] if account_types else "unknown"),
        "constraints_considered": [
            f"Policy cash target {cash_target:.0%}", f"Policy fixed-income target {fixed_income_target:.0%}",
            f"Maximum single-stock weight {max_weight:.0%}",
            f"Guidance level: {str(suitability.get('guidance_level', 'research_only')).replace('_', ' ')}",
        ],
        "tax_assumptions": [
            f"Saved marginal tax rate is {float(profile.get('tax_rate') or 0):.0%}.",
            "Contribution-only implementation is assumed to avoid realizing existing taxable gains.",
        ],
        "alternatives": [
            "Hold the contribution in cash until the policy or liquidity need is clarified.",
            "Split the contribution across underweight policy sleeves.",
            "Use the contribution toward high-interest debt or emergency reserves when those needs dominate investment risk.",
        ],
        "missing_information": [
            label for condition, label in [
                (not suitability, "Suitability profile"),
                (float(suitability.get("emergency_reserve_months") or 0) <= 0, "Emergency-reserve coverage"),
                (not suitability.get("income_stability"), "Income stability"),
                (not goals, "A saved goal and account assignment"),
                (not account_types, "Account type"),
            ] if condition
        ],
    }
    if not recommendations:
        recommendations.append({
            "key": "no_urgent_change", "proposed_action": "No immediate sale is supported; use contributions to close the largest policy gap.",
            "why_it_matters": "Avoiding unnecessary turnover can reduce taxes and behavioral mistakes.",
            "expected_benefit": "Maintains the current strategy while improving alignment incrementally.",
            "costs_taxes_risks": "The current portfolio can still underperform and policy estimates can be incomplete.",
            "alternatives": ["Run a gradual-transition analysis", "Revise the policy if circumstances changed"],
            "doing_nothing": "Existing allocation differences remain until contributions or market movement change them.",
            "confidence": "medium", "missing_information": ["Complete household holdings", "Fees", "Tax lots"],
            "review_date": (date.today() + timedelta(days=90)).isoformat(),
            "reversal_evidence": "A policy breach, deteriorating goal projection, material cash-flow change, or materially fresher evidence.",
        })

    preferences = policy.get("research_preferences", {})
    return {
        "as_of": date.today().isoformat(), "policy_status": policy.get("status", "draft"),
        "recommendations": recommendations[:3], "next_dollar": next_dollar, "alerts": alerts[:8],
        "model_customization": {
            "method": "policy_weighted_transparent_research_v1", "preferences": preferences,
            "production_model_changed": False,
            "validation_status": (monitoring or {}).get("status", "not_run"),
            "explanation": "Preferences change the emphasis of transparent research comparisons. They do not retrain or promote an ML model without a recorded walk-forward validation and promotion decision.",
            "available_dimensions": ["fundamentals", "growth", "valuation", "dividend income", "macro resilience", "price behavior"],
        },
        "assumptions": ["No trades are submitted", "Household assets not entered in EagleEyes are excluded", "Fund and advisory fees are not yet complete"],
        "lineage": {"holdings": "saved portfolio", "goals": "saved planning goals", "policy": "user-approved policy", "research": "stored security research"},
    }
