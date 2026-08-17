from fastapi.testclient import TestClient

from backend.main import app


def _result(run_id: str) -> dict:
    return {
        "id": run_id,
        "created_at": "2026-08-16T12:00:00+00:00",
        "model_version": "test-analysis-v1",
        "alternatives": [
            {"name": "Risk-Controlled"},
            {"name": "Balanced"},
            {"name": "Goal-Tilted"},
        ],
        "research": [],
        "macro": {"regime": "neutral", "score": 50, "as_of": "2026-08-15"},
        "warnings": [],
        "data_lineage": {},
    }


def test_analysis_reuses_same_market_session_and_restores_latest(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_run(holdings, profile):
        calls.append(profile.model_dump(mode="json"))
        return _result(f"run-{len(calls)}")

    monkeypatch.setattr("backend.main.run_analysis", fake_run)
    monkeypatch.setattr(
        "backend.main.database.price_history",
        lambda tickers, limit_per_ticker=1: [
            {"ticker": "SPY", "date": "2026-08-14T20:00:00+00:00", "close": 500, "provider": "test"}
        ],
    )
    request = {
        "portfolio": {
            "name": "Saved portfolio",
            "holdings": [{"ticker": "SPY", "weight": 1, "account_type": "taxable"}],
        }
    }
    with TestClient(app) as client:
        first = client.post("/api/analyses", json=request)
        second = client.post("/api/analyses", json=request)
        latest = client.get("/api/analyses/latest")

    assert first.status_code == 200
    assert first.json()["cache_status"] == "miss"
    assert second.json()["cache_status"] == "hit"
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["market_session"] == "2026-08-14"
    assert latest.json()["analysis"]["id"] == first.json()["id"]
    assert len(calls) == 1


def test_objective_change_invalidates_analysis_cache(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_run(holdings, profile):
        calls.append(profile.model_dump(mode="json"))
        return _result(f"run-{len(calls)}")

    monkeypatch.setattr("backend.main.run_analysis", fake_run)
    monkeypatch.setattr(
        "backend.main.database.price_history",
        lambda tickers, limit_per_ticker=1: [
            {"ticker": "SPY", "date": "2026-08-14", "close": 500, "provider": "test"}
        ],
    )
    portfolio = {
        "name": "Saved portfolio",
        "holdings": [{"ticker": "SPY", "weight": 1, "account_type": "taxable"}],
    }
    with TestClient(app) as client:
        first = client.post("/api/analyses", json={"portfolio": portfolio})
        changed = client.post(
            "/api/analyses",
            json={"portfolio": portfolio, "profile": {"objectives": {"expected_return": 0.75}}},
        )

    assert first.json()["cache_status"] == "miss"
    assert changed.json()["cache_status"] == "miss"
    assert changed.json()["id"] != first.json()["id"]
    assert len(calls) == 2
