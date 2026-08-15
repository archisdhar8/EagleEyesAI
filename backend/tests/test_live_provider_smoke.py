from __future__ import annotations

import os
import time

import httpx
import pytest


pytestmark = pytest.mark.live

RUN_LIVE = os.getenv("RUN_LIVE_SMOKE") == "1"
BASE_URL = os.getenv("LIVE_API_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("LIVE_ACCESS_TOKEN", "")
SECOND_TOKEN = os.getenv("LIVE_SECOND_ACCESS_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
TICKER = os.getenv("LIVE_SMOKE_TICKER", "SPY").upper()


def _client(token: str = TOKEN) -> httpx.Client:
    if not RUN_LIVE:
        pytest.skip("Set RUN_LIVE_SMOKE=1 to call real providers.")
    if not token:
        pytest.skip("LIVE_ACCESS_TOKEN is required for authenticated live smoke tests.")
    return httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=90)


def _ok(response: httpx.Response) -> dict:
    assert response.status_code < 400, response.text
    return response.json()


def test_live_supabase_auth_and_rls_boundary() -> None:
    with _client() as client:
        health = _ok(client.get("/api/providers/health"))
        supabase = next(row for row in health["providers"] if row["key"] == "supabase")
        assert supabase["configured"] is True
        first_ids = {row["id"] for row in _ok(client.get("/api/portfolios"))}
    if SECOND_TOKEN:
        with _client(SECOND_TOKEN) as other:
            second_ids = {row["id"] for row in _ok(other.get("/api/portfolios"))}
        assert first_ids.isdisjoint(second_ids), "RLS smoke accounts returned overlapping private portfolio records"


def test_live_supabase_direct_rest_rls_isolates_owned_records() -> None:
    if not SECOND_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
        pytest.skip("Second user token and Supabase public connection settings are required for direct RLS verification.")
    with _client() as owner:
        created = _ok(owner.post("/api/terminal/layouts", json={"name": "RLS smoke layout", "widgets": []}))
    try:
        headers = {"Authorization": f"Bearer {SECOND_TOKEN}", "apikey": SUPABASE_KEY}
        response = httpx.get(f"{SUPABASE_URL}/rest/v1/terminal_layouts", params={"id": f"eq.{created['id']}", "select": "id,user_id"}, headers=headers, timeout=20)
        assert response.status_code == 200, response.text
        assert response.json() == [], "A second authenticated user could read the owner's terminal layout"
    finally:
        with _client() as owner:
            owner.delete(f"/api/terminal/layouts/{created['id']}")


@pytest.mark.parametrize("provider", ["fred", "prices", "prediction_markets", "sec"])
def test_live_provider_refresh(provider: str) -> None:
    with _client() as client:
        payload = _ok(client.post(f"/api/providers/refresh/{provider}", params={"tickers": TICKER}))
    assert payload["provider"] == provider
    assert isinstance(payload["rows"], int)
    assert payload["health"]["version"] == "provider-health-v1"


def test_live_adjusted_price_coverage_and_lineage() -> None:
    with _client() as client:
        coverage = _ok(client.get("/api/research/coverage", params={"tickers": TICKER}))
    assert coverage["calculation_version"] == "historical-coverage-v1"
    symbol = next(row for row in coverage["symbols"] if row["ticker"] == TICKER)
    assert symbol["first_date"] and symbol["last_date"]
    assert symbol["observations"] > 0
    assert symbol["corporate_action_adjusted"] is True
    assert symbol["lineage"] and symbol["lineage"][0]["effective_through"]


def test_live_gemini_planner_widgets_and_narrator() -> None:
    with _client() as client:
        job = _ok(client.post("/api/dashboard/drafts", json={"prompt": f"Compare {TICKER} with its broad-market benchmark over one year"}))
        deadline = time.monotonic() + 60
        while job.get("state") not in {"COMPLETE", "PARTIAL_SUCCESS", "FAILED", "CANCELLED", "EXPIRED"} and time.monotonic() < deadline:
            time.sleep(1)
            job = _ok(client.get(f"/api/dashboard/drafts/{job['id']}"))
    assert job["state"] in {"COMPLETE", "PARTIAL_SUCCESS"}, job.get("error")
    assert job.get("plan") and job.get("specification")
    assert job.get("widget_results")
    assert job.get("narrative"), "Gemini narration did not complete"
