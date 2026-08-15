from backend.guidance import PERSONALIZED_GUIDANCE, PORTFOLIO_AWARE_ANALYSIS, guidance_disclosure


def _profile() -> dict:
    return {
        "risk_tolerance": 6, "loss_capacity": 6, "tax_rate": .2,
        "suitability_profile": {
            "guidance_level": "recommendations", "required_risk": 5,
            "liquidity_needs_next_24_months": 0,
        },
    }


def test_personalized_guidance_requires_approved_policy_and_goal() -> None:
    portfolio = {"holdings": [{"ticker": "AAPL", "account_type": "taxable"}]}
    result = guidance_disclosure(portfolio=portfolio, profile=_profile(), policy={"status": "draft"}, goals=[])
    assert result["level"] == PORTFOLIO_AWARE_ANALYSIS
    assert "approved investment policy" in result["missing_context"]
    assert "current goal context" in result["missing_context"]


def test_complete_context_can_emit_personalized_guidance() -> None:
    portfolio = {"holdings": [{"ticker": "AAPL", "account_type": "taxable"}]}
    result = guidance_disclosure(
        portfolio=portfolio, profile=_profile(), policy={"status": "approved"},
        goals=[{"name": "Retirement"}],
    )
    assert result["level"] == PERSONALIZED_GUIDANCE
    assert not result["missing_context"]
