from backend import provider_health


def test_provider_health_reports_configuration_fallbacks_and_rate_limits(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-test")
    monkeypatch.setenv("FRED_API_KEY", "fred-test")
    monkeypatch.setenv("TIINGO_API_KEY", "tiingo-test")
    monkeypatch.setenv("SEC_USER_AGENT", "test@example.com")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(provider_health.database, "provider_data_status", lambda: {
        "storage": "supabase", "counts": {}, "freshness": {},
        "providers": [{"provider": "fred", "status": "success", "fetched_at": "2026-08-10T01:00:00Z", "as_of": "2026-08-01", "metadata": {"rate_limit_remaining": 99}, "error": None}],
        "price_coverage": [{"provider": "tiingo", "bars": 5000, "symbols": 2, "earliest": "2006-01-01", "latest": "2026-08-09"}],
    })
    result = provider_health.build_provider_health()
    fred = next(row for row in result["providers"] if row["key"] == "fred")
    prices = next(row for row in result["providers"] if row["key"] == "prices")
    assert fred["status"] == "healthy"
    assert fred["rate_limit"]["rate_limit_remaining"] == 99
    assert prices["configured"] is True
    assert prices["coverage"]["symbols"] == 2
    assert "Security → sector ETF → VTI" in prices["fallbacks"]


def test_provider_health_does_not_expose_secret_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-return-this")
    monkeypatch.setattr(provider_health.database, "provider_data_status", lambda: {"storage": "sqlite", "providers": [], "price_coverage": []})
    result = provider_health.build_provider_health()
    assert "do-not-return-this" not in str(result)
    gemini = next(row for row in result["providers"] if row["key"] == "gemini")
    assert gemini["configured"] is True
    assert gemini["status"] == "awaiting_data"


def test_provider_health_whitelists_metadata(monkeypatch):
    monkeypatch.setattr(provider_health.database, "provider_data_status", lambda: {
        "storage": "supabase", "price_coverage": [],
        "providers": [{"provider": "fred", "status": "success", "fetched_at": "2026-08-10", "as_of": "2026-08-01", "metadata": {"api_key": "never-return", "remaining": 7}}],
    })
    result = provider_health.build_provider_health()
    assert "never-return" not in str(result)
    fred = next(row for row in result["providers"] if row["key"] == "fred")
    assert fred["rate_limit"]["remaining"] == 7
