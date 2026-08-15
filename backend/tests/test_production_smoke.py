from __future__ import annotations

import os
import httpx
import pytest

pytestmark = pytest.mark.production


def test_deployed_api_smoke_contract() -> None:
    url = os.getenv("PRODUCTION_API_URL", "").rstrip("/")
    token = os.getenv("PRODUCTION_SMOKE_ACCESS_TOKEN", "")
    if os.getenv("RUN_PRODUCTION_SMOKE") != "1" or not url or not token:
        pytest.skip("Set RUN_PRODUCTION_SMOKE=1, PRODUCTION_API_URL, and PRODUCTION_SMOKE_ACCESS_TOKEN.")
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=url, headers=headers, timeout=30) as client:
        responses = [client.get("/api/health"), client.get("/api/home/briefing"), client.get("/api/research/search", params={"q": "AAPL", "limit": 3}), client.get("/api/operations/metrics")]
    health, briefing, research, operations = responses
    assert health.status_code == 200 and health.json()["trading_enabled"] is False
    assert briefing.status_code == 200 and briefing.json().get("version")
    assert research.status_code == 200 and research.json()["method"]["version"] == "research-workspace-v2"
    assert operations.status_code == 200 and operations.json()["version"] == "operational-monitoring-v1"
    for response in responses:
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers.get("x-request-id")
