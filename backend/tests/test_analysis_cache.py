from fastapi.testclient import TestClient

from backend.main import app
from backend import main


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


def test_exact_research_detail_reuses_shared_stored_evidence_without_user_context(monkeypatch) -> None:
    calls = {"research": 0, "reference": 0}
    main._RESEARCH_DETAIL_CACHE.clear()

    def fake_research(tickers, price_limit=260):
        calls["research"] += 1
        return [{"ticker": tickers[0], "company": "Example"}]

    def fake_reference(tickers):
        calls["reference"] += 1
        return {"events": [{"ticker": tickers[0]}]}

    monkeypatch.setattr(main, "security_research", fake_research)
    monkeypatch.setattr(main.database, "research_reference_data", fake_reference)
    first = main._cached_research_detail("AAPL")
    first[0][0]["company"] = "mutated by caller"
    second = main._cached_research_detail("AAPL")

    assert calls == {"research": 1, "reference": 1}
    assert second[0][0]["company"] == "Example"


def test_analysis_reuses_same_durable_job_without_inline_optimizer(monkeypatch) -> None:
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

    assert first.status_code == 202
    assert first.json()["status"] == "PENDING"
    assert second.json()["job"]["id"] == first.json()["job"]["id"]
    assert latest.json()["analysis"] is None
    assert calls == []


def test_objective_change_creates_distinct_durable_optimizer_job(monkeypatch) -> None:
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

    assert first.json()["status"] == "PENDING"
    assert changed.json()["status"] == "PENDING"
    assert changed.json()["job"]["id"] != first.json()["job"]["id"]
    assert calls == []
