from copy import deepcopy

from backend import database, portfolio_overview


def research(ticker: str, score: float = 75, confidence: float = 90) -> dict:
    return {
        "ticker": ticker, "company": ticker, "fundamental_score": score,
        "valuation_score": score, "technical_score": score, "confidence": confidence,
        "data_quality": "high", "fundamentals_as_of": "2026-06-30",
        "market_statistics": {"return_1d": .01, "return_1m": .04, "return_1y": .15},
    }


def diagnostics(weights: list[tuple[str, float]]) -> dict:
    return {
        "sector_exposure": [{"sector": "Technology", "weight": sum(weight for _, weight in weights)}],
        "industry_exposure": [],
        "marginal_risk": {"status": "ready", "positions": [
            {"ticker": ticker, "risk_contribution": weight, "portfolio_weight": weight}
            for ticker, weight in weights
        ]},
        "intelligence": {
            "concentration": {"effective_holdings": 1 / sum(weight ** 2 for _, weight in weights)},
            "economic_dependencies": [],
        },
    }


def build(holdings: list[dict], rows: list[dict], **extra) -> dict:
    weights = [(row["ticker"], row["weight"]) for row in holdings]
    return portfolio_overview.build_portfolio_overview(
        portfolio={"id": "p1", "name": "Primary", "holdings": holdings},
        diagnostics=diagnostics(weights), research=rows, **extra,
    )


def test_score_is_deterministic_and_uses_disclosed_weights():
    holdings = [{"ticker": "MSFT", "weight": .5}, {"ticker": "AAPL", "weight": .5}]
    first = build(holdings, [research("MSFT"), research("AAPL")])
    second = build(deepcopy(holdings), [research("MSFT"), research("AAPL")])
    assert first["health"] == second["health"]
    assert sum(item["weight"] for item in first["health"]["components"].values()) == 1
    assert first["version"] == "portfolio-health-v1"


def test_missing_coverage_receives_conservative_score_and_low_confidence():
    holdings = [{"ticker": "MSFT", "weight": .5}, {"ticker": "UNKNOWN", "weight": .5}]
    result = build(holdings, [research("MSFT", 80, 90)])
    assert result["health"]["components"]["fundamentals"]["score"] == 60
    assert result["health"]["coverage"] == .5
    assert result["health"]["confidence"] == "Low"
    assert any(action["action"] == "INVESTIGATE" for action in result["actions"])


def test_concentration_action_and_thesis_breaker_rank_above_ordinary_review():
    holdings = [{"ticker": "MSFT", "weight": .8}, {"ticker": "AAPL", "weight": .2}]
    monitor = {"ticker": "MSFT", "thesis_id": "t1", "requires_review": True,
               "overall_status": "THESIS_BREAKER_TRIGGERED", "evidence_quality": "HIGH"}
    result = build(holdings, [research("MSFT"), research("AAPL")], monitors=[monitor])
    assert any(action["action"] == "REDUCE" for action in result["actions"])
    assert result["actions"][0]["source"] == "thesis_monitor"
    assert result["actions"][0]["materiality"] == "CRITICAL"


def test_holding_conviction_is_never_inferred():
    holdings = [{"ticker": "MSFT", "weight": 1}]
    no_decision = build(holdings, [research("MSFT")])
    explicit = build(holdings, [research("MSFT")], decisions=[{"ticker": "MSFT", "user_confidence": 4}])
    assert no_decision["holdings"][0]["conviction"] is None
    assert explicit["holdings"][0]["conviction"] == 4


def test_previous_nightly_snapshot_drives_score_and_holding_changes():
    holdings = [{"ticker": "MSFT", "weight": 1}]
    baseline = build(holdings, [research("MSFT", 80)])
    changed = build(holdings, [research("MSFT", 45)], previous_nightly=baseline)
    assert changed["health"]["delta"] < 0
    assert any(item["type"] == "HOLDING" and item["ticker"] == "MSFT" for item in changed["changes"])


def test_empty_portfolio_is_explicit_and_does_not_invent_health():
    result = portfolio_overview.build_portfolio_overview(
        portfolio={"id": "p1", "name": "Empty", "holdings": []},
        diagnostics={"sector_exposure": [], "marginal_risk": {}, "intelligence": {}}, research=[],
    )
    assert result["health"]["score"] == 0
    assert result["health"]["band"] == "Critical"
    assert result["holdings"] == []


def test_all_cash_does_not_create_a_reduce_concentration_action():
    result = build([{"ticker": "CASH", "weight": 1}], [])
    assert result["health"]["components"]["risk"]["score"] == 100
    assert not any(action["action"] == "REDUCE" and "CASH" in action["affected_holdings"] for action in result["actions"])


def test_snapshot_and_action_state_are_persistent_and_portfolio_scoped():
    portfolio = database.save_portfolio("Primary", [{"ticker": "MSFT", "weight": 1}], user_id="user-a")
    result = build([{"ticker": "MSFT", "weight": 1}], [research("MSFT")])
    first = database.save_portfolio_health_snapshot("user-a", portfolio["id"], result, "NIGHTLY", "same-input")
    second = database.save_portfolio_health_snapshot("user-a", portfolio["id"], result, "NIGHTLY", "same-input")
    assert first["id"] == second["id"]
    assert len(database.portfolio_health_history("user-a", portfolio["id"])) == 1

    database.sync_portfolio_actions("user-a", portfolio["id"], result["actions"])
    actions = database.portfolio_actions("user-a", portfolio["id"])
    assert actions
    updated = database.save_portfolio_action_state("user-a", actions[0]["id"], "INVESTIGATING")
    assert updated["state"] == "INVESTIGATING"
    assert database.portfolio_actions("user-b", portfolio["id"]) == []
