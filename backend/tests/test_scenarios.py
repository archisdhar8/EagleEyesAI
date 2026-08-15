from unittest.mock import Mock, patch

import pytest

from backend.scenarios import (
    build_condition_dimensions, build_scenarios, canonical_contract_series, discover_polymarket_contracts,
    normalize_kalshi, normalize_polymarket,
    sanitize_contracts,
)


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


def test_polymarket_discovery_pages_events_and_extracts_nested_markets() -> None:
    first = Mock()
    first.raise_for_status.return_value = None
    first.json.return_value = [{"markets": [{
        "id": "m1", "conditionId": "c1", "question": "Will US inflation exceed 3%?",
        "outcomePrices": '["0.4", "0.6"]',
    }]} for _ in range(100)]
    last = Mock()
    last.raise_for_status.return_value = None
    last.json.return_value = [{"markets": [{
        "id": "m2", "conditionId": "c2", "question": "Will the US enter a recession?",
        "outcomePrices": '["0.3", "0.7"]',
    }]}]
    with patch("backend.scenarios.requests.get", side_effect=[first, last]) as get:
        contracts = discover_polymarket_contracts(max_events=200)
    assert {row["provider"] for row in contracts} == {"Polymarket"}
    assert {row["scenario"] for row in contracts} == {"sticky_inflation", "recession_cuts"}
    assert get.call_args_list[1].kwargs["params"]["offset"] == 100


@pytest.mark.parametrize(
    "market",
    [
        {"ticker": "SOCCER-1", "title": "Brentford vs Tottenham Winner?", "last_price": 42},
        {"ticker": "NHL-1", "title": "Will the Edmonton Oilers win the game?", "last_price": 55},
        {
            "ticker": "PLAYER-1",
            "title": "Will Brent score in the match?",
            "category": "Sports",
            "last_price": 30,
        },
    ],
)
def test_kalshi_rejects_sports_markets_that_contain_commodity_words(market: dict) -> None:
    assert normalize_kalshi([market]) == []


def test_kalshi_accepts_explicit_brent_crude_market() -> None:
    contracts = normalize_kalshi([{
        "ticker": "BRENT-100", "event_ticker": "BRENT", "category": "Economics",
        "title": "Will Brent crude oil be above $100?", "last_price": 41,
    }])
    assert len(contracts) == 1
    assert contracts[0]["scenario"] == "oil_shock"
    assert contracts[0]["indicator"] == "oil price"


def test_cached_contracts_are_revalidated_by_current_classifier() -> None:
    valid = {
        "provider": "Kalshi", "id": "oil", "event_id": "oil", "title": "Will WTI oil price exceed $100?",
        "scenario": "oil_shock", "indicator": "oil price", "probability": .4, "confidence": .5,
    }
    invalid = {
        "provider": "Kalshi", "id": "football", "event_id": "football",
        "title": "Brentford vs Tottenham Winner?", "scenario": "oil_shock",
        "indicator": "oil price", "probability": .4, "confidence": .5,
    }
    accepted, rejected = sanitize_contracts([valid, invalid])
    assert accepted == [valid]
    assert rejected == [invalid]


def test_duplicate_contracts_do_not_count_twice() -> None:
    contract = {"provider": "Kalshi", "id": "a", "event_id": "event", "title": "Recession", "scenario": "recession_cuts", "indicator": "recession probability", "probability": .7, "confidence": .8, "source": "x"}
    scenarios = build_scenarios([contract, {**contract, "id": "b", "confidence": .2}])
    recession = next(item for item in scenarios if item["key"] == "recession_cuts")
    assert recession["probability"] < .7
    assert sum(item["probability"] for item in scenarios) != pytest.approx(1)
    assert {item["dimension"] for item in scenarios} == {
        "Economic conditions", "Inflation conditions", "Independent market shocks"
    }


def test_macro_trend_model_replaces_fixed_prior_when_market_evidence_is_missing() -> None:
    macro_signal = {
        "as_of_date": "2026-07-31", "confidence": .60, "data_quality": 1.0,
        "probabilities": {
            "soft_landing": .10, "sticky_inflation": .60, "recession_cuts": .10,
            "growth_reacceleration": .10, "oil_shock": .10,
        },
    }
    scenarios = build_scenarios([], macro_signal=macro_signal)
    sticky = next(item for item in scenarios if item["key"] == "sticky_inflation")
    assert sticky["probability"] > .45
    assert sticky["evidence_basis"] == "macro_trend_model"
    assert sticky["is_prior"] is False
    assert "FRED macro trends" in sticky["indicators"]


def test_thresholds_from_one_event_count_as_one_signal() -> None:
    base = {"provider": "Kalshi", "event_id": "wti-aug-11", "scenario": "oil_shock", "indicator": "oil price", "source": "x"}
    strongest = {**base, "id": "wti-78", "title": "WTI above 78", "probability": .40, "confidence": .8}
    related_threshold = {**base, "id": "wti-82", "title": "WTI above 82", "probability": .10, "confidence": .2}
    grouped = build_scenarios([strongest, related_threshold])
    baseline = build_scenarios([strongest])
    grouped_oil = next(item for item in grouped if item["key"] == "oil_shock")
    baseline_oil = next(item for item in baseline if item["key"] == "oil_shock")
    assert grouped_oil["probability"] == baseline_oil["probability"]


def test_contract_series_links_expirations_and_preserves_thresholds() -> None:
    january = {
        "scenario": "sticky_inflation", "indicator": "inflation path",
        "title": "Will CPI inflation be above 3% in January 2027?",
    }
    february = {**january, "title": "Will CPI inflation be above 3% in February 2027?"}
    lower = {**january, "title": "Will CPI inflation be below 2% in January 2027?"}
    january_key, january_bucket = canonical_contract_series(january)
    february_key, _ = canonical_contract_series(february)
    lower_key, lower_bucket = canonical_contract_series(lower)
    assert january_key == february_key
    assert january_key != lower_key
    assert january_bucket == {"operator": "gte", "value": 3.0, "unit": "%"}
    assert lower_bucket["operator"] == "lte"


def test_condition_dimensions_keep_oil_independent_and_support_combinations() -> None:
    conditions = build_condition_dimensions(build_scenarios([]))
    by_dimension: dict[str, list[dict]] = {}
    for condition in conditions:
        by_dimension.setdefault(condition["dimension"], []).append(condition)
    assert sum(row["probability"] for row in by_dimension["Economic state"]) == pytest.approx(1, abs=.001)
    assert sum(row["probability"] for row in by_dimension["Inflation state"]) == pytest.approx(1, abs=.001)
    assert sum(row["probability"] for row in by_dimension["Rate state"]) == pytest.approx(1, abs=.001)
    assert {row["key"] for row in by_dimension["Independent shocks"]} == {"shock_oil"}
    assert any(row["key"] == "economic_recession" for row in conditions)
    assert any(row["key"] == "inflation_accelerating" for row in conditions)
