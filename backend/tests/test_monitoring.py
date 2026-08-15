from backend.monitoring import build_monitoring_result, calibration_metrics, run_monitoring
from backend.quant import REGIME_KEYS


def test_prediction_market_calibration_scores_realized_regimes() -> None:
    rows = []
    for index in range(6):
        actual = REGIME_KEYS[index % len(REGIME_KEYS)]
        for key in REGIME_KEYS:
            rows.append({
                "snapshot_id": f"snapshot-{index}", "scenario_key": key,
                "probability": .60 if key == actual else .10,
                "dominant_regime": actual, "observed_at": f"2025-0{index + 1}-20",
                "realized_at": f"2025-0{index + 2}-28",
            })
    result = calibration_metrics(rows)
    assert result["status"] == "complete"
    assert result["sample_count"] == 6
    assert result["brier_score"] < .25


def test_monitoring_flags_conditioning_turnover_and_stale_data() -> None:
    analysis = {
        "model_diagnostics": {"covariance": {"shrunk_condition_number": 200000}},
        "walk_forward": {
            "status": "complete", "period_count": 4,
            "model": {"annualized_return": .04},
            "benchmarks": [{"name": "Equal", "annualized_return": .07}],
        },
        "alternatives": [{"name": "Balanced", "turnover": .70, "allocations": []}],
    }
    result = build_monitoring_result(
        analysis,
        {"freshness": {}, "price_coverage": []},
        {"status": "insufficient_history", "brier_score": None},
    )
    assert result["status"] == "warning"
    assert any("covariance" in alert.lower() for alert in result["alerts"])
    assert any("turnover" in alert.lower() for alert in result["alerts"])
    assert any("price data" in alert.lower() for alert in result["alerts"])


def test_scheduled_monitoring_skips_without_a_system_owned_portfolio(monkeypatch) -> None:
    monkeypatch.setattr("backend.monitoring.database.list_portfolios", lambda: [])

    result = run_monitoring()

    assert result["status"] == "skipped"
    assert result["id"] is None
    assert "authenticated analysis context" in result["reason"]
