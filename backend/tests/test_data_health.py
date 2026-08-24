from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend import data_health, database
from backend.ask_resolution import DataHealthStatus


def test_data_health_migration_accepts_every_runtime_domain():
    migration = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "202608220006_data_health_states.sql"
    ).read_text(encoding="utf-8")

    for domain in data_health.DOMAINS:
        assert f"'{domain}'" in migration


def test_exact_remediation_actions_for_stale_missing_and_partial_domains(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(database, "analytical_dataset_versions", lambda *_: {
        "fundamentals": {"effective_through": (now - timedelta(days=180)).isoformat()},
        "securities": {"effective_through": now.isoformat()},
        "macro": {"effective_through": (now - timedelta(days=20)).isoformat()},
    })
    monkeypatch.setattr(database, "data_health_states", lambda *_: [])
    states = {state.domain: state for state in data_health.derive(
        "health-test-user", "health-test-portfolio",
        field_coverage={"classifications": .72},
    )}

    assert states["fundamentals"].status == DataHealthStatus.STALE
    assert states["fundamentals"].repair_action == "refresh_fundamentals"
    assert states["classifications"].status == DataHealthStatus.PARTIAL
    assert states["classifications"].repair_action == "reconcile_security_master"
    assert states["events"].status == DataHealthStatus.MISSING
    assert states["earnings_events"].repair_action == "refresh_earnings_events"
    assert states["macro_events"].repair_action == "refresh_macro_event_calendar"
    assert states["cash_hurdle"].status == DataHealthStatus.STALE
    assert states["cash_hurdle"].repair_action == "refresh_cash_hurdle"
