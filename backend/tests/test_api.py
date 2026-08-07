from fastapi.testclient import TestClient

from backend.main import app


def test_health_is_local_and_non_trading() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/health").json()
    assert payload == {"status": "ok", "mode": "local-only", "trading_enabled": False}


def test_csv_import_validation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Test", "csv_text": "ticker,weight,account_type\nSPY,0.6,taxable\nBND,0.4,traditional_ira\n"})
    assert response.status_code == 200
    assert response.json()["validated_rows"] == 2


def test_csv_import_rejects_rows_without_size() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"csv_text": "ticker,account_type\nSPY,taxable\n"})
    assert response.status_code == 422

