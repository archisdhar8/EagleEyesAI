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


def test_csv_import_validation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Test", "csv_text": "ticker,weight,account_type\nSPY,0.6,taxable\nBND,0.4,traditional_ira\n"})
    assert response.status_code == 200
    assert response.json()["validated_rows"] == 2


def test_csv_import_rejects_rows_without_size() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"csv_text": "ticker,account_type\nSPY,taxable\n"})
    assert response.status_code == 422
