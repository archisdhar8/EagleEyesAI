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
