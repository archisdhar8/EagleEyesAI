from backend import retention


def test_retention_is_a_dry_run_by_default(monkeypatch):
    monkeypatch.setattr(retention, "retention_report", lambda: {
        "version": retention.RETENTION_VERSION, "storage": "supabase", "candidates": {"overlapping_price_bars": 12},
    })
    monkeypatch.setattr(retention.database, "DATABASE_URL", "configured")
    result = retention.archive_and_prune(execute=False)
    assert result["executed"] is False
    assert result["candidates"]["overlapping_price_bars"] == 12
