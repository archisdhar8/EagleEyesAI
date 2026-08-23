from backend import feature_flags, main


def test_optional_rollout_flags_default_on(monkeypatch):
    monkeypatch.delenv("PREDICTION_MARKET_ENRICHMENT_ENABLED", raising=False)
    monkeypatch.delenv("CONVERSATIONAL_DASHBOARDS_ENABLED", raising=False)
    assert feature_flags.prediction_market_enrichment_enabled() is True
    assert feature_flags.conversational_dashboards_enabled() is True


def test_optional_rollout_flags_disable_independently(monkeypatch):
    monkeypatch.setenv("PREDICTION_MARKET_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("CONVERSATIONAL_DASHBOARDS_ENABLED", "0")
    assert feature_flags.prediction_market_enrichment_enabled() is False
    assert feature_flags.conversational_dashboards_enabled() is False


def test_prediction_enrichment_flag_returns_explicit_unavailable(monkeypatch):
    monkeypatch.setenv("PREDICTION_MARKET_ENRICHMENT_ENABLED", "0")
    results, evidence = main._phase6_chat_tools("prediction_markets", "user-a", "What matters?")
    assert results[0]["status"] == "unavailable"
    assert results[0]["analysis_result"]["status"] == "UNAVAILABLE"
    assert "disabled" in evidence[0]["data"]["message"].lower()
