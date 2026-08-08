from fastapi.testclient import TestClient

from backend.main import app


def test_health_reports_storage_and_disables_trading() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/health").json()
    assert payload == {"status": "ok", "mode": "sqlite", "storage": "sqlite", "trading_enabled": False}


def test_provider_status_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/providers/status")
    assert response.status_code == 200
    assert response.json() == {"storage": "sqlite", "counts": {}, "freshness": {}, "providers": []}


def test_regime_history_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/regimes")
    assert response.status_code == 200
    assert response.json() == {"model_version": "macro-regime-rules-v1", "history": []}


def test_model_validation_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/model-validation")
    assert response.status_code == 200
    assert response.json() == {"runs": []}


def test_model_monitoring_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/model-monitoring")
    assert response.status_code == 200
    assert response.json() == {"latest": None, "promotion_decisions": []}


def test_csv_import_validation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Test", "csv_text": "ticker,weight,account_type\nSPY,0.6,taxable\nBND,0.4,traditional_ira\n"})
    assert response.status_code == 200
    assert response.json()["validated_rows"] == 2


def test_csv_import_rejects_rows_without_size() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"csv_text": "ticker,account_type\nSPY,taxable\n"})
    assert response.status_code == 422


def test_csv_import_accepts_explicit_weight_percent() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios/import",
            json={"name": "Percent weights", "csv_text": "ticker,weight_percent\nSPY,60\nBND,40\n"},
        )
    assert response.status_code == 200
    assert [row["weight"] for row in response.json()["portfolio"]["holdings"]] == [.6, .4]


def test_csv_import_rejects_ambiguous_weight_columns() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios/import",
            json={"csv_text": "ticker,weight,weight_percent\nSPY,0.6,60\n"},
        )
    assert response.status_code == 422
    assert "either weight" in response.json()["detail"]


def test_csv_import_rejects_duplicate_tickers_cleanly() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios/import",
            json={"csv_text": "ticker,weight_percent\nAAPL,50\naapl,50\n"},
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "Duplicate tickers are not allowed: AAPL"


def test_portfolio_rejects_duplicate_tickers() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios",
            json={
                "name": "Duplicates",
                "holdings": [
                    {"ticker": "AAPL", "weight": .5},
                    {"ticker": "aapl", "weight": .5},
                ],
            },
        )
    assert response.status_code == 422
    assert "Duplicate tickers" in str(response.json()["detail"])


def test_research_refresh_updates_saved_universe(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.main.refresh_security_evidence",
        lambda tickers: {"tickers": tickers, "providers": {"tiingo": 252}, "warnings": []},
    )
    monkeypatch.setattr(
        "backend.main.refresh_company_markets",
        lambda companies: {"markets": [{"id": "market-1"}], "warnings": [], "searched": len(companies)},
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/research/refresh",
            json={"tickers": ["AAPL", "NVDA", "CASH"], "ingest_tickers": ["NVDA", "CASH"]},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["searched"] == 2
    assert payload["markets_found"] == 1
    assert payload["evidence_refresh"] == {"tickers": ["NVDA"], "providers": {"tiingo": 252}, "warnings": []}
    assert {row["ticker"] for row in payload["research"]} == {"AAPL", "NVDA"}


def test_portfolio_update_and_research_include_new_holding() -> None:
    with TestClient(app) as client:
        portfolio = client.get("/api/portfolios").json()[0]
        saved = client.put(
            f"/api/portfolios/{portfolio['id']}",
            json={
                "name": "Updated portfolio",
                "holdings": [
                    {"ticker": "AAPL", "weight": .8, "account_type": "taxable"},
                    {"ticker": "NVDA", "weight": .2, "account_type": "taxable"},
                ],
            },
        )
        research = client.get("/api/research?tickers=AAPL,NVDA")
    assert saved.status_code == 200
    assert {row["ticker"] for row in saved.json()["holdings"]} == {"AAPL", "NVDA"}
    assert {row["ticker"] for row in research.json()} == {"AAPL", "NVDA"}
