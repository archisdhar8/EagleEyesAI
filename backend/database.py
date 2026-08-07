from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


APP_DIR = Path(__file__).resolve().parents[1]
DB_PATH = APP_DIR / "data" / "dashboard.db"
ENV_PATH = APP_DIR / "backend" / ".env"
load_dotenv(ENV_PATH, override=False)
DATABASE_URL: str | None = os.getenv("DATABASE_URL") or None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def storage_mode() -> str:
    return "supabase" if DATABASE_URL else "sqlite"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, (Decimal, int, float)) else value


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda item: json.dumps(item, default=str))


@contextmanager
def sqlite_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def postgres_connection() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    with psycopg.connect(DATABASE_URL, connect_timeout=15, sslmode="require", row_factory=dict_row) as conn:
        yield conn


def initialize() -> None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            ready = conn.execute(
                "SELECT to_regclass('public.portfolios') IS NOT NULL "
                "AND to_regclass('public.analysis_runs') IS NOT NULL AS ready"
            ).fetchone()["ready"]
        if not ready:
            raise RuntimeError("Supabase schema is missing. Run: python -m backend.migrations apply")
        return

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
    with sqlite_connection() as conn:
        for statement in statements:
            conn.execute(statement)
        conn.execute("CREATE INDEX IF NOT EXISTS scenario_fetched_idx ON scenario_snapshots(fetched_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS analysis_created_idx ON analysis_runs(created_at)")


def save_portfolio(
    name: str, holdings: list[dict[str, Any]], portfolio_id: str | int | None = None
) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            if portfolio_id is None:
                portfolio_id = str(
                    conn.execute(
                        "INSERT INTO public.portfolios(name) VALUES (%s) RETURNING id", (name,)
                    ).fetchone()["id"]
                )
            else:
                updated = conn.execute(
                    "UPDATE public.portfolios SET name = %s WHERE id = %s RETURNING id",
                    (name, portfolio_id),
                ).fetchone()
                if updated is None:
                    raise KeyError(portfolio_id)
                conn.execute("DELETE FROM public.holdings WHERE portfolio_id = %s", (portfolio_id,))
            for holding in holdings:
                conn.execute(
                    """INSERT INTO public.holdings(
                        portfolio_id, ticker, quantity, weight, market_value, cost_basis,
                        account_type, acquisition_date
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        portfolio_id,
                        holding["ticker"].upper(),
                        holding.get("shares"),
                        holding.get("weight"),
                        holding.get("market_value"),
                        holding.get("cost_basis"),
                        holding.get("account_type", "taxable"),
                        holding.get("acquisition_date"),
                    ),
                )
        return get_portfolio(portfolio_id)

    now = utc_now()
    with sqlite_connection() as conn:
        if portfolio_id is None:
            cursor = conn.execute(
                "INSERT INTO portfolios(name, holdings_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, json.dumps(holdings, default=str), now, now),
            )
            portfolio_id = int(cursor.lastrowid)
        else:
            cursor = conn.execute(
                "UPDATE portfolios SET name = ?, holdings_json = ?, updated_at = ? WHERE id = ?",
                (name, json.dumps(holdings, default=str), now, portfolio_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(portfolio_id)
    return get_portfolio(portfolio_id)


def _postgres_holdings(conn: psycopg.Connection, portfolio_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT ticker, quantity, weight, market_value, cost_basis, account_type, acquisition_date
        FROM public.holdings WHERE portfolio_id = %s ORDER BY created_at, id""",
        (portfolio_id,),
    ).fetchall()
    return [
        {
            "ticker": row["ticker"],
            "shares": _number(row["quantity"]),
            "weight": _number(row["weight"]),
            "market_value": _number(row["market_value"]),
            "cost_basis": _number(row["cost_basis"]),
            "account_type": row["account_type"],
            "acquisition_date": _iso(row["acquisition_date"]),
        }
        for row in rows
    ]


def get_portfolio(portfolio_id: str | int) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT id, name, updated_at FROM public.portfolios WHERE id = %s", (portfolio_id,)
            ).fetchone()
            if row is None:
                raise KeyError(portfolio_id)
            holdings = _postgres_holdings(conn, str(row["id"]))
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "holdings": holdings,
            "updated_at": _iso(row["updated_at"]),
        }

    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
    if row is None:
        raise KeyError(portfolio_id)
    return {
        "id": row["id"],
        "name": row["name"],
        "holdings": json.loads(row["holdings_json"]),
        "updated_at": row["updated_at"],
    }


def list_portfolios() -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, updated_at FROM public.portfolios ORDER BY updated_at DESC"
            ).fetchall()
            return [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "holdings": _postgres_holdings(conn, str(row["id"])),
                    "updated_at": _iso(row["updated_at"]),
                }
                for row in rows
            ]

    with sqlite_connection() as conn:
        rows = conn.execute("SELECT * FROM portfolios ORDER BY updated_at DESC").fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "holdings": json.loads(row["holdings_json"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if DATABASE_URL:
        now = utc_now()
        explanation = {
            "llm_provider": profile.get("llm_provider", "disabled"),
            "llm_endpoint": profile.get("llm_endpoint"),
            "llm_model": profile.get("llm_model"),
        }
        with postgres_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM public.investor_profiles ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            values = (
                profile.get("age"), profile.get("retirement_age"), profile.get("horizon_years"),
                profile.get("account_type", "taxable"), profile.get("annual_contribution", 0),
                profile.get("annual_withdrawal", 0), profile.get("target_value"), profile.get("tax_rate"),
                profile.get("risk_tolerance"), profile.get("preset", "balanced"),
                _jsonb(profile.get("restrictions", [])), profile.get("watchlist", []),
                _jsonb(profile.get("objectives", {})), _jsonb(explanation),
            )
            if existing:
                conn.execute(
                    """UPDATE public.investor_profiles SET
                    age=%s, retirement_age=%s, horizon_years=%s, account_type=%s,
                    annual_contribution=%s, annual_withdrawal=%s, target_value=%s, tax_rate=%s,
                    risk_tolerance=%s, preset=%s, restrictions=%s, watchlist=%s,
                    objective_weights=%s, explanation_settings=%s WHERE id=%s""",
                    (*values, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO public.investor_profiles(
                    age, retirement_age, horizon_years, account_type, annual_contribution,
                    annual_withdrawal, target_value, tax_rate, risk_tolerance, preset,
                    restrictions, watchlist, objective_weights, explanation_settings
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    values,
                )
        return {**profile, "updated_at": now}

    now = utc_now()
    with sqlite_connection() as conn:
        conn.execute(
            "INSERT INTO profiles(id, profile_json, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET profile_json = excluded.profile_json, updated_at = excluded.updated_at",
            (json.dumps(profile, default=str), now),
        )
    return {**profile, "updated_at": now}


def load_profile() -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT * FROM public.investor_profiles ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        explanation = row["explanation_settings"] or {}
        return {
            "age": row["age"], "retirement_age": row["retirement_age"],
            "horizon_years": row["horizon_years"], "account_type": row["account_type"],
            "annual_contribution": _number(row["annual_contribution"]),
            "annual_withdrawal": _number(row["annual_withdrawal"]),
            "target_value": _number(row["target_value"]), "tax_rate": _number(row["tax_rate"]),
            "risk_tolerance": int(row["risk_tolerance"]) if row["risk_tolerance"] is not None else 6,
            "preset": row["preset"], "restrictions": row["restrictions"] or [],
            "watchlist": row["watchlist"] or [], "objectives": row["objective_weights"] or {},
            "llm_provider": explanation.get("llm_provider", "disabled"),
            "llm_endpoint": explanation.get("llm_endpoint"), "llm_model": explanation.get("llm_model"),
            "updated_at": _iso(row["updated_at"]),
        }

    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = 1").fetchone()
    return None if row is None else {**json.loads(row["profile_json"]), "updated_at": row["updated_at"]}


def save_scenario_snapshot(
    scenarios: list[dict[str, Any]], contracts: list[dict[str, Any]], warnings: list[str]
) -> str | int:
    if DATABASE_URL:
        with postgres_connection() as conn:
            snapshot_id = conn.execute(
                """INSERT INTO public.scenario_snapshots(
                model_version, warnings, lineage, raw_scenarios, raw_contracts
                ) VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (
                    "prediction-market-v1", _jsonb(warnings), _jsonb({}),
                    _jsonb(scenarios), _jsonb(contracts),
                ),
            ).fetchone()["id"]
            for scenario in scenarios:
                conn.execute(
                    """INSERT INTO public.scenario_probabilities(
                    snapshot_id, scenario_key, probability, confidence, is_prior, contributors
                    ) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        snapshot_id, scenario["key"], scenario["probability"], scenario["confidence"],
                        scenario.get("is_prior", False), _jsonb(scenario.get("sources", [])),
                    ),
                )
        return str(snapshot_id)

    with sqlite_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO scenario_snapshots(scenarios_json, contracts_json, warnings_json, fetched_at) VALUES (?, ?, ?, ?)",
            (json.dumps(scenarios, default=str), json.dumps(contracts, default=str), json.dumps(warnings), utc_now()),
        )
        return int(cursor.lastrowid)


def latest_scenario_snapshot() -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """SELECT raw_scenarios, raw_contracts, warnings, observed_at
                FROM public.scenario_snapshots ORDER BY observed_at DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        return {
            "scenarios": row["raw_scenarios"], "contracts": row["raw_contracts"],
            "warnings": row["warnings"], "fetched_at": _iso(row["observed_at"]),
        }

    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM scenario_snapshots ORDER BY fetched_at DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {
        "scenarios": json.loads(row["scenarios_json"]), "contracts": json.loads(row["contracts_json"]),
        "warnings": json.loads(row["warnings_json"]), "fetched_at": row["fetched_at"],
    }


def scenario_history() -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                """SELECT raw_scenarios, observed_at FROM public.scenario_snapshots
                ORDER BY observed_at DESC LIMIT 800"""
            ).fetchall()
        return [{"scenarios": row["raw_scenarios"], "fetched_at": _iso(row["observed_at"])} for row in rows]

    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT scenarios_json, fetched_at FROM scenario_snapshots ORDER BY fetched_at DESC LIMIT 800"
        ).fetchall()
    return [{"scenarios": json.loads(row["scenarios_json"]), "fetched_at": row["fetched_at"]} for row in rows]


def save_analysis(run_id: str, request: dict[str, Any], result: dict[str, Any]) -> None:
    if DATABASE_URL:
        portfolio_id = request.get("portfolio_id")
        with postgres_connection() as conn:
            profile = conn.execute(
                "SELECT id FROM public.investor_profiles ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            conn.execute(
                """INSERT INTO public.analysis_runs(
                id, portfolio_id, profile_id, status, model_version, config_version,
                input_snapshot, data_lineage, current_portfolio, alternatives, warnings,
                result_snapshot, created_at
                ) VALUES (%s,%s,%s,'completed',%s,'v1',%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET result_snapshot=excluded.result_snapshot""",
                (
                    run_id, portfolio_id, profile["id"] if profile else None,
                    result.get("model_version", "scenario-shrinkage-v1"), _jsonb(request),
                    _jsonb(result.get("data_lineage", {})), _jsonb(result.get("current_weights", {})),
                    _jsonb(result.get("alternatives", [])), _jsonb(result.get("warnings", [])),
                    _jsonb(result), result.get("created_at", utc_now()),
                ),
            )
        return

    with sqlite_connection() as conn:
        conn.execute(
            "INSERT INTO analysis_runs(id, request_json, result_json, created_at) VALUES (?, ?, ?, ?)",
            (run_id, json.dumps(request, default=str), json.dumps(result, default=str), utc_now()),
        )


def load_analysis(run_id: str) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT result_snapshot FROM public.analysis_runs WHERE id = %s", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row["result_snapshot"]

    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    return json.loads(row["result_json"])


def latest_analysis() -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """SELECT result_snapshot FROM public.analysis_runs
                WHERE status = 'completed' ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        return None if row is None else row["result_snapshot"]

    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT result_json FROM analysis_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return None if row is None else json.loads(row["result_json"])


def provider_data_status() -> dict[str, Any]:
    if not DATABASE_URL:
        return {"storage": "sqlite", "counts": {}, "freshness": {}, "providers": []}
    with postgres_connection() as conn:
        counts = conn.execute(
            """SELECT
            (SELECT count(*) FROM public.price_bars) AS price_bars,
            (SELECT count(*) FROM public.macro_observations) AS macro_observations,
            (SELECT count(*) FROM public.fundamental_periods) AS fundamental_periods,
            (SELECT count(*) FROM public.documents WHERE document_type='news') AS news_documents,
            (SELECT count(*) FROM public.prediction_market_snapshots) AS market_snapshots"""
        ).fetchone()
        freshness = conn.execute(
            """SELECT
            (SELECT max(ts) FROM public.price_bars) AS prices,
            (SELECT max(observation_date) FROM public.macro_observations) AS macro,
            (SELECT max(period_end) FROM public.fundamental_periods) AS fundamentals,
            (SELECT max(published_at) FROM public.documents WHERE document_type='news') AS news,
            (SELECT max(observed_at) FROM public.prediction_market_snapshots) AS markets"""
        ).fetchone()
        providers = conn.execute(
            """SELECT DISTINCT ON (provider) provider, status, fetched_at, as_of,
            metadata, error_message FROM public.provider_fetches
            ORDER BY provider, fetched_at DESC"""
        ).fetchall()
    return {
        "storage": "supabase",
        "counts": {key: int(value or 0) for key, value in counts.items()},
        "freshness": {key: _iso(value) for key, value in freshness.items()},
        "providers": [
            {
                "provider": row["provider"], "status": row["status"],
                "fetched_at": _iso(row["fetched_at"]), "as_of": _iso(row["as_of"]),
                "metadata": row["metadata"] or {}, "error": row["error_message"],
            }
            for row in providers
        ],
    }


def macro_observation_history(series_ids: list[str], limit_per_series: int = 18) -> list[dict[str, Any]]:
    if not DATABASE_URL or not series_ids:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT series_id, observation_date, vintage_date, value, provider, source_url
            FROM (
              SELECT series_id, observation_date, vintage_date, value, provider, source_url,
              row_number() OVER (
                PARTITION BY series_id ORDER BY observation_date DESC, vintage_date DESC,
                CASE WHEN provider='FRED' THEN 0 ELSE 1 END
              ) AS position
              FROM public.macro_observations WHERE series_id = ANY(%s)
            ) observations WHERE position <= %s
            ORDER BY series_id, observation_date DESC, vintage_date DESC""",
            (series_ids, limit_per_series),
        ).fetchall()
    return [
        {
            "series_id": row["series_id"], "date": _iso(row["observation_date"]),
            "vintage_date": _iso(row["vintage_date"]), "value": _number(row["value"]),
            "provider": row["provider"], "source_url": row["source_url"],
        }
        for row in rows
    ]


def security_data(tickers: list[str], price_limit: int = 756) -> dict[str, Any]:
    normalized = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip() and ticker.upper() != "CASH"})
    if not DATABASE_URL or not normalized:
        return {"securities": [], "fundamentals": [], "prices": [], "news": []}
    with postgres_connection() as conn:
        securities = conn.execute(
            """SELECT id, ticker, asset_type, company_name, sector, industry, updated_at
            FROM public.securities WHERE ticker = ANY(%s) AND active=true""",
            (normalized,),
        ).fetchall()
        fundamentals = conn.execute(
            """SELECT ticker, period_end, fiscal_period, fiscal_year, metrics,
            data_quality_score, source_url, fetched_at FROM (
              SELECT s.ticker, f.period_end, f.fiscal_period, f.fiscal_year, f.metrics,
              f.data_quality_score, f.source_url, f.fetched_at,
              row_number() OVER (PARTITION BY s.ticker ORDER BY f.period_end DESC, f.fetched_at DESC) AS position
              FROM public.fundamental_periods f JOIN public.securities s ON s.id=f.security_id
              WHERE s.ticker = ANY(%s)
            ) periods WHERE position <= 8 ORDER BY ticker, period_end DESC""",
            (normalized,),
        ).fetchall()
        prices = conn.execute(
            """SELECT ticker, ts, close, volume, fetched_at FROM (
              SELECT s.ticker, p.ts, p.close, p.volume, p.fetched_at,
              row_number() OVER (PARTITION BY s.ticker ORDER BY p.ts DESC) AS position
              FROM public.price_bars p JOIN public.securities s ON s.id=p.security_id
              WHERE s.ticker = ANY(%s) AND p.interval='1d'
            ) bars WHERE position <= %s ORDER BY ticker, ts""",
            (normalized, price_limit),
        ).fetchall()
        news = conn.execute(
            """SELECT ticker, title, source_url, published_at, metadata, fetched_at FROM (
              SELECT s.ticker, d.title, d.source_url, d.published_at, d.metadata, d.fetched_at,
              row_number() OVER (PARTITION BY s.ticker ORDER BY d.published_at DESC NULLS LAST) AS position
              FROM public.document_securities ds
              JOIN public.securities s ON s.id=ds.security_id
              JOIN public.documents d ON d.id=ds.document_id
              WHERE s.ticker = ANY(%s) AND d.document_type='news'
            ) items WHERE position <= 25 ORDER BY ticker, published_at DESC NULLS LAST""",
            (normalized,),
        ).fetchall()
    return {
        "securities": [
            {**dict(row), "id": str(row["id"]), "updated_at": _iso(row["updated_at"])}
            for row in securities
        ],
        "fundamentals": [
            {
                **dict(row), "period_end": _iso(row["period_end"]),
                "fetched_at": _iso(row["fetched_at"]),
                "data_quality_score": _number(row["data_quality_score"]),
            }
            for row in fundamentals
        ],
        "prices": [
            {
                "ticker": row["ticker"], "date": _iso(row["ts"]),
                "close": _number(row["close"]), "volume": _number(row["volume"]),
                "fetched_at": _iso(row["fetched_at"]),
            }
            for row in prices
        ],
        "news": [
            {
                **dict(row), "published_at": _iso(row["published_at"]),
                "fetched_at": _iso(row["fetched_at"]),
            }
            for row in news
        ],
    }
