from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = APP_DIR / "backend" / ".env"
MIGRATIONS_DIR = APP_DIR / "supabase" / "migrations"
EXPECTED_TABLES = {
    "analysis_runs",
    "chat_conversations",
    "chat_message_evidence",
    "chat_messages",
    "chat_artifact_links",
    "document_chunks",
    "dashboard_preferences",
    "dashboard_jobs",
    "dashboard_job_tasks",
    "dashboard_views",
    "dashboard_view_runs",
    "dashboard_view_revisions",
    "dashboard_widget_cache",
    "document_securities",
    "documents",
    "fundamental_periods",
    "fundamental_observations",
    "financial_goals",
    "fund_holdings",
    "fund_reference_data",
    "etf_catalog",
    "etf_exposures",
    "etf_refresh_runs",
    "goal_account_allocations",
    "holdings",
    "investor_profiles",
    "investment_policies",
    "investment_theses",
    "thesis_assumptions",
    "thesis_factors",
    "thesis_versions",
    "investment_decisions",
    "decision_context_snapshots",
    "decision_retrospectives",
    "learning_preferences",
    "learning_progress",
    "learning_quiz_attempts",
    "learning_tutor_threads",
    "learning_tutor_messages",
    "simulation_runs",
    "allocation_builder_runs",
    "model_portfolios",
    "market_events",
    "market_observations",
    "security_master",
    "security_coverage_snapshots",
    "investment_accounts",
    "portfolio_transactions",
    "account_valuations",
    "security_lots",
    "corporate_actions",
    "income_events",
    "statement_reconciliations",
    "portfolio_performance_runs",
    "macro_observations",
    "macro_regime_labels",
    "model_monitoring_runs",
    "model_promotion_decisions",
    "model_versions",
    "portfolios",
    "prediction_market_snapshots",
    "prediction_market_calibration_runs",
    "prediction_markets",
    "prediction_contract_series",
    "price_bars",
    "provider_fetches",
    "scenario_probabilities",
    "scenario_snapshots",
    "securities",
    "security_research_snapshots",
    "security_memberships",
    "terminal_layouts",
    "briefing_snapshots",
    "user_attention_dismissals",
    "attention_item_states",
    "alert_preferences",
    "alert_events",
    "decision_preferences",
    "validation_folds",
    "validation_runs",
}


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def migration_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def database_url() -> str:
    load_dotenv(ENV_PATH, override=False)
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError(f"DATABASE_URL is missing from {ENV_PATH}")
    return value


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), connect_timeout=15, sslmode="require")


def ensure_migration_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS public.app_schema_migrations (
            version text PRIMARY KEY,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )"""
    )


def check_connection() -> None:
    with connect() as conn:
        database, user, version = conn.execute(
            "SELECT current_database(), current_user, current_setting('server_version')"
        ).fetchone()
    print(f"Connected to database={database} user={user} postgres={version}")


def show_status() -> None:
    with connect() as conn:
        exists = conn.execute(
            "SELECT to_regclass('public.app_schema_migrations') IS NOT NULL"
        ).fetchone()[0]
        applied = {}
        if exists:
            applied = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT version, checksum FROM public.app_schema_migrations ORDER BY version"
                ).fetchall()
            }
    for path in migration_files():
        checksum = migration_checksum(path)
        state = "applied" if applied.get(path.name) == checksum else "pending"
        if path.name in applied and applied[path.name] != checksum:
            state = "checksum-mismatch"
        print(f"{state:17} {path.name}")


def validate_migrations() -> None:
    files = migration_files()
    if not files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")
    with connect() as conn:
        try:
            exists = conn.execute(
                "SELECT to_regclass('public.app_schema_migrations') IS NOT NULL"
            ).fetchone()[0]
            applied = {}
            if exists:
                applied = {
                    row[0]: row[1]
                    for row in conn.execute(
                        "SELECT version, checksum FROM public.app_schema_migrations"
                    ).fetchall()
                }
            validated = 0
            for path in files:
                checksum = migration_checksum(path)
                if path.name in applied:
                    if applied[path.name] != checksum:
                        raise RuntimeError(f"Applied migration changed: {path.name}")
                    continue
                conn.execute(path.read_text(encoding="utf-8"), prepare=False)
                print(f"Validated {path.name}")
                validated += 1
        finally:
            conn.rollback()
    if validated:
        print("Validation rolled back; the remote schema was not changed.")
    else:
        print("No pending migrations to validate.")


def verify_schema() -> None:
    files = migration_files()
    with connect() as conn:
        table_rows = conn.execute(
            "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        table_security = {row[0]: row[1] for row in table_rows}
        missing = EXPECTED_TABLES - table_security.keys()
        rls_disabled = {name for name in EXPECTED_TABLES if not table_security.get(name, False)}
        extensions = {
            row[0]
            for row in conn.execute(
                "SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto', 'vector')"
            ).fetchall()
        }
        anon_readable = {
            name
            for name in EXPECTED_TABLES
            if conn.execute(
                "SELECT has_table_privilege('anon', %s, 'SELECT')", (f"public.{name}",)
            ).fetchone()[0]
        }
        applied = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT version, checksum FROM public.app_schema_migrations"
            ).fetchall()
        }

    problems: list[str] = []
    if missing:
        problems.append(f"missing tables: {', '.join(sorted(missing))}")
    if rls_disabled:
        problems.append(f"RLS disabled: {', '.join(sorted(rls_disabled))}")
    missing_extensions = {"pgcrypto", "vector"} - extensions
    if missing_extensions:
        problems.append(f"missing extensions: {', '.join(sorted(missing_extensions))}")
    if anon_readable:
        problems.append(f"anonymous reads allowed: {', '.join(sorted(anon_readable))}")
    for path in files:
        if applied.get(path.name) != migration_checksum(path):
            problems.append(f"migration checksum mismatch: {path.name}")
    if problems:
        raise RuntimeError("; ".join(problems))
    print(
        f"Verified tables={len(EXPECTED_TABLES)} extensions=pgcrypto,vector "
        f"rls=enabled anon_reads=blocked migrations={len(files)}"
    )


def apply_migrations() -> None:
    files = migration_files()
    if not files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    with connect() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('investment_dashboard_migrations'))")
            ensure_migration_table(conn)
            applied = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT version, checksum FROM public.app_schema_migrations"
                ).fetchall()
            }
            pending = 0
            for path in files:
                checksum = migration_checksum(path)
                if path.name in applied:
                    if applied[path.name] != checksum:
                        raise RuntimeError(
                            f"Applied migration changed: {path.name}. Create a new migration instead."
                        )
                    continue
                conn.execute(path.read_text(encoding="utf-8"), prepare=False)
                conn.execute(
                    "INSERT INTO public.app_schema_migrations(version, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
                pending += 1
                print(f"Applied {path.name}")
    if pending == 0:
        print("Database schema is already current.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage InvestmentDashboard Supabase migrations")
    parser.add_argument("command", choices=["check", "validate", "status", "apply", "verify"])
    args = parser.parse_args()
    if args.command == "check":
        check_connection()
    elif args.command == "validate":
        validate_migrations()
    elif args.command == "status":
        show_status()
    elif args.command == "verify":
        verify_schema()
    else:
        apply_migrations()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
