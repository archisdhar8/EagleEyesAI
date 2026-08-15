from __future__ import annotations

from typing import Any


GENERAL_MARKET_RESEARCH = "General Market Research"
PORTFOLIO_AWARE_ANALYSIS = "Portfolio-Aware Analysis"
PERSONALIZED_GUIDANCE = "Personalized Guidance"


def guidance_disclosure(
    *, portfolio: dict[str, Any] | None = None, profile: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None, goals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe how much user context is actually used without overstating suitability."""
    holdings = (portfolio or {}).get("holdings") or []
    if not holdings:
        return {
            "level": GENERAL_MARKET_RESEARCH,
            "reason": "No saved holdings are used; conclusions describe general market or security evidence.",
            "missing_context": ["saved portfolio"],
        }
    suitability = (profile or {}).get("suitability_profile") or {}
    requested = suitability.get("guidance_level", "research_only")
    requirements = {
        "risk tolerance": (profile or {}).get("risk_tolerance") is not None,
        "loss capacity": (profile or {}).get("loss_capacity") is not None,
        "required risk": suitability.get("required_risk") is not None,
        "tax and account context": (profile or {}).get("tax_rate") is not None and all(row.get("account_type") for row in holdings),
        "liquidity needs": suitability.get("liquidity_needs_next_24_months") is not None,
        "current goal context": bool(goals),
        "approved investment policy": bool(policy and policy.get("status") == "approved"),
    }
    missing = [label for label, complete in requirements.items() if not complete]
    stale = [
        label for label, value in (
            ("portfolio", (portfolio or {}).get("updated_at")),
            ("planning profile", (profile or {}).get("updated_at")),
        ) if value and _older_than_days(value, 365)
    ]
    if requested == "recommendations" and profile:
        if not missing and not stale:
            return {
                "level": PERSONALIZED_GUIDANCE,
                "reason": "Saved holdings and the user-approved planning profile materially shape this result.",
                "missing_context": [],
                "stale_context": [],
                "requirements": requirements,
            }
    return {
        "level": PORTFOLIO_AWARE_ANALYSIS,
        "reason": "Saved holdings shape exposure and fit conclusions; incomplete planning context limits personalization.",
        "missing_context": (["request Personalized Guidance in Plan"] if requested != "recommendations" else missing),
        "stale_context": stale,
        "requirements": requirements,
    }


def _older_than_days(value: Any, days: int) -> bool:
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days > days
    except (TypeError, ValueError):
        return True
