from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from . import database


MIGRATION_NAMESPACE = uuid.UUID("f1048e5a-f263-4ef7-9d69-23367fb62ae9")
BACKUP_DIR = database.APP_DIR / "data" / "backups"


def stable_uuid(kind: str, legacy_id: int) -> uuid.UUID:
    return uuid.uuid5(MIGRATION_NAMESPACE, f"{kind}:{legacy_id}")


def jsonb(value: Any) -> Jsonb:
    return database._jsonb(value)


def snapshot_counts(path: Path = database.DB_PATH) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("portfolios", "profiles", "scenario_snapshots", "analysis_runs")
        }


def backup_sqlite(path: Path = database.DB_PATH) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUP_DIR / f"dashboard-pre-supabase-{stamp}.db"
    with sqlite3.connect(path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    shutil.copystat(path, destination)
    return destination


def migrate(path: Path = database.DB_PATH) -> dict[str, int]:
    if not database.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for migration")
    counts = snapshot_counts(path)
    with sqlite3.connect(path) as source:
        source.row_factory = sqlite3.Row
        portfolios = source.execute("SELECT * FROM portfolios ORDER BY id").fetchall()
        profiles = source.execute("SELECT * FROM profiles ORDER BY id").fetchall()
        scenarios = source.execute("SELECT * FROM scenario_snapshots ORDER BY id").fetchall()
        analyses = source.execute("SELECT * FROM analysis_runs ORDER BY created_at").fetchall()

    portfolio_ids = {row["id"]: stable_uuid("portfolio", row["id"]) for row in portfolios}
    primary_portfolio_id = next(iter(portfolio_ids.values()), None)
    primary_profile_id = stable_uuid("profile", profiles[0]["id"]) if profiles else None

    with database.postgres_connection() as target:
        with target.transaction():
            for row in portfolios:
                portfolio_id = portfolio_ids[row["id"]]
                target.execute(
                    """INSERT INTO public.portfolios(
                    id, name, legacy_sqlite_id, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (legacy_sqlite_id) DO UPDATE SET
                    name=excluded.name, updated_at=excluded.updated_at""",
                    (portfolio_id, row["name"], row["id"], row["created_at"], row["updated_at"]),
                )
                target.execute("DELETE FROM public.holdings WHERE portfolio_id = %s", (portfolio_id,))
                for holding in json.loads(row["holdings_json"]):
                    target.execute(
                        """INSERT INTO public.holdings(
                        portfolio_id, ticker, quantity, weight, market_value, cost_basis,
                        account_type, acquisition_date
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            portfolio_id, holding["ticker"].upper(), holding.get("shares"),
                            holding.get("weight"), holding.get("market_value"), holding.get("cost_basis"),
                            holding.get("account_type", "taxable"), holding.get("acquisition_date"),
                        ),
                    )

            for row in profiles:
                profile = json.loads(row["profile_json"])
                explanation = {
                    "llm_provider": profile.get("llm_provider", "disabled"),
                    "llm_endpoint": profile.get("llm_endpoint"),
                    "llm_model": profile.get("llm_model"),
                }
                target.execute(
                    """INSERT INTO public.investor_profiles(
                    id, portfolio_id, legacy_sqlite_id, name, age, retirement_age, horizon_years,
                    account_type, annual_contribution, annual_withdrawal, target_value, tax_rate,
                    risk_tolerance, preset, restrictions, watchlist, objective_weights,
                    explanation_settings, created_at, updated_at
                    ) VALUES (%s,%s,%s,'Primary profile',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (legacy_sqlite_id) DO UPDATE SET
                    portfolio_id=excluded.portfolio_id, age=excluded.age,
                    retirement_age=excluded.retirement_age, horizon_years=excluded.horizon_years,
                    account_type=excluded.account_type, annual_contribution=excluded.annual_contribution,
                    annual_withdrawal=excluded.annual_withdrawal, target_value=excluded.target_value,
                    tax_rate=excluded.tax_rate, risk_tolerance=excluded.risk_tolerance,
                    preset=excluded.preset, restrictions=excluded.restrictions,
                    watchlist=excluded.watchlist, objective_weights=excluded.objective_weights,
                    explanation_settings=excluded.explanation_settings, updated_at=excluded.updated_at""",
                    (
                        stable_uuid("profile", row["id"]), primary_portfolio_id, row["id"],
                        profile.get("age"), profile.get("retirement_age"), profile.get("horizon_years"),
                        profile.get("account_type", "taxable"), profile.get("annual_contribution", 0),
                        profile.get("annual_withdrawal", 0), profile.get("target_value"), profile.get("tax_rate"),
                        profile.get("risk_tolerance"), profile.get("preset", "balanced"),
                        jsonb(profile.get("restrictions", [])), profile.get("watchlist", []),
                        jsonb(profile.get("objectives", {})), jsonb(explanation),
                        row["updated_at"], row["updated_at"],
                    ),
                )

            for row in scenarios:
                snapshot_id = stable_uuid("scenario", row["id"])
                raw_scenarios = json.loads(row["scenarios_json"])
                raw_contracts = json.loads(row["contracts_json"])
                warnings = json.loads(row["warnings_json"])
                target.execute(
                    """INSERT INTO public.scenario_snapshots(
                    id, legacy_sqlite_id, observed_at, model_version, warnings, lineage,
                    raw_scenarios, raw_contracts
                    ) VALUES (%s,%s,%s,'prediction-market-v1',%s,%s,%s,%s)
                    ON CONFLICT (legacy_sqlite_id) DO UPDATE SET
                    observed_at=excluded.observed_at, warnings=excluded.warnings,
                    lineage=excluded.lineage, raw_scenarios=excluded.raw_scenarios,
                    raw_contracts=excluded.raw_contracts""",
                    (
                        snapshot_id, row["id"], row["fetched_at"], jsonb(warnings),
                        jsonb({"migrated_from": "sqlite"}), jsonb(raw_scenarios), jsonb(raw_contracts),
                    ),
                )
                target.execute("DELETE FROM public.scenario_probabilities WHERE snapshot_id = %s", (snapshot_id,))
                for scenario in raw_scenarios:
                    target.execute(
                        """INSERT INTO public.scenario_probabilities(
                        snapshot_id, scenario_key, probability, confidence, is_prior, contributors
                        ) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            snapshot_id, scenario["key"], scenario["probability"], scenario["confidence"],
                            scenario.get("is_prior", False), jsonb(scenario.get("sources", [])),
                        ),
                    )

            for row in analyses:
                request = json.loads(row["request_json"])
                result = json.loads(row["result_json"])
                requested_legacy_id = request.get("portfolio_id")
                portfolio_id = portfolio_ids.get(requested_legacy_id, primary_portfolio_id)
                target.execute(
                    """INSERT INTO public.analysis_runs(
                    id, portfolio_id, profile_id, status, model_version, config_version,
                    input_snapshot, data_lineage, current_portfolio, alternatives, warnings,
                    result_snapshot, created_at
                    ) VALUES (%s,%s,%s,'completed',%s,'v1',%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                    input_snapshot=excluded.input_snapshot, data_lineage=excluded.data_lineage,
                    current_portfolio=excluded.current_portfolio, alternatives=excluded.alternatives,
                    warnings=excluded.warnings, result_snapshot=excluded.result_snapshot""",
                    (
                        row["id"], portfolio_id, primary_profile_id,
                        result.get("model_version", "scenario-shrinkage-v1"), jsonb(request),
                        jsonb(result.get("data_lineage", {})), jsonb(result.get("current_weights", {})),
                        jsonb(result.get("alternatives", [])), jsonb(result.get("warnings", [])),
                        jsonb(result), row["created_at"],
                    ),
                )
    return counts


def verify(counts: dict[str, int]) -> None:
    with database.postgres_connection() as conn:
        actual = {
            "portfolios": conn.execute(
                "SELECT count(*) AS count FROM public.portfolios WHERE legacy_sqlite_id IS NOT NULL"
            ).fetchone()["count"],
            "profiles": conn.execute(
                "SELECT count(*) AS count FROM public.investor_profiles WHERE legacy_sqlite_id IS NOT NULL"
            ).fetchone()["count"],
            "scenario_snapshots": conn.execute(
                "SELECT count(*) AS count FROM public.scenario_snapshots WHERE legacy_sqlite_id IS NOT NULL"
            ).fetchone()["count"],
            "analysis_runs": conn.execute(
                "SELECT count(*) AS count FROM public.analysis_runs WHERE result_snapshot <> '{}'::jsonb"
            ).fetchone()["count"],
        }
    mismatches = {key: (counts[key], actual[key]) for key in counts if counts[key] != actual[key]}
    if mismatches:
        raise RuntimeError(f"Migration count mismatch: {mismatches}")
    print("Verified migrated rows: " + ", ".join(f"{key}={value}" for key, value in actual.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy InvestmentDashboard SQLite data to Supabase")
    parser.add_argument("--apply", action="store_true", help="Create a backup and perform the migration")
    args = parser.parse_args()
    counts = snapshot_counts()
    print("SQLite source rows: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if not args.apply:
        print("Dry run only. Re-run with --apply to back up and migrate these rows.")
        return 0
    backup = backup_sqlite()
    migrated = migrate()
    verify(migrated)
    print(f"SQLite backup retained at {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
