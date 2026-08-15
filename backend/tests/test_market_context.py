from backend.market_context import overlay_observations


def test_older_snapshot_cannot_override_newer_adjusted_close():
    prices = [{
        "ticker": "SPY", "date": "2026-08-10T00:00:00+00:00",
        "close": 650.0, "provider": "polygon",
    }]
    observations = [{
        "ticker": "SPY", "observed_at": "2026-08-07T20:00:00+00:00",
        "value": 640.0, "provider": "cached snapshot",
        "retrieved_at": "2026-08-11T00:00:00+00:00", "latency_class": "cached",
        "data_status": "cached", "entitlement": "end_of_day",
    }]
    assert overlay_observations(prices, observations) == prices


def test_newer_snapshot_is_appended_after_latest_adjusted_close():
    prices = [{"ticker": "SPY", "date": "2026-08-10T00:00:00+00:00", "close": 650.0}]
    observations = [{
        "ticker": "SPY", "observed_at": "2026-08-11T20:00:00+00:00",
        "value": 655.0, "provider": "delayed snapshot",
        "retrieved_at": "2026-08-11T20:15:00+00:00", "latency_class": "delayed",
        "data_status": "delayed", "entitlement": "provider_delayed",
    }]
    result = overlay_observations(prices, observations)
    assert len(result) == 2
    assert result[-1]["close"] == 655.0
