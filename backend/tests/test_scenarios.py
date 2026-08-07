import pytest

from backend.scenarios import build_scenarios, normalize_kalshi, normalize_polymarket


def test_kalshi_confidence_ignores_deprecated_liquidity() -> None:
    market = {
        "ticker": "CPI-TEST", "event_ticker": "CPI", "title": "Will CPI inflation be above 3%?",
        "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44", "volume_fp": "1200",
        "open_interest_fp": "800", "liquidity_dollars": "999999999", "updated_time": "2026-08-05T12:00:00Z",
    }
    first = normalize_kalshi([market])[0]
    market["liquidity_dollars"] = "0"
    second = normalize_kalshi([market])[0]
    assert first["confidence"] == pytest.approx(second["confidence"])
    assert first["scenario"] == "sticky_inflation"


def test_polymarket_maps_outcome_prices_and_event_id() -> None:
    contracts = normalize_polymarket([{
        "id": "m1", "conditionId": "condition-1", "question": "Will the US enter a recession?",
        "outcomePrices": '["0.31", "0.69"]', "volumeNum": 5000, "bestBid": 0.30, "bestAsk": 0.32,
    }])
    assert contracts[0]["probability"] == 0.31
    assert contracts[0]["event_id"] == "condition-1"


def test_duplicate_contracts_do_not_count_twice() -> None:
    contract = {"provider": "Kalshi", "id": "a", "event_id": "event", "title": "Recession", "scenario": "recession_cuts", "indicator": "recession probability", "probability": .7, "confidence": .8, "source": "x"}
    scenarios = build_scenarios([contract, {**contract, "id": "b", "confidence": .2}])
    recession = next(item for item in scenarios if item["key"] == "recession_cuts")
    assert recession["probability"] < .7
    assert abs(sum(item["probability"] for item in scenarios) - 1) < 0.001
