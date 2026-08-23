from pathlib import Path

from backend.migrations import migration_checksum, migration_files


def test_initial_migration_is_discoverable() -> None:
    files = migration_files()
    assert files
    assert files == sorted(files)
    assert files[0].name == "202608070001_initial_schema.sql"


def test_migration_checksum_is_stable() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608070001_initial_schema.sql"
    assert migration_checksum(path) == migration_checksum(path)
    assert len(migration_checksum(path)) == 64


def test_etf_catalog_migration_is_additive_and_versioned() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608100002_etf_research_catalog.sql"
    sql = path.read_text()
    assert "create table if not exists public.etf_catalog" in sql
    assert "create table if not exists public.etf_exposures" in sql
    assert "create table if not exists public.etf_refresh_runs" in sql
    assert "alter table public.etf_catalog enable row level security" in sql


def test_market_observation_and_event_quality_migration_is_additive() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608100004_market_observations_and_event_quality.sql"
    sql = path.read_text()
    assert "create table if not exists public.market_observations" in sql
    assert "latency_class" in sql
    assert "alter table public.market_events add column if not exists event_status" in sql
    assert "alter table public.market_observations enable row level security" in sql


def test_research_master_and_ledger_migration_is_additive_and_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608100005_research_master_and_portfolio_ledger.sql"
    sql = path.read_text().lower()
    for table in (
        "security_master", "security_coverage_snapshots", "investment_accounts",
        "portfolio_transactions", "account_valuations", "security_lots",
        "statement_reconciliations", "portfolio_performance_runs",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "drop table" not in sql
    assert "alter table public.holdings" not in sql


def test_thesis_and_decision_migration_is_additive_immutable_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160001_investment_theses_and_decisions.sql"
    sql = path.read_text().lower()
    for table in ("investment_theses", "thesis_assumptions", "thesis_factors", "thesis_versions", "investment_decisions"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "grant select,insert on public.thesis_versions,public.investment_decisions" in sql
    assert "grant select,insert,update,delete on public.thesis_versions" not in sql
    assert "drop table" not in sql
    assert "drop column" not in sql


def test_evidence_snapshot_migration_is_additive_immutable_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160002_evidence_snapshots.sql"
    sql = path.read_text().lower()
    assert "create table if not exists public.evidence_snapshots" in sql
    assert "alter table public.evidence_snapshots enable row level security" in sql
    assert "grant select,insert on public.evidence_snapshots" in sql
    assert "grant select,insert,update" not in sql
    assert "drop table" not in sql
    assert "drop column" not in sql


def test_thesis_monitor_migration_is_additive_immutable_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160003_thesis_monitor.sql"
    sql = path.read_text().lower()
    assert "create table if not exists public.thesis_review_events" in sql
    assert "alter table public.thesis_review_events enable row level security" in sql
    assert "grant select,insert on public.thesis_review_events" in sql
    assert "grant select,insert,update" not in sql
    assert "drop table" not in sql


def test_forecasting_migration_is_additive_append_only_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160004_forecasting_intelligence.sql"
    sql = path.read_text().lower()
    for table in ("user_forecasts", "forecast_resolution_events", "forecast_records"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "grant select,insert on public.user_forecasts" in sql
    assert "grant select,insert,update" not in sql
    assert "drop table" not in sql and "drop column" not in sql


def test_today_attention_state_migration_is_additive_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160005_today_attention_states.sql"
    sql = path.read_text().lower()
    assert "create table if not exists public.attention_item_states" in sql
    assert "alter table public.attention_item_states enable row level security" in sql
    assert "auth.uid() = user_id" in sql
    assert "drop table" not in sql and "drop column" not in sql


def test_decision_journal_migration_is_append_only_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160006_decision_journal.sql"
    sql = path.read_text().lower()
    for table in ("decision_context_snapshots", "decision_retrospectives"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "grant select,insert on public.decision_context_snapshots,public.decision_retrospectives" in sql
    assert "grant select,insert,update" not in sql
    assert "drop table" not in sql and "drop column" not in sql


def test_phase10_preferences_and_alerts_are_additive_and_owner_secured() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608160007_phase10_alerts_personalization.sql"
    sql = path.read_text().lower()
    for table in ("alert_preferences", "alert_events", "decision_preferences"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "in_app_only" in sql and "group_key" in sql and "supersedes_id" in sql
    assert "drop table" not in sql and "drop column" not in sql


def test_phase9_scope_migration_supports_company_global_and_portfolio_models() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase/migrations/202608220005_analytical_scope_keys.sql"
    sql = path.read_text().lower()
    assert "add column if not exists scope_key text" in sql
    assert "alter column portfolio_id drop not null" in sql
    assert "primary key(user_id,scope_key,dataset_type)" in sql
    assert "capability_read_models_scope_lookup_idx" in sql
    assert "drop table" not in sql and "drop column" not in sql
