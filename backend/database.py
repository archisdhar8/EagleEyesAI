from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


APP_DIR = Path(__file__).resolve().parents[1]
DB_PATH = APP_DIR / "data" / "dashboard.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize() -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            holdings_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            profile_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS scenario_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenarios_json TEXT NOT NULL,
            contracts_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS analysis_runs (
            id TEXT PRIMARY KEY,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
    ]
    with connection() as conn:
        for statement in statements:
            conn.execute(statement)
        conn.execute("CREATE INDEX IF NOT EXISTS scenario_fetched_idx ON scenario_snapshots(fetched_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS analysis_created_idx ON analysis_runs(created_at)")


def save_portfolio(name: str, holdings: list[dict[str, Any]], portfolio_id: int | None = None) -> dict[str, Any]:
    now = utc_now()
    with connection() as conn:
        if portfolio_id is None:
            cursor = conn.execute(
                "INSERT INTO portfolios(name, holdings_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, json.dumps(holdings), now, now),
            )
            portfolio_id = int(cursor.lastrowid)
        else:
            conn.execute(
                "UPDATE portfolios SET name = ?, holdings_json = ?, updated_at = ? WHERE id = ?",
                (name, json.dumps(holdings), now, portfolio_id),
            )
    return get_portfolio(portfolio_id)


def get_portfolio(portfolio_id: int) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
    if row is None:
        raise KeyError(portfolio_id)
    return {"id": row["id"], "name": row["name"], "holdings": json.loads(row["holdings_json"]), "updated_at": row["updated_at"]}


def list_portfolios() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM portfolios ORDER BY updated_at DESC").fetchall()
    return [{"id": row["id"], "name": row["name"], "holdings": json.loads(row["holdings_json"]), "updated_at": row["updated_at"]} for row in rows]


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO profiles(id, profile_json, updated_at) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET profile_json = excluded.profile_json, updated_at = excluded.updated_at",
            (json.dumps(profile), now),
        )
    return {**profile, "updated_at": now}


def load_profile() -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = 1").fetchone()
    return None if row is None else {**json.loads(row["profile_json"]), "updated_at": row["updated_at"]}


def save_scenario_snapshot(scenarios: list[dict[str, Any]], contracts: list[dict[str, Any]], warnings: list[str]) -> int:
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO scenario_snapshots(scenarios_json, contracts_json, warnings_json, fetched_at) VALUES (?, ?, ?, ?)",
            (json.dumps(scenarios), json.dumps(contracts), json.dumps(warnings), utc_now()),
        )
        return int(cursor.lastrowid)


def latest_scenario_snapshot() -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM scenario_snapshots ORDER BY fetched_at DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"scenarios": json.loads(row["scenarios_json"]), "contracts": json.loads(row["contracts_json"]), "warnings": json.loads(row["warnings_json"]), "fetched_at": row["fetched_at"]}


def scenario_history() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT scenarios_json, fetched_at FROM scenario_snapshots ORDER BY fetched_at DESC LIMIT 800").fetchall()
    return [{"scenarios": json.loads(row["scenarios_json"]), "fetched_at": row["fetched_at"]} for row in rows]


def save_analysis(run_id: str, request: dict[str, Any], result: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO analysis_runs(id, request_json, result_json, created_at) VALUES (?, ?, ?, ?)",
            (run_id, json.dumps(request), json.dumps(result), utc_now()),
        )


def load_analysis(run_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    return json.loads(row["result_json"])
