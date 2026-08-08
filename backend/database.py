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
                    result.get("model_version", "walk-forward-regime-shrinkage-v2"), _jsonb(request),
                    _jsonb(result.get("data_lineage", {})), _jsonb(result.get("current_weights", {})),
                    _jsonb(result.get("alternatives", [])), _jsonb(result.get("warnings", [])),
                    _jsonb(result), result.get("created_at", utc_now()),
                ),
            )
            _save_validation_artifacts(conn, run_id, result)
        return

    with sqlite_connection() as conn:
        conn.execute(
            "INSERT INTO analysis_runs(id, request_json, result_json, created_at) VALUES (?, ?, ?, ?)",
            (run_id, json.dumps(request, default=str), json.dumps(result, default=str), utc_now()),
        )


def _upsert_model_version(
    conn: psycopg.Connection, *, model_key: str, version: str, model_type: str,
    status: str, configuration: dict[str, Any], assumptions: list[str],
) -> str:
    row = conn.execute(
        """INSERT INTO public.model_versions(
        model_key, version, model_type, status, configuration, assumptions
        ) VALUES (%s,%s,%s,'evaluation',%s,%s)
        ON CONFLICT (model_key, version) DO UPDATE SET
        configuration=excluded.configuration,
        assumptions=excluded.assumptions
        RETURNING id, status""",
        (
            model_key, version, model_type, _jsonb(configuration), _jsonb(assumptions),
        ),
    ).fetchone()
    if status == "production" and row["status"] != "production":
        existing = conn.execute(
            """SELECT id FROM public.model_promotion_decisions
            WHERE model_version_id=%s AND decision='promote'
              AND requested_status='production' LIMIT 1""",
            (row["id"],),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO public.model_promotion_decisions(
                model_version_id, decision, previous_status, requested_status,
                rationale, gates, evidence, decided_by
                ) VALUES (%s,'promote','evaluation','production',%s,%s,%s,%s)""",
                (
                    row["id"],
                    "Transparent baseline approved under the recorded baseline policy; challengers remain evaluation-only.",
                    _jsonb({"transparent": True, "automatic_challenger_promotion": False}),
                    _jsonb({"model_key": model_key, "version": version}),
                    "baseline-policy",
                ),
            )
        conn.execute(
            "UPDATE public.model_versions SET status='production' WHERE id=%s",
            (row["id"],),
        )
    return str(row["id"])


def _upsert_validation_run(
    conn: psycopg.Connection, *, analysis_run_id: str, model_version_id: str,
    validation_type: str, status: str, data_cutoff: str | None,
    configuration: dict[str, Any], aggregate_metrics: dict[str, Any],
    benchmarks: list[dict[str, Any]], recommendation: str | None,
    assumptions: list[str], folds: list[dict[str, Any]],
) -> str:
    row = conn.execute(
        """INSERT INTO public.validation_runs(
        analysis_run_id, model_version_id, validation_type, status, data_cutoff,
        configuration, aggregate_metrics, benchmark_comparisons, recommendation, assumptions
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (analysis_run_id, model_version_id, validation_type) DO UPDATE SET
        status=excluded.status, data_cutoff=excluded.data_cutoff,
        configuration=excluded.configuration, aggregate_metrics=excluded.aggregate_metrics,
        benchmark_comparisons=excluded.benchmark_comparisons,
        recommendation=excluded.recommendation, assumptions=excluded.assumptions
        RETURNING id""",
        (
            analysis_run_id, model_version_id, validation_type, status, data_cutoff,
            _jsonb(configuration), _jsonb(aggregate_metrics), _jsonb(benchmarks),
            recommendation, _jsonb(assumptions),
        ),
    ).fetchone()
    validation_run_id = str(row["id"])
    conn.execute(
        "DELETE FROM public.validation_folds WHERE validation_run_id=%s",
        (validation_run_id,),
    )
    for index, fold in enumerate(folds):
        conn.execute(
            """INSERT INTO public.validation_folds(
            validation_run_id, fold_index, train_start, train_end, test_start,
            test_end, data_cutoff, sample_counts, metrics, benchmark_metrics,
            diagnostics, leakage_check
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                validation_run_id, int(fold.get("fold_index", index)),
                fold.get("train_start"), fold["train_end"], fold["test_start"],
                fold["test_end"], fold.get("data_cutoff") or fold["train_end"],
                _jsonb(fold.get("sample_counts", {})), _jsonb(fold.get("metrics", {})),
                _jsonb(fold.get("benchmark_metrics", {})),
                _jsonb(fold.get("diagnostics", {})), bool(fold.get("leakage_check", False)),
            ),
        )
    return validation_run_id


def _save_validation_artifacts(
    conn: psycopg.Connection, analysis_run_id: str, result: dict[str, Any]
) -> None:
    walk = result.get("walk_forward") or {}
    model_diagnostics = result.get("model_diagnostics") or {}
    optimizer_assumptions = next(
        (
            item.get("model_assumptions", []) for item in result.get("alternatives", [])
            if item.get("name") == "Balanced"
        ),
        walk.get("assumptions", []),
    )
    optimizer_id = _upsert_model_version(
        conn, model_key="portfolio_optimizer",
        version=result.get("model_version", "walk-forward-regime-shrinkage-v2"),
        model_type="optimizer", status="production",
        configuration=model_diagnostics, assumptions=optimizer_assumptions,
    )
    _upsert_model_version(
        conn, model_key="macro_regime_rules", version="macro-regime-rules-v1",
        model_type="regime_rules", status="production",
        configuration={"states": 5, "point_in_time": True},
        assumptions=["Transparent rules use only macro observations available by each month-end cutoff."],
    )
    walk_folds = [
        {
            "fold_index": index, "train_end": fold["train_end"],
            "test_start": fold["test_start"], "test_end": fold["test_end"],
            "data_cutoff": fold["train_end"],
            "sample_counts": {
                "eligible_assets": fold.get("eligible_assets"),
                "regime_training_months": fold.get("regime_training_months"),
            },
            "metrics": {
                "model_return": fold.get("model_return"), "turnover": fold.get("turnover"),
            },
            "benchmark_metrics": {
                "equal_weight_return": fold.get("equal_weight_return"),
                "static_return": fold.get("static_return"),
            },
            "diagnostics": {"validation_method": "quarterly expanding-window walk-forward"},
            "leakage_check": fold["train_end"] < fold["test_start"],
        }
        for index, fold in enumerate(walk.get("periods", []))
    ]
    _upsert_validation_run(
        conn, analysis_run_id=analysis_run_id, model_version_id=optimizer_id,
        validation_type="portfolio_walk_forward", status=walk.get("status", "failed"),
        data_cutoff=(walk.get("periods") or [{}])[-1].get("test_end"),
        configuration={"period_count": walk.get("period_count", 0)},
        aggregate_metrics=walk.get("model", {}), benchmarks=walk.get("benchmarks", []),
        recommendation=None, assumptions=walk.get("assumptions", []), folds=walk_folds,
    )

    evaluation = result.get("ml_regime_evaluation") or {}
    classifier_id = _upsert_model_version(
        conn, model_key="regime_classifier",
        version=evaluation.get("model_version", "multinomial-logit-regime-v1"),
        model_type="regime_classifier", status="evaluation",
        configuration=evaluation.get("configuration", {}),
        assumptions=evaluation.get("assumptions", []),
    )
    classifier_folds = [
        {
            **fold,
            "sample_counts": {
                "train_samples": fold.get("train_samples"),
                "test_samples": fold.get("test_samples"),
            },
            "metrics": fold.get("ml_metrics", {}),
            "benchmark_metrics": fold.get("baseline_metrics", {}),
        }
        for fold in evaluation.get("folds", [])
    ]
    _upsert_validation_run(
        conn, analysis_run_id=analysis_run_id, model_version_id=classifier_id,
        validation_type="regime_classification",
        status=evaluation.get("status", "failed"),
        data_cutoff=(evaluation.get("folds") or [{}])[-1].get("test_end"),
        configuration=evaluation.get("configuration", {}),
        aggregate_metrics={
            "ml_classifier": evaluation.get("ml_classifier", {}),
            "transparent_baseline": evaluation.get("transparent_baseline", {}),
            "comparison": evaluation.get("comparison", {}),
        },
        benchmarks=[{"name": "Transparent rules", **evaluation.get("transparent_baseline", {})}],
        recommendation=evaluation.get("recommendation"),
        assumptions=evaluation.get("assumptions", []), folds=classifier_folds,
    )


def validation_history(limit: int = 20) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    with postgres_connection() as conn:
        runs = conn.execute(
            """SELECT vr.id, vr.analysis_run_id, vr.validation_type, vr.status,
            vr.data_cutoff, vr.aggregate_metrics, vr.benchmark_comparisons,
            vr.recommendation, vr.assumptions, vr.created_at,
            mv.model_key, mv.version, mv.model_type, mv.status AS model_status
            FROM public.validation_runs vr
            JOIN public.model_versions mv ON mv.id=vr.model_version_id
            ORDER BY vr.created_at DESC LIMIT %s""",
            (max(1, min(limit, 100)),),
        ).fetchall()
        run_ids = [row["id"] for row in runs]
        folds = conn.execute(
            """SELECT validation_run_id, fold_index, train_start, train_end,
            test_start, test_end, data_cutoff, sample_counts, metrics,
            benchmark_metrics, diagnostics, leakage_check
            FROM public.validation_folds WHERE validation_run_id = ANY(%s)
            ORDER BY validation_run_id, fold_index""",
            (run_ids,),
        ).fetchall() if run_ids else []
    by_run: dict[str, list[dict[str, Any]]] = {}
    for fold in folds:
        item = dict(fold)
        run_key = str(item.pop("validation_run_id"))
        for key in ("train_start", "train_end", "test_start", "test_end", "data_cutoff"):
            item[key] = _iso(item[key])
        by_run.setdefault(run_key, []).append(item)
    return [
        {
            **dict(row), "id": str(row["id"]),
            "analysis_run_id": str(row["analysis_run_id"]) if row["analysis_run_id"] else None,
            "data_cutoff": _iso(row["data_cutoff"]), "created_at": _iso(row["created_at"]),
            "folds": by_run.get(str(row["id"]), []),
        }
        for row in runs
    ]


def prediction_calibration_inputs() -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """WITH monthly AS (
              SELECT ss.id, ss.observed_at,
              row_number() OVER (
                PARTITION BY date_trunc('month', ss.observed_at)
                ORDER BY ss.observed_at DESC
              ) AS position
              FROM public.scenario_snapshots ss
              WHERE EXISTS (
                SELECT 1 FROM public.scenario_probabilities sp
                WHERE sp.snapshot_id=ss.id AND sp.is_prior=false
              )
            )
            SELECT m.id AS snapshot_id, m.observed_at, sp.scenario_key,
            sp.probability, sp.is_prior, realized.as_of_date AS realized_at,
            realized.dominant_regime
            FROM monthly m
            JOIN public.scenario_probabilities sp ON sp.snapshot_id=m.id
            JOIN LATERAL (
              SELECT as_of_date, dominant_regime
              FROM public.macro_regime_labels
              WHERE as_of_date > (date_trunc('month', m.observed_at) + interval '1 month - 1 day')::date
              ORDER BY as_of_date LIMIT 1
            ) realized ON true
            WHERE m.position=1
            ORDER BY m.observed_at, sp.scenario_key"""
        ).fetchall()
    return [
        {
            **dict(row), "snapshot_id": str(row["snapshot_id"]),
            "observed_at": _iso(row["observed_at"]),
            "realized_at": _iso(row["realized_at"]),
            "probability": _number(row["probability"]),
        }
        for row in rows
    ]


def save_prediction_calibration(result: dict[str, Any]) -> str | None:
    if not DATABASE_URL:
        return None
    with postgres_connection() as conn:
        row = conn.execute(
            """INSERT INTO public.prediction_market_calibration_runs(
            model_version, horizon_months, data_cutoff, sample_count,
            genuine_market_sample_count, brier_score, calibration_error,
            status, metrics, assumptions
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                result.get("model_version", "prediction-market-v1"),
                result.get("horizon_months", 1), result["data_cutoff"],
                result.get("sample_count", 0), result.get("genuine_market_sample_count", 0),
                result.get("brier_score"), result.get("calibration_error"),
                result.get("status", "failed"), _jsonb(result.get("metrics", {})),
                _jsonb(result.get("assumptions", [])),
            ),
        ).fetchone()
    return str(row["id"])


def latest_monitoring_run() -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    with postgres_connection() as conn:
        row = conn.execute(
            """SELECT mmr.*, mv.model_key, mv.version,
            pmc.status AS calibration_status, pmc.sample_count AS calibration_samples,
            pmc.brier_score, pmc.calibration_error
            FROM public.model_monitoring_runs mmr
            JOIN public.model_versions mv ON mv.id=mmr.model_version_id
            LEFT JOIN public.prediction_market_calibration_runs pmc
              ON pmc.id=mmr.market_calibration_run_id
            ORDER BY mmr.created_at DESC LIMIT 1"""
        ).fetchone()
    if row is None:
        return None
    return {
        **dict(row), "id": str(row["id"]),
        "model_version_id": str(row["model_version_id"]),
        "analysis_run_id": str(row["analysis_run_id"]) if row["analysis_run_id"] else None,
        "market_calibration_run_id": str(row["market_calibration_run_id"]) if row["market_calibration_run_id"] else None,
        "data_cutoff": _iso(row["data_cutoff"]), "created_at": _iso(row["created_at"]),
    }


def save_monitoring_run(
    *, analysis_run_id: str, calibration_run_id: str | None, status: str,
    data_cutoff: str, metrics: dict[str, Any], alerts: list[str],
    freshness: dict[str, Any], coverage: dict[str, Any],
) -> str:
    if not DATABASE_URL:
        raise RuntimeError("Supabase is required for model monitoring")
    with postgres_connection() as conn:
        model = conn.execute(
            """SELECT id FROM public.model_versions
            WHERE model_key='portfolio_optimizer' AND status='production'
            ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        if model is None:
            raise RuntimeError("No recorded production optimizer version is available")
        row = conn.execute(
            """INSERT INTO public.model_monitoring_runs(
            model_version_id, analysis_run_id, status, data_cutoff,
            market_calibration_run_id, metrics, alerts, data_freshness, coverage
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                model["id"], analysis_run_id, status, data_cutoff,
                calibration_run_id, _jsonb(metrics), _jsonb(alerts),
                _jsonb(freshness), _jsonb(coverage),
            ),
        ).fetchone()
    return str(row["id"])


def promotion_decisions(limit: int = 20) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT d.*, mv.model_key, mv.version
            FROM public.model_promotion_decisions d
            JOIN public.model_versions mv ON mv.id=d.model_version_id
            ORDER BY d.decided_at DESC LIMIT %s""",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [
        {
            **dict(row), "id": str(row["id"]),
            "model_version_id": str(row["model_version_id"]),
            "decided_at": _iso(row["decided_at"]),
        }
        for row in rows
    ]


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
            (SELECT count(*) FROM public.prediction_market_snapshots) AS market_snapshots,
            (SELECT count(*) FROM public.macro_regime_labels) AS macro_regimes"""
        ).fetchone()
        freshness = conn.execute(
            """SELECT
            (SELECT max(ts) FROM public.price_bars) AS prices,
            (SELECT max(observation_date) FROM public.macro_observations) AS macro,
            (SELECT max(period_end) FROM public.fundamental_periods) AS fundamentals,
            (SELECT max(published_at) FROM public.documents WHERE document_type='news') AS news,
            (SELECT max(observed_at) FROM public.prediction_market_snapshots) AS markets,
            (SELECT max(as_of_date) FROM public.macro_regime_labels) AS regimes"""
        ).fetchone()
        providers = conn.execute(
            """SELECT DISTINCT ON (provider) provider, status, fetched_at, as_of,
            metadata, error_message FROM public.provider_fetches
            ORDER BY provider, fetched_at DESC"""
        ).fetchall()
        price_coverage = conn.execute(
            """SELECT p.provider, count(*) AS bars, count(DISTINCT p.security_id) AS symbols,
            min(p.ts) AS earliest, max(p.ts) AS latest
            FROM public.price_bars p GROUP BY p.provider ORDER BY p.provider"""
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
        "price_coverage": [
            {
                "provider": row["provider"], "bars": int(row["bars"] or 0),
                "symbols": int(row["symbols"] or 0), "earliest": _iso(row["earliest"]),
                "latest": _iso(row["latest"]),
            }
            for row in price_coverage
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


def price_history(tickers: list[str], limit_per_ticker: int = 5000) -> list[dict[str, Any]]:
    normalized = sorted({
        ticker.strip().upper() for ticker in tickers
        if ticker.strip() and ticker.upper() != "CASH"
    })
    if not DATABASE_URL or not normalized:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """WITH provider_stats AS (
              SELECT s.ticker, p.provider, count(*) AS samples,
              min(p.ts) AS first_bar, max(p.ts) AS last_bar
              FROM public.price_bars p JOIN public.securities s ON s.id=p.security_id
              WHERE s.ticker = ANY(%s) AND p.interval='1d'
                AND coalesce(p.adjusted_close, p.close) IS NOT NULL
              GROUP BY s.ticker, p.provider
            ), selected_provider AS (
              SELECT ticker, provider FROM (
                SELECT ticker, provider,
                row_number() OVER (
                  PARTITION BY ticker
                  ORDER BY (last_bar-first_bar) DESC, samples DESC,
                    CASE WHEN provider='tiingo' THEN 0 ELSE 1 END
                ) AS priority
                FROM provider_stats
              ) ranked WHERE priority=1
            )
            SELECT ticker, provider, ts, close FROM (
              SELECT s.ticker, p.provider, p.ts,
              coalesce(p.adjusted_close, p.close) AS close,
              row_number() OVER (PARTITION BY s.ticker ORDER BY p.ts DESC) AS position
              FROM public.price_bars p JOIN public.securities s ON s.id=p.security_id
              JOIN selected_provider chosen
                ON chosen.ticker=s.ticker AND chosen.provider=p.provider
              WHERE s.ticker = ANY(%s) AND p.interval='1d'
                AND coalesce(p.adjusted_close, p.close) IS NOT NULL
            ) bars WHERE position <= %s ORDER BY ticker, ts""",
            (normalized, normalized, max(1, min(limit_per_ticker, 10000))),
        ).fetchall()
    return [
        {
            "ticker": row["ticker"], "date": _iso(row["ts"]),
            "close": _number(row["close"]), "provider": row["provider"],
        }
        for row in rows
    ]


def regime_history(limit: int = 240) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT as_of_date, model_version, dominant_regime, probabilities,
            inputs, confidence, data_quality, is_point_in_time
            FROM public.macro_regime_labels ORDER BY as_of_date DESC LIMIT %s""",
            (max(1, min(limit, 1000)),),
        ).fetchall()
    return [
        {
            **dict(row), "as_of_date": _iso(row["as_of_date"]),
            "confidence": _number(row["confidence"]),
            "data_quality": _number(row["data_quality"]),
        }
        for row in rows
    ]
