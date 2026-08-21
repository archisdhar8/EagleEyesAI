from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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


def save_operational_event(event: dict[str, Any]) -> None:
    if not DATABASE_URL:
        return
    with postgres_connection() as conn:
        conn.execute(
            """INSERT INTO public.operational_events(metric_name, metric_value, tags, observed_at)
            VALUES (%s,%s,%s,%s)""",
            (event["name"], event["value"], _jsonb(event.get("tags") or {}), event["observed_at"]),
        )


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
    connect_timeout = max(2, min(15, int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5"))))
    statement_timeout = max(2_000, min(60_000, int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000"))))
    with psycopg.connect(
        DATABASE_URL,
        connect_timeout=connect_timeout,
        sslmode="require",
        row_factory=dict_row,
        options=f"-c statement_timeout={statement_timeout} -c lock_timeout=5000",
    ) as conn:
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
        """CREATE TABLE IF NOT EXISTS dashboard_jobs (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, portfolio_id TEXT, source_view_id TEXT,
            prompt TEXT NOT NULL, state TEXT NOT NULL, progress INTEGER NOT NULL,
            plan_json TEXT, specification_json TEXT, widget_results_json TEXT NOT NULL,
            narrative TEXT, warnings_json TEXT NOT NULL, error TEXT, cancelled_at TEXT,
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS dashboard_job_tasks (
            job_id TEXT NOT NULL, task_key TEXT NOT NULL, task_type TEXT NOT NULL,
            depends_on_json TEXT NOT NULL, required_for_narrative INTEGER NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL, calculation_version TEXT NOT NULL,
            query_json TEXT NOT NULL, result_json TEXT, error TEXT, started_at TEXT, completed_at TEXT,
            PRIMARY KEY(job_id, task_key)
        )""",
        """CREATE TABLE IF NOT EXISTS dashboard_views (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, original_prompt TEXT NOT NULL,
            plan_json TEXT NOT NULL, specification_json TEXT NOT NULL, layout_json TEXT NOT NULL,
            refresh_policy TEXT NOT NULL, spec_version TEXT NOT NULL DEFAULT 'dashboard-spec-v1',
            layout_version TEXT NOT NULL DEFAULT 'dashboard-layout-v1', conversation_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS dashboard_view_runs (
            id TEXT PRIMARY KEY, view_id TEXT NOT NULL, job_id TEXT, user_id TEXT NOT NULL,
            input_snapshot_json TEXT NOT NULL, widget_results_json TEXT NOT NULL, narrative TEXT,
            lineage_json TEXT NOT NULL, warnings_json TEXT NOT NULL, model_versions_json TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS dashboard_widget_cache (
            cache_key TEXT PRIMARY KEY, task_type TEXT NOT NULL, calculation_version TEXT NOT NULL,
            result_json TEXT NOT NULL, lineage_json TEXT NOT NULL, effective_through TEXT,
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS dashboard_view_revisions (
            id TEXT PRIMARY KEY, view_id TEXT NOT NULL, user_id TEXT NOT NULL,
            revision_number INTEGER NOT NULL, revision_type TEXT NOT NULL, prompt TEXT,
            plan_json TEXT NOT NULL, specification_json TEXT NOT NULL, layout_json TEXT NOT NULL,
            diff_json TEXT NOT NULL, spec_version TEXT NOT NULL, layout_version TEXT NOT NULL,
            source_view_id TEXT, created_at TEXT NOT NULL, UNIQUE(view_id, revision_number)
        )""",
        """CREATE TABLE IF NOT EXISTS financial_goals (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, goal_type TEXT NOT NULL,
            target_amount REAL NOT NULL, target_date TEXT NOT NULL, current_value REAL NOT NULL,
            annual_contribution REAL NOT NULL, priority INTEGER NOT NULL, funding_source TEXT NOT NULL DEFAULT 'New contributions',
            flexibility TEXT NOT NULL DEFAULT 'somewhat_flexible', inflation_adjusted INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS goal_account_allocations (
            goal_id TEXT NOT NULL, account_key TEXT NOT NULL, allocation REAL NOT NULL,
            PRIMARY KEY(goal_id, account_key),
            FOREIGN KEY(goal_id) REFERENCES financial_goals(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS terminal_layouts (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, widgets_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS investment_policies (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE, policy_json TEXT NOT NULL,
            status TEXT NOT NULL, approved_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS learning_preferences (
            user_id TEXT PRIMARY KEY, selected_path TEXT, knowledge_level TEXT NOT NULL,
            interests_json TEXT NOT NULL, portfolio_context_enabled INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS learning_progress (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, module_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
            content_version TEXT NOT NULL, status TEXT NOT NULL, completion_percentage REAL NOT NULL,
            started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id,lesson_id,content_version)
        )""",
        """CREATE TABLE IF NOT EXISTS learning_quiz_attempts (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, module_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
            content_version TEXT NOT NULL, quiz_id TEXT NOT NULL, quiz_version TEXT NOT NULL,
            score INTEGER NOT NULL, total_questions INTEGER NOT NULL, percentage REAL NOT NULL,
            answers_json TEXT NOT NULL, attempted_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS learning_tutor_threads (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, lesson_id TEXT NOT NULL, title TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS learning_tutor_messages (
            id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, source_references_json TEXT NOT NULL, retrieval_quality_json TEXT NOT NULL,
            model_version TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(thread_id) REFERENCES learning_tutor_threads(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS simulation_runs (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, portfolio_id TEXT,
            input_json TEXT NOT NULL, result_json TEXT NOT NULL, model_version TEXT NOT NULL,
            seed INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS allocation_builder_runs (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, builder_type TEXT NOT NULL,
            request_json TEXT NOT NULL, result_json TEXT NOT NULL, model_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS model_portfolios (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
            portfolio_type TEXT NOT NULL, status TEXT NOT NULL,
            candidate_universe_json TEXT NOT NULL, basket_json TEXT NOT NULL,
            configuration_json TEXT NOT NULL, comparison_results_json TEXT NOT NULL,
            backtest_results_json TEXT NOT NULL, simulation_run_id TEXT,
            converted_portfolio_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS investment_theses (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, ticker TEXT NOT NULL,
            summary TEXT NOT NULL, base_case TEXT NOT NULL, bull_case TEXT NOT NULL, bear_case TEXT NOT NULL,
            investment_horizon TEXT NOT NULL, horizon_end_date TEXT, review_date TEXT, status TEXT NOT NULL,
            source_context_json TEXT NOT NULL, current_version INTEGER NOT NULL DEFAULT 1,
            closed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS thesis_assumptions (
            id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, user_id TEXT NOT NULL,
            description TEXT NOT NULL, category TEXT NOT NULL, importance TEXT NOT NULL, status TEXT NOT NULL,
            metric TEXT, comparison_operator TEXT, target_value REAL, unit TEXT,
            evidence_mapping_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(thesis_id) REFERENCES investment_theses(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS thesis_factors (
            id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, user_id TEXT NOT NULL, factor_type TEXT NOT NULL,
            description TEXT NOT NULL, metric TEXT, comparison_operator TEXT, threshold REAL,
            period_requirement TEXT, unit TEXT, evidence_mapping_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(thesis_id) REFERENCES investment_theses(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS thesis_versions (
            id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, user_id TEXT NOT NULL, version_number INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL, change_note TEXT, created_at TEXT NOT NULL,
            UNIQUE(thesis_id, version_number),
            FOREIGN KEY(thesis_id) REFERENCES investment_theses(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS investment_decisions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, ticker TEXT NOT NULL, thesis_id TEXT,
            thesis_version INTEGER, decision_type TEXT NOT NULL, decision_date TEXT NOT NULL,
            price_at_decision REAL, price_as_of TEXT, price_source TEXT, quantity REAL,
            portfolio_context_json TEXT NOT NULL, user_confidence INTEGER, investment_horizon TEXT,
            notes TEXT NOT NULL, source_context_json TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(thesis_id) REFERENCES investment_theses(id) ON DELETE SET NULL
        )""",
        """CREATE TABLE IF NOT EXISTS evidence_snapshots (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, entity_type TEXT NOT NULL,
            entity_key TEXT NOT NULL, baseline_type TEXT NOT NULL, baseline_ref TEXT NOT NULL,
            as_of TEXT NOT NULL, observations_json TEXT NOT NULL,
            methodology_version TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(user_id, entity_key, baseline_type, baseline_ref)
        )""",
        """CREATE TABLE IF NOT EXISTS thesis_review_events (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, thesis_id TEXT NOT NULL,
            thesis_version INTEGER NOT NULL, ticker TEXT NOT NULL, baseline_review_at TEXT NOT NULL,
            evaluated_at TEXT NOT NULL, reviewed_at TEXT NOT NULL, overall_status TEXT NOT NULL,
            requires_review INTEGER NOT NULL, monitoring_result_json TEXT NOT NULL,
            calculation_version TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(thesis_id) REFERENCES investment_theses(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS user_forecasts (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, event_key TEXT NOT NULL,
            provider TEXT, external_market_id TEXT, title TEXT NOT NULL, probability REAL NOT NULL,
            reasoning TEXT NOT NULL, market_probability_at_entry REAL, model_probability_at_entry REAL,
            forecast_horizon TEXT, observed_at TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS forecast_resolution_events (
            id TEXT PRIMARY KEY, event_key TEXT NOT NULL, provider TEXT, external_market_id TEXT,
            outcome REAL NOT NULL, resolution_reference TEXT, resolved_at TEXT NOT NULL, recorded_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS attention_item_states (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, attention_item_id TEXT NOT NULL,
            state TEXT NOT NULL, snoozed_until TEXT, note TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, attention_item_id)
        )""",
        """CREATE TABLE IF NOT EXISTS portfolio_health_snapshots (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
            snapshot_date TEXT NOT NULL, trigger TEXT NOT NULL, input_hash TEXT NOT NULL,
            health_score REAL NOT NULL, health_band TEXT NOT NULL, confidence TEXT NOT NULL,
            coverage REAL NOT NULL, components_json TEXT NOT NULL, holding_metrics_json TEXT NOT NULL,
            changes_json TEXT NOT NULL, warnings_json TEXT NOT NULL, result_json TEXT NOT NULL,
            methodology_version TEXT NOT NULL, effective_at TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(user_id,portfolio_id,trigger,input_hash)
        )""",
        """CREATE TABLE IF NOT EXISTS portfolio_action_items (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
            source_key TEXT NOT NULL, source TEXT NOT NULL, action_type TEXT NOT NULL,
            title TEXT NOT NULL, reason TEXT NOT NULL, payload_json TEXT NOT NULL,
            priority REAL NOT NULL, state TEXT NOT NULL, active INTEGER NOT NULL,
            snoozed_until TEXT, note TEXT NOT NULL, first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id,portfolio_id,source_key)
        )""",
        """CREATE TABLE IF NOT EXISTS alert_preferences (
            user_id TEXT PRIMARY KEY, delivery_mode TEXT NOT NULL, threshold TEXT NOT NULL,
            categories TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS alert_events (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, attention_item_id TEXT NOT NULL,
            group_key TEXT NOT NULL, alert_type TEXT NOT NULL, materiality TEXT NOT NULL,
            title TEXT NOT NULL, summary TEXT NOT NULL, payload TEXT NOT NULL,
            occurred_at TEXT NOT NULL, supersedes_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(user_id, attention_item_id)
        )""",
        """CREATE TABLE IF NOT EXISTS decision_preferences (
            user_id TEXT PRIMARY KEY, explicit_preferences TEXT NOT NULL,
            accepted_preferences TEXT NOT NULL, dismissed_inferences TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS decision_context_snapshots (
            id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL, ticker TEXT NOT NULL,
            decision_date TEXT NOT NULL, snapshot_json TEXT NOT NULL, methodology_version TEXT NOT NULL, captured_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS decision_retrospectives (
            id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, user_id TEXT NOT NULL, horizon_key TEXT NOT NULL,
            window_start TEXT NOT NULL, window_end TEXT NOT NULL, structured_result_json TEXT NOT NULL,
            user_notes TEXT NOT NULL, ai_summary TEXT, ai_model TEXT, summary_version TEXT,
            reviewed_at TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(decision_id,horizon_key,window_end)
        )""",
    ]
    with sqlite_connection() as conn:
        for statement in statements:
            conn.execute(statement)
        goal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(financial_goals)").fetchall()}
        if "funding_source" not in goal_columns:
            conn.execute("ALTER TABLE financial_goals ADD COLUMN funding_source TEXT NOT NULL DEFAULT 'New contributions'")
        if "flexibility" not in goal_columns:
            conn.execute("ALTER TABLE financial_goals ADD COLUMN flexibility TEXT NOT NULL DEFAULT 'somewhat_flexible'")
        view_columns = {row["name"] for row in conn.execute("PRAGMA table_info(dashboard_views)").fetchall()}
        if "spec_version" not in view_columns:
            conn.execute("ALTER TABLE dashboard_views ADD COLUMN spec_version TEXT NOT NULL DEFAULT 'dashboard-spec-v1'")
        if "layout_version" not in view_columns:
            conn.execute("ALTER TABLE dashboard_views ADD COLUMN layout_version TEXT NOT NULL DEFAULT 'dashboard-layout-v1'")
        if "conversation_id" not in view_columns:
            conn.execute("ALTER TABLE dashboard_views ADD COLUMN conversation_id TEXT")
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(dashboard_jobs)").fetchall()}
        if "conversation_id" not in job_columns:
            conn.execute("ALTER TABLE dashboard_jobs ADD COLUMN conversation_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS scenario_fetched_idx ON scenario_snapshots(fetched_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS analysis_created_idx ON analysis_runs(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS dashboard_jobs_user_idx ON dashboard_jobs(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS dashboard_views_user_idx ON dashboard_views(user_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS dashboard_view_revisions_view_idx ON dashboard_view_revisions(view_id, revision_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS financial_goals_user_idx ON financial_goals(user_id, priority, target_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS simulation_runs_user_idx ON simulation_runs(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS allocation_builder_runs_user_idx ON allocation_builder_runs(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS model_portfolios_user_idx ON model_portfolios(user_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS investment_theses_user_ticker_idx ON investment_theses(user_id, ticker, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS investment_theses_review_idx ON investment_theses(user_id, status, review_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS thesis_assumptions_thesis_idx ON thesis_assumptions(thesis_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS thesis_factors_thesis_idx ON thesis_factors(thesis_id, factor_type, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS thesis_versions_thesis_idx ON thesis_versions(thesis_id, version_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS investment_decisions_user_ticker_idx ON investment_decisions(user_id, ticker, decision_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS evidence_snapshots_user_entity_idx ON evidence_snapshots(user_id, entity_key, as_of)")
        conn.execute("CREATE INDEX IF NOT EXISTS thesis_review_events_user_thesis_idx ON thesis_review_events(user_id, thesis_id, reviewed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS thesis_review_events_user_status_idx ON thesis_review_events(user_id, overall_status, reviewed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS user_forecasts_user_event_idx ON user_forecasts(user_id, event_key, observed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS forecast_resolution_event_idx ON forecast_resolution_events(event_key, resolved_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS attention_item_states_user_idx ON attention_item_states(user_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS alert_events_user_status_idx ON alert_events(user_id, status, occurred_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS alert_events_user_group_idx ON alert_events(user_id, group_key, occurred_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS decision_context_snapshots_user_idx ON decision_context_snapshots(user_id, decision_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS decision_retrospectives_user_idx ON decision_retrospectives(user_id, reviewed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS terminal_layouts_user_idx ON terminal_layouts(user_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS learning_progress_user_idx ON learning_progress(user_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS learning_quiz_user_lesson_idx ON learning_quiz_attempts(user_id, lesson_id, attempted_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS learning_threads_user_idx ON learning_tutor_threads(user_id, updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS learning_messages_thread_idx ON learning_tutor_messages(thread_id, created_at)")


def save_portfolio(
    name: str, holdings: list[dict[str, Any]], portfolio_id: str | int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            if portfolio_id is None:
                portfolio_id = str(
                    conn.execute(
                        "INSERT INTO public.portfolios(name, user_id) VALUES (%s, %s) RETURNING id",
                        (name, user_id),
                    ).fetchone()["id"]
                )
            else:
                updated = conn.execute(
                    "UPDATE public.portfolios SET name = %s WHERE id = %s AND user_id IS NOT DISTINCT FROM %s RETURNING id",
                    (name, portfolio_id, user_id),
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
        return get_portfolio(portfolio_id, user_id)

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
    return get_portfolio(portfolio_id, user_id)


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


def get_portfolio(portfolio_id: str | int, user_id: str | None = None) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT id, name, updated_at FROM public.portfolios WHERE id = %s AND user_id IS NOT DISTINCT FROM %s",
                (portfolio_id, user_id),
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


def list_portfolios(user_id: str | None = None) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, updated_at FROM public.portfolios WHERE user_id IS NOT DISTINCT FROM %s ORDER BY updated_at DESC",
                (user_id,),
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


def activate_portfolio(portfolio_id: str | int, user_id: str | None = None) -> dict[str, Any]:
    """Make a saved portfolio the user's current workspace without changing its holdings."""
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "UPDATE public.portfolios SET updated_at=%s WHERE id=%s AND user_id IS NOT DISTINCT FROM %s RETURNING id",
                (now, portfolio_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(portfolio_id)
    else:
        with sqlite_connection() as conn:
            cursor = conn.execute("UPDATE portfolios SET updated_at=? WHERE id=?", (now, portfolio_id))
            if cursor.rowcount == 0:
                raise KeyError(portfolio_id)
    return get_portfolio(portfolio_id, user_id)


def save_profile(profile: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    if DATABASE_URL:
        now = utc_now()
        explanation = {
            "llm_provider": profile.get("llm_provider", "disabled"),
            "llm_endpoint": profile.get("llm_endpoint"),
            "llm_model": profile.get("llm_model"),
        }
        with postgres_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM public.investor_profiles WHERE user_id IS NOT DISTINCT FROM %s ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            values = (
                profile.get("age"), profile.get("retirement_age"), profile.get("horizon_years"),
                profile.get("account_type", "taxable"), profile.get("annual_contribution", 0),
                profile.get("annual_withdrawal", 0), profile.get("target_value"), profile.get("tax_rate"),
                profile.get("risk_tolerance"), profile.get("loss_capacity", 6),
                profile.get("annual_income_need", 0), profile.get("preset", "balanced"),
                _jsonb(profile.get("restrictions", [])), profile.get("watchlist", []),
                _jsonb(profile.get("objectives", {})), _jsonb(explanation),
                _jsonb(profile.get("suitability_profile", {})),
            )
            if existing:
                conn.execute(
                    """UPDATE public.investor_profiles SET
                    age=%s, retirement_age=%s, horizon_years=%s, account_type=%s,
                    annual_contribution=%s, annual_withdrawal=%s, target_value=%s, tax_rate=%s,
                    risk_tolerance=%s, loss_capacity=%s, annual_income_need=%s,
                    preset=%s, restrictions=%s, watchlist=%s,
                    objective_weights=%s, explanation_settings=%s, suitability_profile=%s WHERE id=%s""",
                    (*values, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO public.investor_profiles(
                    age, retirement_age, horizon_years, account_type, annual_contribution,
                    annual_withdrawal, target_value, tax_rate, risk_tolerance,
                    loss_capacity, annual_income_need, preset, restrictions, watchlist,
                    objective_weights, explanation_settings, suitability_profile, user_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (*values, user_id),
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


def load_profile(user_id: str | None = None) -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT * FROM public.investor_profiles WHERE user_id IS NOT DISTINCT FROM %s ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
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
            "loss_capacity": int(row["loss_capacity"]) if row.get("loss_capacity") is not None else 6,
            "annual_income_need": _number(row.get("annual_income_need")) or 0,
            "preset": row["preset"], "restrictions": row["restrictions"] or [],
            "watchlist": row["watchlist"] or [], "objectives": row["objective_weights"] or {},
            "suitability_profile": row.get("suitability_profile") or {},
            "llm_provider": explanation.get("llm_provider", "disabled"),
            "llm_endpoint": explanation.get("llm_endpoint"), "llm_model": explanation.get("llm_model"),
            "updated_at": _iso(row["updated_at"]),
        }

    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = 1").fetchone()
    return None if row is None else {**json.loads(row["profile_json"]), "updated_at": row["updated_at"]}


def _goal(row: Any, allocations: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "name": row["name"], "goal_type": row["goal_type"],
        "target_amount": _number(row["target_amount"]), "target_date": _iso(row["target_date"]),
        "current_value": _number(row["current_value"]),
        "annual_contribution": _number(row["annual_contribution"]), "priority": int(row["priority"]),
        "funding_source": row.get("funding_source", "New contributions") if isinstance(row, dict) else row["funding_source"],
        "flexibility": row.get("flexibility", "somewhat_flexible") if isinstance(row, dict) else row["flexibility"],
        "inflation_adjusted": bool(row["inflation_adjusted"]),
        "account_allocations": allocations or {}, "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def list_goals(user_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM public.financial_goals WHERE user_id=%s ORDER BY priority, target_date", (user_id,)
            ).fetchall()
            allocations = conn.execute(
                """SELECT a.goal_id,a.account_key,a.allocation FROM public.goal_account_allocations a
                JOIN public.financial_goals g ON g.id=a.goal_id WHERE g.user_id=%s""", (user_id,)
            ).fetchall()
    else:
        with sqlite_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM financial_goals WHERE user_id=? ORDER BY priority,target_date", (user_id,)
            ).fetchall()
            allocations = conn.execute(
                """SELECT a.goal_id,a.account_key,a.allocation FROM goal_account_allocations a
                JOIN financial_goals g ON g.id=a.goal_id WHERE g.user_id=?""", (user_id,)
            ).fetchall()
    grouped: dict[str, dict[str, float]] = {}
    for item in allocations:
        grouped.setdefault(str(item["goal_id"]), {})[item["account_key"]] = float(item["allocation"])
    return [_goal(row, grouped.get(str(row["id"]), {})) for row in rows]


def save_goal(user_id: str, goal: dict[str, Any], goal_id: str | None = None) -> dict[str, Any]:
    goal_id = goal_id or str(uuid.uuid4())
    now = utc_now()
    allocations = {str(key): float(value) for key, value in goal.get("account_allocations", {}).items()}
    existing = [item for item in list_goals(user_id) if item["id"] != goal_id]
    account_totals: dict[str, float] = {}
    for item in existing:
        for account, value in item.get("account_allocations", {}).items():
            account_totals[account] = account_totals.get(account, 0) + float(value)
    conflicts = [account for account, value in allocations.items() if account_totals.get(account, 0) + value > 1.000001]
    if conflicts:
        raise ValueError(f"Account allocation exceeds 100% across goals: {', '.join(sorted(conflicts))}")
    values = (
        goal["name"], goal.get("goal_type", "long_term_growth"), goal["target_amount"], goal["target_date"],
        goal.get("current_value", 0), goal.get("annual_contribution", 0), goal.get("priority", 3),
        goal.get("funding_source", "New contributions"), goal.get("flexibility", "somewhat_flexible"),
        goal.get("inflation_adjusted", True), now,
    )
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.financial_goals(
                id,user_id,name,goal_type,target_amount,target_date,current_value,annual_contribution,priority,funding_source,flexibility,inflation_adjusted,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,goal_type=excluded.goal_type,
                target_amount=excluded.target_amount,target_date=excluded.target_date,current_value=excluded.current_value,
                annual_contribution=excluded.annual_contribution,priority=excluded.priority,
                funding_source=excluded.funding_source,flexibility=excluded.flexibility,
                inflation_adjusted=excluded.inflation_adjusted,updated_at=excluded.updated_at
                WHERE public.financial_goals.user_id=excluded.user_id RETURNING *""",
                (goal_id, user_id, *values),
            ).fetchone()
            if row is None:
                raise KeyError(goal_id)
            conn.execute("DELETE FROM public.goal_account_allocations WHERE goal_id=%s", (goal_id,))
            for account, allocation in allocations.items():
                conn.execute(
                    "INSERT INTO public.goal_account_allocations(goal_id,account_key,allocation) VALUES(%s,%s,%s)",
                    (goal_id, account, allocation),
                )
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO financial_goals(
                id,user_id,name,goal_type,target_amount,target_date,current_value,annual_contribution,priority,funding_source,flexibility,inflation_adjusted,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                goal_type=excluded.goal_type,target_amount=excluded.target_amount,target_date=excluded.target_date,
                current_value=excluded.current_value,annual_contribution=excluded.annual_contribution,
                priority=excluded.priority,funding_source=excluded.funding_source,flexibility=excluded.flexibility,
                inflation_adjusted=excluded.inflation_adjusted,updated_at=excluded.updated_at
                WHERE user_id=excluded.user_id""",
                (goal_id, user_id, *values[:-1], now, now),
            )
            conn.execute("DELETE FROM goal_account_allocations WHERE goal_id=?", (goal_id,))
            conn.executemany(
                "INSERT INTO goal_account_allocations(goal_id,account_key,allocation) VALUES(?,?,?)",
                [(goal_id, account, allocation) for account, allocation in allocations.items()],
            )
    return next(item for item in list_goals(user_id) if item["id"] == goal_id)


def load_investment_policy(user_id: str) -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute("SELECT * FROM public.investment_policies WHERE user_id=%s", (user_id,)).fetchone()
        if not row:
            return None
        policy = dict(row["policy"])
    else:
        with sqlite_connection() as conn:
            row = conn.execute("SELECT * FROM investment_policies WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        policy = json.loads(row["policy_json"])
    return {**policy, "id": str(row["id"]), "status": row["status"], "approved_at": _iso(row["approved_at"]), "updated_at": _iso(row["updated_at"])}


def save_investment_policy(user_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    existing = load_investment_policy(user_id)
    policy_id = existing["id"] if existing else str(uuid.uuid4())
    now = utc_now()
    status = policy.get("status", "draft")
    approved_at = policy.get("approved_at") or (now if status == "approved" else None)
    stored = {**policy, "id": policy_id, "status": status, "approved_at": approved_at}
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.investment_policies(id,user_id,policy,status,approved_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET policy=excluded.policy,
                status=excluded.status,approved_at=excluded.approved_at,updated_at=excluded.updated_at""",
                (policy_id, user_id, _jsonb(stored), status, approved_at, now),
            )
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO investment_policies(id,user_id,policy_json,status,approved_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET policy_json=excluded.policy_json,
                status=excluded.status,approved_at=excluded.approved_at,updated_at=excluded.updated_at""",
                (policy_id, user_id, json.dumps(stored, default=str), status, approved_at, now, now),
            )
    return load_investment_policy(user_id) or stored


def delete_goal(goal_id: str, user_id: str) -> None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "DELETE FROM public.financial_goals WHERE id=%s AND user_id=%s RETURNING id", (goal_id, user_id)
            ).fetchone()
    else:
        with sqlite_connection() as conn:
            row = conn.execute("SELECT id FROM financial_goals WHERE id=? AND user_id=?", (goal_id, user_id)).fetchone()
            if row:
                conn.execute("DELETE FROM goal_account_allocations WHERE goal_id=?", (goal_id,))
                conn.execute("DELETE FROM financial_goals WHERE id=? AND user_id=?", (goal_id, user_id))
    if row is None:
        raise KeyError(goal_id)


def list_terminal_layouts(user_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM public.terminal_layouts WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        return [{**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} for row in rows]
    with sqlite_connection() as conn:
        rows = conn.execute("SELECT * FROM terminal_layouts WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    return [{"id": row["id"], "name": row["name"], "widgets": json.loads(row["widgets_json"]), "created_at": row["created_at"], "updated_at": row["updated_at"]} for row in rows]


def save_terminal_layout(user_id: str, name: str, widgets: list[dict[str, Any]], layout_id: str | None = None) -> dict[str, Any]:
    layout_id = layout_id or str(uuid.uuid4())
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.terminal_layouts(id,user_id,name,widgets,updated_at)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                widgets=excluded.widgets,updated_at=excluded.updated_at WHERE public.terminal_layouts.user_id=excluded.user_id
                RETURNING *""", (layout_id, user_id, name, _jsonb(widgets), now)
            ).fetchone()
        if row is None:
            raise KeyError(layout_id)
        return {**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])}
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO terminal_layouts(id,user_id,name,widgets_json,created_at,updated_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,widgets_json=excluded.widgets_json,
            updated_at=excluded.updated_at WHERE user_id=excluded.user_id""",
            (layout_id, user_id, name, json.dumps(widgets), now, now),
        )
    return next(item for item in list_terminal_layouts(user_id) if item["id"] == layout_id)


def delete_terminal_layout(layout_id: str, user_id: str) -> None:
    table = "public.terminal_layouts" if DATABASE_URL else "terminal_layouts"
    placeholder = "%s" if DATABASE_URL else "?"
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        row = conn.execute(
            f"DELETE FROM {table} WHERE id={placeholder} AND user_id={placeholder} RETURNING id", (layout_id, user_id)
        ).fetchone()
    if row is None:
        raise KeyError(layout_id)


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
                    "prediction-market-v2", _jsonb(warnings),
                    _jsonb({"classifier": "strict-macro-v2", "sports_rejection": True}),
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
                """SELECT raw_scenarios, raw_contracts, observed_at FROM public.scenario_snapshots
                ORDER BY observed_at DESC LIMIT 800"""
            ).fetchall()
        return [{"scenarios": row["raw_scenarios"], "contracts": row["raw_contracts"],
                 "fetched_at": _iso(row["observed_at"])} for row in rows]

    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT scenarios_json, contracts_json, fetched_at FROM scenario_snapshots ORDER BY fetched_at DESC LIMIT 800"
        ).fetchall()
    return [{"scenarios": json.loads(row["scenarios_json"]), "contracts": json.loads(row["contracts_json"]),
             "fetched_at": row["fetched_at"]} for row in rows]


def save_analysis(run_id: str, request: dict[str, Any], result: dict[str, Any], user_id: str | None = None) -> None:
    if DATABASE_URL:
        portfolio_id = request.get("portfolio_id")
        with postgres_connection() as conn:
            profile = conn.execute(
                "SELECT id FROM public.investor_profiles WHERE user_id IS NOT DISTINCT FROM %s ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            conn.execute(
                """INSERT INTO public.analysis_runs(
                id, portfolio_id, profile_id, status, model_version, config_version,
                input_snapshot, data_lineage, current_portfolio, alternatives, warnings,
                result_snapshot, created_at, user_id
                ) VALUES (%s,%s,%s,'completed',%s,'v1',%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET result_snapshot=excluded.result_snapshot""",
                (
                    run_id, portfolio_id, profile["id"] if profile else None,
                    result.get("model_version", "walk-forward-regime-shrinkage-v2"), _jsonb(request),
                    _jsonb(result.get("data_lineage", {})), _jsonb(result.get("current_weights", {})),
                    _jsonb(result.get("alternatives", [])), _jsonb(result.get("warnings", [])),
                    _jsonb(result), result.get("created_at", utc_now()), user_id,
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
                result.get("model_version", "prediction-market-v2"),
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


def load_analysis(run_id: str, user_id: str | None = None) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT result_snapshot FROM public.analysis_runs WHERE id = %s AND user_id IS NOT DISTINCT FROM %s",
                (run_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row["result_snapshot"]

    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    return json.loads(row["result_json"])


def latest_analysis(user_id: str | None = None, portfolio_id: str | int | None = None) -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """SELECT result_snapshot FROM public.analysis_runs
                WHERE status = 'completed' AND user_id IS NOT DISTINCT FROM %s
                AND (%s::text IS NULL OR portfolio_id::text=%s::text) ORDER BY created_at DESC LIMIT 1""",
                (user_id, portfolio_id, portfolio_id),
            ).fetchone()
        return None if row is None else row["result_snapshot"]

    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT request_json, result_json FROM analysis_runs ORDER BY created_at DESC"
        ).fetchall()
    for row in rows:
        request = json.loads(row["request_json"])
        if portfolio_id is None or str(request.get("portfolio_id")) == str(portfolio_id):
            return json.loads(row["result_json"])
    return None


def cached_analysis(cache_key: str, user_id: str | None = None) -> dict[str, Any] | None:
    """Return the newest completed analysis produced from the same effective inputs.

    The cache key lives in the immutable input snapshot so this works with the
    existing analysis_runs schema and does not rewrite historical runs.
    """
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                """SELECT input_snapshot, result_snapshot FROM public.analysis_runs
                WHERE status = 'completed' AND user_id IS NOT DISTINCT FROM %s
                ORDER BY created_at DESC LIMIT 50""",
                (user_id,),
            ).fetchall()
        for row in rows:
            request = row["input_snapshot"] or {}
            if request.get("analysis_cache_key") == cache_key:
                return row["result_snapshot"]
        return None

    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT request_json, result_json FROM analysis_runs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    for row in rows:
        request = json.loads(row["request_json"])
        if request.get("analysis_cache_key") == cache_key:
            return json.loads(row["result_json"])
    return None


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
            (SELECT count(*) FROM public.market_observations) AS market_observations,
            (SELECT count(*) FROM public.market_events) AS market_events,
            (SELECT count(*) FROM public.macro_regime_labels) AS macro_regimes"""
        ).fetchone()
        freshness = conn.execute(
            """SELECT
            (SELECT max(ts) FROM public.price_bars) AS prices,
            (SELECT max(observation_date) FROM public.macro_observations) AS macro,
            (SELECT max(period_end) FROM public.fundamental_periods) AS fundamentals,
            (SELECT max(published_at) FROM public.documents WHERE document_type='news') AS news,
            (SELECT max(observed_at) FROM public.prediction_market_snapshots) AS markets,
            (SELECT max(observed_at) FROM public.market_observations) AS market_observations,
            (SELECT max(coalesce(verified_at,fetched_at)) FROM public.market_events) AS market_events,
            (SELECT max(as_of_date) FROM public.macro_regime_labels) AS regimes"""
        ).fetchone()
        providers = conn.execute(
            """SELECT DISTINCT ON (provider) provider, status, fetched_at, as_of,
            metadata, error_message FROM public.provider_fetches
            ORDER BY provider, fetched_at DESC"""
        ).fetchall()
        provider_windows = conn.execute(
            """WITH recent AS (
              SELECT provider,status,fetched_at,row_number() OVER (PARTITION BY provider ORDER BY fetched_at DESC) AS rn
              FROM public.provider_fetches
            ) SELECT provider,count(*) AS attempts,
              count(*) FILTER (WHERE status='success') AS successes,
              max(fetched_at) FILTER (WHERE status='success') AS last_success_at,
              min(fetched_at) AS window_start
            FROM recent WHERE rn<=50 GROUP BY provider"""
        ).fetchall()
        price_coverage = conn.execute(
            """SELECT p.provider, count(*) AS bars, count(DISTINCT p.security_id) AS symbols,
            min(p.ts) AS earliest, max(p.ts) AS latest
            FROM public.price_bars p GROUP BY p.provider ORDER BY p.provider"""
        ).fetchall()
    windows={str(row["provider"]).lower():{"attempts":int(row["attempts"] or 0),"successes":int(row["successes"] or 0),
             "last_success_at":_iso(row["last_success_at"]),"window_start":_iso(row["window_start"])} for row in provider_windows}
    return {
        "storage": "supabase",
        "counts": {key: int(value or 0) for key, value in counts.items()},
        "freshness": {key: _iso(value) for key, value in freshness.items()},
        "providers": [
            {
                "provider": row["provider"], "status": row["status"],
                "fetched_at": _iso(row["fetched_at"]), "as_of": _iso(row["as_of"]),
                "metadata": row["metadata"] or {}, "error": row["error_message"],
                "window": windows.get(str(row["provider"]).lower(), {}),
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


def upcoming_market_events(tickers: list[str], days: int = 45) -> list[dict[str, Any]]:
    """Return server-ingested events; an empty list is explicit missing coverage."""
    if not DATABASE_URL:
        return []
    normalized = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip() and ticker.upper() != "CASH"})
    try:
        with postgres_connection() as conn:
            rows = conn.execute(
                """SELECT id, provider, external_id, event_type, title, starts_at,
                tickers, source_url, metadata, fetched_at, event_status, timing_status,
                verified_at, timezone_name, dedupe_key
                FROM public.market_events
                WHERE starts_at >= now() AND starts_at <= now() + (%s * interval '1 day')
                  AND (%s = '{}'::text[] OR tickers = '{}'::text[] OR tickers && %s)
                ORDER BY starts_at, title LIMIT 100""",
                (max(1, min(days, 180)), normalized, normalized),
            ).fetchall()
    except psycopg.Error:
        return []
    return [
        {
            **dict(row), "id": str(row["id"]), "starts_at": _iso(row["starts_at"]),
            "fetched_at": _iso(row["fetched_at"]), "tickers": list(row["tickers"] or []),
        }
        for row in rows
    ]


def save_market_observations(rows: list[dict[str, Any]]) -> int:
    if not DATABASE_URL or not rows:
        return 0
    with postgres_connection() as conn:
        for row in rows:
            conn.execute(
                """INSERT INTO public.market_observations(
                ticker,value,observed_at,retrieved_at,provider,dataset,latency_class,
                entitlement,source_url,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(ticker,provider,dataset,observed_at) DO UPDATE SET
                value=excluded.value,retrieved_at=excluded.retrieved_at,
                latency_class=excluded.latency_class,entitlement=excluded.entitlement,
                source_url=excluded.source_url,metadata=excluded.metadata""",
                (
                    row["ticker"], row["value"], row["observed_at"], row["retrieved_at"],
                    row["provider"], row["dataset"], row["latency_class"], row["entitlement"],
                    row.get("source_url"), _jsonb({"version": row.get("version")}),
                ),
            )
    return len(rows)


def latest_market_observations(tickers: list[str]) -> list[dict[str, Any]]:
    if not DATABASE_URL or not tickers:
        return []
    normalized = sorted({ticker.upper() for ticker in tickers if ticker and ticker.upper() != "CASH"})
    try:
        with postgres_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT ON (ticker) ticker,value,observed_at,retrieved_at,
                provider,dataset,latency_class,entitlement,source_url,metadata
                FROM public.market_observations WHERE ticker = ANY(%s)
                ORDER BY ticker, observed_at DESC, retrieved_at DESC""",
                (normalized,),
            ).fetchall()
    except psycopg.Error:
        return []
    return [{**dict(row), "observed_at": _iso(row["observed_at"]), "retrieved_at": _iso(row["retrieved_at"])} for row in rows]


def latest_briefing_snapshot(user_id: str | None) -> dict[str, Any] | None:
    if not DATABASE_URL or not user_id:
        return None
    try:
        with postgres_connection() as conn:
            row = conn.execute(
                """SELECT result FROM public.briefing_snapshots
                WHERE user_id=%s AND evidence_state='current'
                ORDER BY effective_at DESC, created_at DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
    except psycopg.Error:
        return None
    return None if row is None else row["result"]


def save_briefing_snapshot(user_id: str | None, briefing: dict[str, Any]) -> str | None:
    if not DATABASE_URL or not user_id:
        return None
    try:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.briefing_snapshots
                (user_id, briefing_version, evidence_state, result, effective_at)
                VALUES (%s,%s,%s,%s::jsonb,%s) RETURNING id""",
                (
                    user_id, briefing.get("version", "today-briefing-v1"), briefing.get("evidence_state", "partial"),
                    json.dumps(briefing, default=str), briefing.get("as_of") or datetime.now(timezone.utc).isoformat(),
                ),
            ).fetchone()
    except psycopg.Error:
        return None
    return str(row["id"])


def macro_observation_history(series_ids: list[str], limit_per_series: int = 18) -> list[dict[str, Any]]:
    if not DATABASE_URL or not series_ids:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """WITH unique_observations AS (
              SELECT DISTINCT ON (series_id, observation_date)
                series_id, observation_date, vintage_date, value, provider, source_url
              FROM public.macro_observations WHERE series_id = ANY(%s)
              ORDER BY series_id, observation_date, vintage_date DESC,
                CASE WHEN provider='FRED' THEN 0 ELSE 1 END
            )
            SELECT series_id, observation_date, vintage_date, value, provider, source_url
            FROM (
              SELECT *, row_number() OVER (
                PARTITION BY series_id ORDER BY observation_date DESC
              ) AS position FROM unique_observations
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


def macro_point_in_time_history(series_ids: list[str], limit_per_series: int = 300) -> list[dict[str, Any]]:
    """Return one earliest available real-time vintage for each observation date."""
    if not DATABASE_URL or not series_ids:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """WITH first_vintages AS (
              SELECT DISTINCT ON (series_id, observation_date)
                series_id, observation_date, vintage_date, value, provider, source_url
              FROM public.macro_observations
              WHERE series_id = ANY(%s) AND is_point_in_time=true
              ORDER BY series_id, observation_date, vintage_date ASC,
                CASE WHEN provider='ALFRED' THEN 0 ELSE 1 END
            )
            SELECT series_id, observation_date, vintage_date, value, provider, source_url
            FROM (
              SELECT *, row_number() OVER (
                PARTITION BY series_id ORDER BY observation_date DESC
              ) AS position FROM first_vintages
            ) observations WHERE position <= %s
            ORDER BY series_id, observation_date DESC""",
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
        return {"securities": [], "fundamentals": [], "prices": [], "news": [], "company_markets": []}
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
        # A lateral bounded lookup lets Postgres use the security/time index for
        # each requested symbol.  The former window query ranked every stored
        # bar before applying the per-symbol limit and made Today/research reads
        # increasingly slow as history accumulated.
        prices = conn.execute(
            """SELECT s.ticker, bars.ts, bars.close, bars.volume, bars.fetched_at,
            bars.provider
            FROM public.securities s
            CROSS JOIN LATERAL (
              SELECT canonical.ts, canonical.close, canonical.volume,
              canonical.fetched_at, canonical.provider
              FROM (
                SELECT DISTINCT ON (p.ts) p.ts,
                  COALESCE(p.adjusted_close, p.close) AS close,
                  p.volume, p.fetched_at, p.provider
                FROM public.price_bars p
                WHERE p.security_id=s.id AND p.interval='1d'
                ORDER BY p.ts DESC,
                  CASE WHEN p.provider='tiingo' THEN 0 WHEN p.provider='polygon' THEN 1 ELSE 2 END,
                  p.fetched_at DESC
              ) canonical
              ORDER BY canonical.ts DESC LIMIT %s
            ) bars
            WHERE s.ticker = ANY(%s)
            ORDER BY s.ticker, bars.ts""",
            (price_limit, normalized),
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
        company_markets = conn.execute(
            """SELECT ticker, provider, external_market_id, title, source_url,
            evidence_type, closes_at, probability, confidence, volume, observed_at
            FROM (
              SELECT upper(pm.metadata->>'ticker') AS ticker, pm.provider,
              pm.external_market_id, pm.title, pm.source_url,
              pm.metadata->>'evidence_type' AS evidence_type,
              pm.closes_at, pms.probability,
              pms.confidence, pms.volume, pms.observed_at,
              row_number() OVER (
                PARTITION BY pm.id ORDER BY pms.observed_at DESC
              ) AS snapshot_position
              FROM public.prediction_markets pm
              JOIN public.prediction_market_snapshots pms ON pms.market_id=pm.id
              WHERE upper(pm.metadata->>'ticker') = ANY(%s)
                AND pm.canonical_scenario IS NULL
            ) latest WHERE snapshot_position=1
            ORDER BY ticker, confidence DESC NULLS LAST, volume DESC NULLS LAST""",
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
                "fetched_at": _iso(row["fetched_at"]), "provider": row["provider"],
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
        "company_markets": [
            {
                **dict(row), "probability": _number(row["probability"]),
                "confidence": _number(row["confidence"]), "volume": _number(row["volume"]),
                "closes_at": _iso(row["closes_at"]), "observed_at": _iso(row["observed_at"]),
                "source": row["source_url"], "id": row["external_market_id"],
            }
            for row in company_markets
        ],
    }


def earnings_transcript_chunks(ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return a bounded set of earnings-relevant chunks; never loads a full transcript."""
    if not DATABASE_URL:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT d.title,d.source_url,d.provider,d.published_at,c.chunk_index,c.content,c.metadata
            FROM public.documents d JOIN public.securities s ON s.id=d.security_id
            JOIN public.document_chunks c ON c.document_id=d.id
            WHERE s.ticker=%s AND d.document_type IN ('transcript','earnings_transcript')
              AND (c.content ILIKE '%%guidance%%' OR c.content ILIKE '%%margin%%'
                   OR c.content ILIKE '%%demand%%' OR c.content ILIKE '%%risk%%')
            ORDER BY d.published_at DESC NULLS LAST,c.chunk_index LIMIT %s""",
            (ticker.upper(), max(1, min(limit, 12))),
        ).fetchall()
    return [{**dict(row), "published_at": _iso(row["published_at"])} for row in rows]


def list_security_universe(limit: int = 500, query: str | None = None) -> list[dict[str, Any]]:
    """Return the stored active security catalog used to disclose research scope."""
    if not DATABASE_URL:
        return []
    normalized_query = (query or "").strip()
    with postgres_connection() as conn:
        if normalized_query:
            pattern = f"%{normalized_query}%"
            rows = conn.execute(
                """SELECT ticker, asset_type, company_name, sector, industry, updated_at
                FROM public.securities
                WHERE active=true AND (ticker ILIKE %s OR company_name ILIKE %s)
                ORDER BY CASE WHEN upper(ticker)=upper(%s) THEN 0 ELSE 1 END, ticker
                LIMIT %s""",
                (pattern, pattern, normalized_query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT ticker, asset_type, company_name, sector, industry, updated_at
                FROM public.securities WHERE active=true ORDER BY ticker LIMIT %s""",
                (limit,),
            ).fetchall()
    return [{**dict(row), "updated_at": _iso(row["updated_at"])} for row in rows]


def search_security_master(query: str, limit: int = 50) -> dict[str, Any]:
    """Return supported scope separately from evidence availability."""
    normalized = query.strip()
    if not DATABASE_URL:
        return {"query": query, "scope": "local fixture universe", "results": [], "unsupported_reason": "A connected security master is unavailable in local fixture mode."}
    with postgres_connection() as conn:
        pattern = f"%{normalized}%"
        rows = conn.execute(
            """SELECT ticker,name,exchange,instrument_type,currency,active_from,active_to,active,
            coverage_tier,provider_mappings,verified_at
            FROM public.security_master
            WHERE ticker ILIKE %s OR name ILIKE %s
            ORDER BY CASE WHEN upper(ticker)=upper(%s) THEN 0 ELSE 1 END,active DESC,ticker
            LIMIT %s""", (pattern, pattern, normalized, max(1, min(limit, 200))),
        ).fetchall()
        # The provider catalog can lag the operational research universe. Keep
        # exact/common stored securities discoverable while catalog ingestion catches up.
        if normalized and not rows:
            rows = conn.execute(
                """SELECT ticker,coalesce(company_name,ticker) AS name,NULL::text AS exchange,
                CASE WHEN asset_type='etf' THEN 'etf' ELSE 'common_stock' END AS instrument_type,
                'USD'::text AS currency,NULL::date AS active_from,NULL::date AS active_to,active,
                'core_us'::text AS coverage_tier,
                jsonb_build_object('source','operational_securities') AS provider_mappings,
                updated_at AS verified_at
                FROM public.securities
                WHERE active=true AND (ticker ILIKE %s OR company_name ILIKE %s)
                ORDER BY CASE WHEN upper(ticker)=upper(%s) THEN 0 ELSE 1 END,ticker
                LIMIT %s""",
                (pattern, pattern, normalized, max(1, min(limit, 200))),
            ).fetchall()
    results = [{**dict(row), "active_from": _iso(row["active_from"]), "active_to": _iso(row["active_to"]), "verified_at": _iso(row["verified_at"])} for row in rows]
    exact = next((row for row in results if row["ticker"].upper() == normalized.upper()), None)
    reason = None
    if normalized and not results:
        reason = "Not found in the supported active U.S. stock and ETF master. ADR, OTC, international, private, delisted, or newly listed coverage may be conditional or unavailable."
    elif exact and exact["coverage_tier"] != "core_us":
        reason = f"{exact['ticker']} is in the {exact['coverage_tier'].replace('_', ' ')} tier; provider and field coverage must be verified before research use."
    return {
        "query": query,
        "scope": "Active U.S.-listed common stocks and ETFs are core; ADR, OTC, international, and delisted identifiers are separate conditional tiers.",
        "results": results, "unsupported_reason": reason,
    }


def resolve_security_mentions(text: str, limit: int = 5) -> list[dict[str, Any]]:
    """Resolve company names contained in natural language without guessing symbols."""
    if not DATABASE_URL or not text.strip():
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT ticker,name FROM public.security_master
               WHERE active=true AND length(name)>=4
                 AND lower(%s) LIKE '%%' || lower(name) || '%%'
               ORDER BY length(name) DESC,ticker LIMIT %s""",
            (text, max(1, min(limit, 10))),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                """SELECT ticker,coalesce(company_name,ticker) AS name FROM public.securities
                   WHERE active=true AND length(coalesce(company_name,''))>=4
                     AND lower(%s) LIKE '%%' || lower(company_name) || '%%'
                   ORDER BY length(company_name) DESC,ticker LIMIT %s""",
                (text, max(1, min(limit, 10))),
            ).fetchall()
    return [{"ticker": str(row["ticker"]).upper(), "name": row["name"]} for row in rows]


def validate_security_tickers(tickers: list[str]) -> set[str]:
    normalized = sorted(set(str(value).upper() for value in tickers if value))
    if not DATABASE_URL or not normalized:
        return set()
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT upper(ticker) ticker FROM public.security_master WHERE active=true AND upper(ticker)=ANY(%s)
               UNION SELECT upper(ticker) FROM public.securities WHERE active=true AND upper(ticker)=ANY(%s)""",
            (normalized, normalized),
        ).fetchall()
    return {str(row["ticker"]).upper() for row in rows}


def sync_security_master(tickers: list[str] | None = None) -> int:
    """Promote provider-validated security records into the explicit support catalog."""
    if not DATABASE_URL:
        return 0
    normalized = sorted({value.upper() for value in (tickers or []) if value})
    with postgres_connection() as conn:
        rows = conn.execute(
            """INSERT INTO public.security_master(ticker,name,instrument_type,coverage_tier,active,provider_mappings,verified_at)
            SELECT DISTINCT ON (ticker) ticker,coalesce(company_name,ticker),
              CASE WHEN asset_type='etf' THEN 'etf' ELSE 'common_stock' END,
              'core_us',active,jsonb_build_object('securities_asset_type',asset_type),updated_at
            FROM public.securities
            WHERE (%s::text[] IS NULL OR ticker=ANY(%s))
            ORDER BY ticker,updated_at DESC
            ON CONFLICT (ticker) DO UPDATE SET name=excluded.name,active=excluded.active,
              verified_at=excluded.verified_at,provider_mappings=public.security_master.provider_mappings || excluded.provider_mappings,
              updated_at=now() RETURNING ticker""",
            (normalized or None, normalized or None),
        ).fetchall()
    return len(rows)


def save_security_coverage_snapshots(rows: list[dict[str, Any]]) -> int:
    if not DATABASE_URL or not rows:
        return 0
    inserted = 0
    with postgres_connection() as conn:
        for row in rows:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker or not conn.execute("SELECT 1 FROM public.security_master WHERE ticker=%s", (ticker,)).fetchone():
                continue
            coverage = row.get("component_coverage") or {}
            missing = [key for key, value in coverage.items() if not value]
            price = {"status": "available" if row.get("price_as_of") else "missing", "as_of": row.get("price_as_of")}
            fundamentals = {"status": "available" if row.get("fundamentals_as_of") else "missing", "as_of": row.get("fundamentals_as_of")}
            valuation = row.get("valuation_evidence") or {"status": "missing"}
            conn.execute(
                """INSERT INTO public.security_coverage_snapshots(ticker,adjusted_prices,fundamentals,
                classification,earnings,valuation,news,usable_history_months,missing_fields,provider_lineage)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ticker, _jsonb(price), _jsonb(fundamentals),
                 _jsonb({"sector": row.get("sector"), "industry": row.get("industry"), "status": "available" if coverage.get("industry_position") else "missing"}),
                 _jsonb({"status": "unknown"}), _jsonb(valuation),
                 _jsonb({"status": "available" if row.get("news_count") else "missing", "count": row.get("news_count") or 0}),
                 0, missing, _jsonb([{"provider": row.get("data_source"), "dataset": "research evidence"}])),
            )
            inserted += 1
    return inserted


def ensure_investment_account(user_id: str, account_reference: str) -> str:
    if not DATABASE_URL:
        return account_reference
    with postgres_connection() as conn:
        row = None
        try:
            account_uuid = str(uuid.UUID(account_reference))
            row = conn.execute("SELECT id FROM public.investment_accounts WHERE id=%s AND user_id=%s", (account_uuid, user_id)).fetchone()
        except ValueError:
            row = None
        if row:
            return str(row["id"])
        created = conn.execute(
            """INSERT INTO public.investment_accounts(user_id,name,account_type,metadata)
            VALUES (%s,%s,'other',%s) RETURNING id""",
            (user_id, account_reference[:120], _jsonb({"created_from": "transaction_import"})),
        ).fetchone()
    return str(created["id"])


def save_portfolio_transactions(user_id: str, account_reference: str, transactions: list[dict[str, Any]]) -> dict[str, Any]:
    if not DATABASE_URL:
        return {"account_id": account_reference, "inserted": len(transactions), "duplicates": 0, "storage": "fixture"}
    account_id = ensure_investment_account(user_id, account_reference)
    inserted = duplicates = 0
    with postgres_connection() as conn:
        for row in transactions:
            external_id = row.get("external_id") or f"import:{row['trade_date']}:{row['transaction_type']}:{row.get('ticker')}:{row.get('quantity')}:{row.get('price')}:{row.get('amount')}:{row.get('fee')}"
            result = conn.execute(
                """INSERT INTO public.portfolio_transactions(
                user_id,account_id,external_id,trade_date,transaction_type,ticker,quantity,price,amount,fee,currency,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (user_id,account_id,external_id) DO NOTHING RETURNING id""",
                (user_id, account_id, external_id, row["trade_date"], row["transaction_type"], row.get("ticker"), row.get("quantity"), row.get("price"), row.get("amount"), row.get("fee") or 0, row.get("currency") or "USD", _jsonb({"source_row": row.get("source_row")})),
            ).fetchone()
            if result: inserted += 1
            else: duplicates += 1
    return {"account_id": account_id, "inserted": inserted, "duplicates": duplicates, "storage": "supabase"}


def account_transactions(user_id: str, account_id: str) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT trade_date,transaction_type,ticker,quantity,price,amount,fee,currency,external_id
            FROM public.portfolio_transactions WHERE user_id=%s AND account_id=%s
            ORDER BY trade_date,id""", (user_id, account_id),
        ).fetchall()
    return [{**dict(row), "trade_date": _iso(row["trade_date"]), **{key: _number(row[key]) for key in ("quantity", "price", "amount", "fee")}} for row in rows]


def save_statement_reconciliation(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    market_difference = float(payload["reconstructed_market_value"]) - float(payload["statement_market_value"])
    cash_difference = float(payload["reconstructed_cash"]) - float(payload["statement_cash"])
    status = "reconciled" if abs(market_difference) <= payload["tolerance"] and abs(cash_difference) <= payload["tolerance"] else "difference"
    result = {**payload, "market_value_difference": market_difference, "cash_difference": cash_difference, "status": status}
    if DATABASE_URL:
        account_id = ensure_investment_account(user_id, payload["account_id"])
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.statement_reconciliations(user_id,account_id,statement_date,
                statement_market_value,statement_cash,reconstructed_market_value,reconstructed_cash,tolerance,status,differences)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user_id, account_id, payload["statement_date"], payload["statement_market_value"], payload["statement_cash"], payload["reconstructed_market_value"], payload["reconstructed_cash"], payload["tolerance"], status, _jsonb({"market_value": market_difference, "cash": cash_difference})),
            )
        result["account_id"] = account_id
    return result


def fund_reference_data(tickers: list[str]) -> dict[str, Any]:
    normalized = sorted({ticker.upper() for ticker in tickers if ticker and ticker.upper() != "CASH"})
    if not DATABASE_URL or not normalized:
        return {"funds": [], "holdings": []}
    with postgres_connection() as conn:
        funds = conn.execute(
            """SELECT ticker, expense_ratio, provider, source_url, effective_at, metadata
            FROM public.fund_reference_data WHERE ticker=ANY(%s)""", (normalized,),
        ).fetchall()
        holdings = conn.execute(
            """SELECT h.fund_ticker, h.constituent_ticker, h.weight, h.as_of, h.provider, h.source_url
            FROM public.fund_holdings h
            JOIN (SELECT fund_ticker, max(as_of) AS as_of FROM public.fund_holdings
                  WHERE fund_ticker=ANY(%s) GROUP BY fund_ticker) latest
              ON latest.fund_ticker=h.fund_ticker AND latest.as_of=h.as_of
            ORDER BY h.fund_ticker, h.weight DESC""", (normalized,),
        ).fetchall()
    return {
        "funds": [{**dict(row), "expense_ratio": _number(row["expense_ratio"]), "effective_at": _iso(row["effective_at"])} for row in funds],
        "holdings": [{**dict(row), "weight": _number(row["weight"]), "as_of": _iso(row["as_of"])} for row in holdings],
    }


def save_fund_reference_snapshot(
    ticker: str,
    expense_ratio: float | None,
    provider: str,
    source_url: str,
    effective_at: str,
    holdings: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a validated current ETF snapshot without rewriting historical dates."""
    if not DATABASE_URL:
        return
    normalized = ticker.upper()
    with postgres_connection() as conn:
        conn.execute(
            """INSERT INTO public.securities(ticker, asset_type, company_name, sector, industry)
            VALUES (%s,'etf',%s,'Broad Market','ETF')
            ON CONFLICT (ticker, asset_type) DO UPDATE SET
              company_name=excluded.company_name, updated_at=now()""",
            (normalized, str((metadata or {}).get("name") or normalized)),
        )
        conn.execute(
            """INSERT INTO public.fund_reference_data(ticker,expense_ratio,provider,source_url,effective_at,metadata)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker) DO UPDATE SET expense_ratio=excluded.expense_ratio,
              provider=excluded.provider,source_url=excluded.source_url,effective_at=excluded.effective_at,
              metadata=excluded.metadata,updated_at=now()""",
            (normalized, expense_ratio, provider, source_url, effective_at, _jsonb(metadata or {})),
        )
        holding_values = []
        for item in holdings:
            constituent = str(item.get("ticker") or "").strip().upper()
            if not constituent:
                continue
            holding_values.append((normalized, constituent, float(item["weight"]), item["as_of"], provider, source_url, _jsonb(item.get("metadata") or {})))
        if holding_values:
            with conn.cursor() as cursor:
                cursor.executemany(
                """INSERT INTO public.fund_holdings(
                fund_ticker,constituent_ticker,weight,as_of,provider,source_url,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (fund_ticker,constituent_ticker,as_of) DO UPDATE SET
                  weight=excluded.weight,provider=excluded.provider,source_url=excluded.source_url,
                  metadata=excluded.metadata""",
                    holding_values,
                )


def upsert_etf_catalog(rows: list[dict[str, Any]]) -> int:
    """Upsert reference metadata while preserving provider-specific fields in metadata."""
    if not DATABASE_URL or not rows:
        return 0
    values = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        if not ticker or not name:
            continue
        values.append((
            ticker, name, row.get("issuer"), row.get("asset_class"), row.get("category"),
            row.get("strategy"), row.get("benchmark"), row.get("expense_ratio"),
            row.get("holdings_count"), row.get("inception_date"), row.get("primary_exchange"),
            row.get("currency") or "USD", bool(row.get("active", True)), row.get("provider") or "unknown",
            row.get("source_url"), row.get("effective_at") or utc_now(), _jsonb(row.get("metadata") or {}),
        ))
    if not values:
        return 0
    with postgres_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO public.etf_catalog(
              ticker,name,issuer,asset_class,category,strategy,benchmark,expense_ratio,
              holdings_count,inception_date,primary_exchange,currency,active,provider,source_url,effective_at,metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker) DO UPDATE SET
              name=excluded.name, issuer=coalesce(excluded.issuer,public.etf_catalog.issuer),
              asset_class=coalesce(excluded.asset_class,public.etf_catalog.asset_class),
              category=coalesce(excluded.category,public.etf_catalog.category),
              strategy=coalesce(excluded.strategy,public.etf_catalog.strategy),
              benchmark=coalesce(excluded.benchmark,public.etf_catalog.benchmark),
              expense_ratio=coalesce(excluded.expense_ratio,public.etf_catalog.expense_ratio),
              holdings_count=coalesce(excluded.holdings_count,public.etf_catalog.holdings_count),
              inception_date=coalesce(excluded.inception_date,public.etf_catalog.inception_date),
              primary_exchange=coalesce(excluded.primary_exchange,public.etf_catalog.primary_exchange),
              currency=excluded.currency, active=excluded.active, provider=excluded.provider,
              source_url=coalesce(excluded.source_url,public.etf_catalog.source_url),
              effective_at=excluded.effective_at, metadata=public.etf_catalog.metadata || excluded.metadata,
              updated_at=now()""",
                values,
            )
            cursor.executemany(
                """INSERT INTO public.securities(ticker,asset_type,company_name,exchange,currency,provider_ids,active)
            VALUES (%s,'etf',%s,%s,%s,%s,%s)
            ON CONFLICT (ticker,asset_type) DO UPDATE SET company_name=excluded.company_name,
              exchange=coalesce(excluded.exchange,public.securities.exchange), currency=excluded.currency,
              provider_ids=public.securities.provider_ids || excluded.provider_ids,
              active=excluded.active,updated_at=now()""",
                [(value[0], value[1], value[10], value[11], _jsonb({"catalog_provider": value[13]}), value[12]) for value in values],
            )
    return len(values)


def search_etf_catalog(query: str = "", issuer: str = "", category: str = "", limit: int = 50) -> dict[str, Any]:
    if not DATABASE_URL:
        return {"results": [], "summary": {"total": 0, "issuers": 0, "with_holdings": 0}}
    clauses = ["c.active=true"]
    params: list[Any] = []
    if query.strip():
        clauses.append("(c.ticker ILIKE %s OR c.name ILIKE %s OR coalesce(c.issuer,'') ILIKE %s)")
        pattern = f"%{query.strip()}%"
        params.extend([pattern, pattern, pattern])
    if issuer.strip():
        clauses.append("coalesce(c.issuer,'') ILIKE %s")
        params.append(f"%{issuer.strip()}%")
    if category.strip():
        clauses.append("coalesce(c.category,'') ILIKE %s")
        params.append(f"%{category.strip()}%")
    where = " AND ".join(clauses)
    params.append(limit)
    with postgres_connection() as conn:
        rows = conn.execute(
            f"""SELECT c.*, latest.as_of AS holdings_as_of, latest.holdings_count AS snapshot_holdings_count,
              latest.provider AS holdings_provider
            FROM public.etf_catalog c
            LEFT JOIN LATERAL (
              SELECT as_of, count(*)::integer AS holdings_count, max(provider) AS provider
              FROM public.fund_holdings WHERE fund_ticker=c.ticker GROUP BY as_of ORDER BY as_of DESC LIMIT 1
            ) latest ON true
            WHERE {where}
            ORDER BY CASE WHEN upper(c.ticker)=upper(%s) THEN 0 ELSE 1 END, c.ticker LIMIT %s""",
            (*params[:-1], query.strip(), params[-1]),
        ).fetchall()
        summary = conn.execute(
            """SELECT count(*)::integer AS total, count(distinct issuer)::integer AS issuers,
            count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.fund_holdings h WHERE h.fund_ticker=c.ticker))::integer AS with_holdings
            FROM public.etf_catalog c WHERE active=true"""
        ).fetchone()
    results = []
    for row in rows:
        item = dict(row)
        for key in ("expense_ratio",): item[key] = _number(item.get(key))
        for key in ("effective_at", "created_at", "updated_at", "holdings_as_of", "inception_date"): item[key] = _iso(item.get(key))
        results.append(item)
    return {"results": results, "summary": dict(summary)}


def etf_catalog_entry(ticker: str) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    with postgres_connection() as conn:
        row = conn.execute("SELECT * FROM public.etf_catalog WHERE ticker=%s", (ticker.upper(),)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["expense_ratio"] = _number(item.get("expense_ratio"))
    for key in ("effective_at", "created_at", "updated_at", "inception_date"): item[key] = _iso(item.get(key))
    return item


def etf_research_detail(ticker: str, portfolio_tickers: list[str] | None = None) -> dict[str, Any] | None:
    catalog = etf_catalog_entry(ticker)
    if not catalog:
        return None
    normalized = ticker.upper()
    portfolio_set = {value.upper() for value in (portfolio_tickers or [])}
    with postgres_connection() as conn:
        holdings = conn.execute(
            """SELECT fund_ticker,constituent_ticker,weight,as_of,provider,source_url,metadata
            FROM public.fund_holdings WHERE fund_ticker=%s AND as_of=(SELECT max(as_of) FROM public.fund_holdings WHERE fund_ticker=%s)
            ORDER BY weight DESC""", (normalized, normalized),
        ).fetchall()
        exposures = conn.execute(
            """SELECT exposure_type,exposure_name,weight,as_of,provider,source_url,metadata
            FROM public.etf_exposures WHERE fund_ticker=%s AND as_of=(SELECT max(as_of) FROM public.etf_exposures WHERE fund_ticker=%s)
            ORDER BY exposure_type,weight DESC""", (normalized, normalized),
        ).fetchall()
        fund_overlap = conn.execute(
            """WITH target AS (
              SELECT constituent_ticker,weight FROM public.fund_holdings
              WHERE fund_ticker=%s AND as_of=(SELECT max(as_of) FROM public.fund_holdings WHERE fund_ticker=%s)
            ), other AS (
              SELECT h.fund_ticker,h.constituent_ticker,h.weight FROM public.fund_holdings h
              JOIN (SELECT fund_ticker,max(as_of) AS as_of FROM public.fund_holdings
                    WHERE fund_ticker=ANY(%s) GROUP BY fund_ticker) latest
                ON latest.fund_ticker=h.fund_ticker AND latest.as_of=h.as_of
            ) SELECT other.fund_ticker, sum(least(target.weight,other.weight)) AS overlap_weight,
              count(*)::integer AS shared_holdings
            FROM target JOIN other USING (constituent_ticker)
            WHERE other.fund_ticker<>%s GROUP BY other.fund_ticker ORDER BY overlap_weight DESC""",
            (normalized, normalized, sorted(portfolio_set) or ["__NONE__"], normalized),
        ).fetchall()
    holding_rows = [{**dict(row), "weight": _number(row["weight"]), "as_of": _iso(row["as_of"])} for row in holdings]
    weights = [float(row["weight"] or 0) for row in holding_rows]
    explained_weight = sum(weights)
    top_ten = sum(weights[:10])
    hhi = sum(weight * weight for weight in weights)
    direct_overlap = [row for row in holding_rows if row["constituent_ticker"] in portfolio_set]
    return {
        "catalog": catalog,
        "holdings": holding_rows,
        "exposures": [{**dict(row), "weight": _number(row["weight"]), "as_of": _iso(row["as_of"])} for row in exposures],
        "concentration": {
            "holdings_count": len(holding_rows), "top_10_weight": top_ten,
            "largest_holding": holding_rows[0] if holding_rows else None,
            "hhi": hhi, "effective_holdings": (1 / hhi if hhi else None),
        },
        "snapshot_coverage": {
            "reported_weight": explained_weight,
            "coverage_percentage": min(1.0, explained_weight),
            "unexplained_weight": max(0.0, 1.0 - explained_weight),
            "over_reported_weight": max(0.0, explained_weight - 1.0),
            "within_tolerance": abs(explained_weight - 1.0) <= .02,
            "tolerance": .02,
            "treatment": "Cash, derivatives, and other exposure remain explicit constituents when supplied; unexplained weight is never redistributed.",
        },
        "portfolio_overlap": {
            "weight": sum(float(row["weight"] or 0) for row in direct_overlap), "holdings": direct_overlap,
            "funds": [{"ticker": row["fund_ticker"], "overlap_weight": _number(row["overlap_weight"]), "shared_holdings": row["shared_holdings"]} for row in fund_overlap],
        },
    }


def save_etf_exposures(ticker: str, as_of: str, exposures: list[dict[str, Any]], provider: str, source_url: str | None) -> int:
    if not DATABASE_URL or not exposures:
        return 0
    with postgres_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO public.etf_exposures(fund_ticker,exposure_type,exposure_name,weight,as_of,provider,source_url,metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (fund_ticker,exposure_type,exposure_name,as_of) DO UPDATE SET
              weight=excluded.weight,provider=excluded.provider,source_url=excluded.source_url,metadata=excluded.metadata""",
                [(ticker.upper(), row["type"], row["name"], row["weight"], as_of, provider, source_url, _jsonb(row.get("metadata") or {})) for row in exposures],
            )
    return len(exposures)


def rebuild_etf_sector_exposures(ticker: str, as_of: str, source_url: str | None = None) -> int:
    """Create a transparent look-through sector rollup; unclassified weight stays visible."""
    if not DATABASE_URL:
        return 0
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT coalesce(s.sector,'Unclassified') AS name, sum(h.weight) AS weight
            FROM public.fund_holdings h
            LEFT JOIN LATERAL (
              SELECT sector FROM public.securities WHERE ticker=h.constituent_ticker
              ORDER BY CASE WHEN asset_type='stock' THEN 0 ELSE 1 END LIMIT 1
            ) s ON true
            WHERE h.fund_ticker=%s AND h.as_of=%s
            GROUP BY coalesce(s.sector,'Unclassified') ORDER BY weight DESC""",
            (ticker.upper(), as_of),
        ).fetchall()
    exposures = [{"type": "sector", "name": row["name"], "weight": min(1.0, float(row["weight"]))} for row in rows if row["weight"] is not None]
    return save_etf_exposures(ticker, as_of, exposures, "EagleEyes look-through", source_url)


def record_etf_refresh(provider: str, run_type: str, status: str, ticker: str | None = None, row_count: int = 0, error: str | None = None, metadata: dict[str, Any] | None = None) -> str | None:
    if not DATABASE_URL:
        return None
    with postgres_connection() as conn:
        row = conn.execute(
            """INSERT INTO public.etf_refresh_runs(provider,run_type,ticker,status,row_count,completed_at,error_message,metadata)
            VALUES (%s,%s,%s,%s,%s,CASE WHEN %s='started' THEN null ELSE now() END,%s,%s) RETURNING id""",
            (provider, run_type, ticker, status, row_count, status, error, _jsonb(metadata or {})),
        ).fetchone()
    return str(row["id"])


def research_reference_data(tickers: list[str]) -> dict[str, Any]:
    """Load additive classifications, fund look-through, and dated catalysts for Research."""
    normalized = sorted({ticker.upper() for ticker in tickers if ticker and ticker.upper() != "CASH"})
    empty = {"funds": [], "fund_holdings": [], "containing_funds": [], "memberships": [], "events": []}
    if not DATABASE_URL or not normalized:
        return empty
    try:
        with postgres_connection() as conn:
            funds = conn.execute(
                """SELECT ticker, expense_ratio, provider, source_url, effective_at, metadata
                FROM public.fund_reference_data WHERE ticker=ANY(%s)""", (normalized,),
            ).fetchall()
            fund_holdings = conn.execute(
                """SELECT fund_ticker, constituent_ticker, weight, as_of, provider, source_url
                FROM public.fund_holdings WHERE fund_ticker=ANY(%s)
                ORDER BY fund_ticker, as_of DESC, weight DESC""", (normalized,),
            ).fetchall()
            containing = conn.execute(
                """SELECT fund_ticker, constituent_ticker, weight, as_of, provider, source_url
                FROM public.fund_holdings WHERE constituent_ticker=ANY(%s)
                ORDER BY constituent_ticker, as_of DESC, weight DESC""", (normalized,),
            ).fetchall()
            memberships = conn.execute(
                """SELECT security_ticker, collection_type, collection_name, weight, as_of,
                provider, source_url FROM public.security_memberships
                WHERE security_ticker=ANY(%s)
                ORDER BY security_ticker, collection_type, as_of DESC""", (normalized,),
            ).fetchall()
    except psycopg.Error:
        return empty
    return {
        "funds": [{**dict(row), "expense_ratio": _number(row["expense_ratio"]), "effective_at": _iso(row["effective_at"])} for row in funds],
        "fund_holdings": [{**dict(row), "weight": _number(row["weight"]), "as_of": _iso(row["as_of"])} for row in fund_holdings],
        "containing_funds": [{**dict(row), "weight": _number(row["weight"]), "as_of": _iso(row["as_of"])} for row in containing],
        "memberships": [{**dict(row), "weight": _number(row["weight"]), "as_of": _iso(row["as_of"])} for row in memberships],
        "events": upcoming_market_events(normalized, 90),
    }


def save_security_prediction_markets(
    ticker: str, company_name: str, markets: list[dict[str, Any]]
) -> int:
    if not DATABASE_URL or not markets:
        return 0
    observed_at = utc_now()
    with postgres_connection() as conn:
        conn.execute(
            """INSERT INTO public.securities(ticker, asset_type, company_name)
            VALUES (%s, 'stock', %s)
            ON CONFLICT (ticker, asset_type) DO UPDATE SET
              company_name=coalesce(public.securities.company_name, excluded.company_name),
              updated_at=now()
            RETURNING id""",
            (ticker.upper(), company_name or ticker.upper()),
        ).fetchone()
        for market in markets:
            market_id = conn.execute(
                """INSERT INTO public.prediction_markets(
                provider, external_market_id, canonical_question, canonical_scenario,
                title, source_url, closes_at, metadata
                ) VALUES ('polymarket', %s, %s, NULL, %s, %s, %s, %s)
                ON CONFLICT (provider, external_market_id) DO UPDATE SET
                  canonical_question=excluded.canonical_question,
                  title=excluded.title, source_url=excluded.source_url,
                  closes_at=excluded.closes_at, metadata=excluded.metadata,
                  updated_at=now()
                RETURNING id""",
                (
                    market["id"], market["title"], market["title"], market.get("source"),
                    market.get("closes_at"),
                    _jsonb({
                        "ticker": ticker.upper(), "token_ids": market.get("token_ids"),
                        "evidence_type": market.get("evidence_type", "business catalyst"),
                        "scope": "security_research",
                    }),
                ),
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO public.prediction_market_snapshots(
                market_id, observed_at, probability, volume, confidence, raw_payload
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (market_id, observed_at) DO UPDATE SET
                  probability=excluded.probability, volume=excluded.volume,
                  confidence=excluded.confidence, raw_payload=excluded.raw_payload""",
                (
                    market_id, observed_at, market["probability"], market.get("volume"),
                    market.get("confidence"), _jsonb(market),
                ),
            )
    return len(markets)


def prediction_market_observations(limit: int = 200) -> list[dict[str, Any]]:
    """Return latest normalized venue observations with bounded immutable history.

    Provider refresh remains owned by the existing ingestion services. This is
    the reusable read model used by forecasting, evidence, research, and Ask.
    """
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM (
                  SELECT pm.id AS internal_market_id, pm.provider,
                  pm.external_market_id AS market_id, pm.canonical_question,
                  pm.canonical_scenario, pm.title, pm.source_url, pm.opens_at,
                  pm.closes_at, pm.resolution_at, pm.resolved_outcome, pm.metadata,
                  pcs.canonical_key AS series_key,
                  pms.probability, pms.bid, pms.ask, pms.volume,
                  pms.open_interest, pms.order_book_depth AS liquidity,
                  pms.confidence, pms.observed_at, pms.raw_payload,
                  row_number() over (partition by pm.id order by pms.observed_at desc) AS position
                  FROM public.prediction_markets pm
                  JOIN public.prediction_market_snapshots pms ON pms.market_id=pm.id
                  LEFT JOIN public.prediction_contract_series pcs ON pcs.id=pm.series_id
                ) latest WHERE position=1
                ORDER BY observed_at DESC LIMIT %s""", (limit,),
            ).fetchall()
            ids = [row["internal_market_id"] for row in rows]
            history_rows = [] if not ids else conn.execute(
                """SELECT market_id, probability, observed_at FROM public.prediction_market_snapshots
                WHERE market_id=ANY(%s) ORDER BY market_id, observed_at DESC LIMIT %s""",
                (ids, max(1000, limit * 30)),
            ).fetchall()
        histories: dict[str, list[dict[str, Any]]] = {}
        for row in history_rows:
            histories.setdefault(str(row["market_id"]), []).append({
                "probability": _number(row["probability"]), "observed_at": _iso(row["observed_at"]),
            })
        result = []
        for row in rows:
            raw = dict(row)
            metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            payload = raw.get("raw_payload") if isinstance(raw.get("raw_payload"), dict) else {}
            result.append({
                **raw, "internal_market_id": str(raw["internal_market_id"]),
                "observed_at": _iso(raw["observed_at"]), "opens_at": _iso(raw.get("opens_at")),
                "closes_at": _iso(raw.get("closes_at")), "resolution_date": _iso(raw.get("resolution_at") or raw.get("closes_at")),
                "probability": _number(raw.get("probability")), "bid": _number(raw.get("bid")),
                "ask": _number(raw.get("ask")), "volume": _number(raw.get("volume")),
                "liquidity": _number(raw.get("liquidity")), "metadata": metadata,
                "description": metadata.get("description") or payload.get("description"),
                "resolution_criteria": metadata.get("resolution_criteria") or payload.get("rules") or payload.get("resolutionSource"),
                "status": metadata.get("status") or payload.get("status"),
                "history": histories.get(str(raw["internal_market_id"]), []),
            })
        return result

    snapshots = scenario_history()
    latest = latest_scenario_snapshot() or {}
    result = []
    for contract in latest.get("contracts", [])[:limit]:
        provider, market_id = str(contract.get("provider") or "Unknown"), str(contract.get("id") or "")
        history = []
        for snapshot in snapshots:
            match = next((row for row in snapshot.get("contracts", [])
                          if str(row.get("provider")) == provider and str(row.get("id")) == market_id), None)
            if match and match.get("probability") is not None:
                history.append({"probability": match["probability"], "observed_at": snapshot["fetched_at"]})
        result.append({
            **contract, "market_id": market_id, "observed_at": latest.get("fetched_at"),
            "canonical_scenario": contract.get("scenario"), "metadata": {
                "canonical_scenario": contract.get("scenario"), "indicator": contract.get("indicator")
            }, "history": history, "resolution_date": contract.get("closes_at"),
        })
    return result


def save_user_forecast(user_id: str, forecast: dict[str, Any]) -> dict[str, Any]:
    forecast_id, now = str(uuid.uuid4()), forecast.get("observed_at") or utc_now()
    values = (
        forecast_id, user_id, forecast["event_key"], forecast.get("provider"), forecast.get("market_id"),
        forecast["title"], forecast["probability"], forecast.get("reasoning", ""),
        forecast.get("market_probability_at_entry"), forecast.get("model_probability_at_entry"),
        forecast.get("forecast_horizon"), now, utc_now(),
    )
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.user_forecasts(
                id,user_id,event_key,provider,external_market_id,title,probability,reasoning,
                market_probability_at_entry,model_probability_at_entry,forecast_horizon,observed_at,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", values,
            ).fetchone()
        return {**dict(row), "id": str(row["id"]), "observed_at": _iso(row["observed_at"]), "created_at": _iso(row["created_at"])}
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO user_forecasts(
            id,user_id,event_key,provider,external_market_id,title,probability,reasoning,
            market_probability_at_entry,model_probability_at_entry,forecast_horizon,observed_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", values,
        )
    return next(row for row in list_user_forecasts(user_id) if row["id"] == forecast_id)


def list_user_forecasts(user_id: str, event_key: str | None = None) -> list[dict[str, Any]]:
    postgres, prefix, placeholder = bool(DATABASE_URL), "public." if DATABASE_URL else "", "%s" if DATABASE_URL else "?"
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    where, params = f"uf.user_id={placeholder}", [user_id]
    if event_key:
        where += f" AND uf.event_key={placeholder}"
        params.append(event_key)
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT uf.*, fre.outcome AS resolved_outcome, fre.resolved_at,
            fre.resolution_reference FROM {prefix}user_forecasts uf
            LEFT JOIN {prefix}forecast_resolution_events fre ON fre.event_key=uf.event_key
              AND (fre.provider IS NULL OR fre.provider=uf.provider)
              AND (fre.external_market_id IS NULL OR fre.external_market_id=uf.external_market_id)
            WHERE {where} ORDER BY uf.observed_at DESC""", tuple(params),
        ).fetchall()
    return [{**dict(row), "id": str(row["id"]), "observed_at": _iso(row["observed_at"]),
             "created_at": _iso(row["created_at"]), "resolved_at": _iso(row["resolved_at"]),
             "probability": _number(row["probability"]),
             "market_probability_at_entry": _number(row["market_probability_at_entry"]),
             "model_probability_at_entry": _number(row["model_probability_at_entry"]),
             "resolved_outcome": _number(row["resolved_outcome"])} for row in rows]


def save_forecast_resolution(event_key: str, outcome: float, resolved_at: str, *,
                             provider: str | None = None, market_id: str | None = None,
                             reference: str | None = None) -> str:
    resolution_id = str(uuid.uuid4())
    prefix, placeholders = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        conn.execute(
            f"""INSERT INTO {prefix}forecast_resolution_events(
            id,event_key,provider,external_market_id,outcome,resolution_reference,resolved_at,recorded_at
            ) VALUES ({','.join([placeholders] * 8)})""",
            (resolution_id, event_key, provider, market_id, outcome, reference, resolved_at, utc_now()),
        )
    return resolution_id


def attention_states(user_id: str) -> dict[str, dict[str, Any]]:
    prefix, placeholder = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT attention_item_id,state,snoozed_until,note,updated_at
            FROM {prefix}attention_item_states WHERE user_id={placeholder}""", (user_id,),
        ).fetchall()
    return {str(row["attention_item_id"]): {
        "state": row["state"], "snoozed_until": _iso(row["snoozed_until"]),
        "note": row["note"], "updated_at": _iso(row["updated_at"]),
    } for row in rows}


def save_attention_state(user_id: str, attention_item_id: str, state: str,
                         snoozed_until: str | None = None, note: str = "") -> dict[str, Any]:
    now, item_id = utc_now(), str(uuid.uuid4())
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.attention_item_states(
                id,user_id,attention_item_id,state,snoozed_until,note,created_at,updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(user_id,attention_item_id) DO UPDATE SET
                state=excluded.state,snoozed_until=excluded.snoozed_until,note=excluded.note,updated_at=excluded.updated_at
                RETURNING attention_item_id,state,snoozed_until,note,updated_at""",
                (item_id, user_id, attention_item_id, state, snoozed_until, note, now, now),
            ).fetchone()
        return {**dict(row), "snoozed_until": _iso(row["snoozed_until"]), "updated_at": _iso(row["updated_at"])}
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO attention_item_states(
            id,user_id,attention_item_id,state,snoozed_until,note,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,attention_item_id) DO UPDATE SET
            state=excluded.state,snoozed_until=excluded.snoozed_until,note=excluded.note,updated_at=excluded.updated_at""",
            (item_id, user_id, attention_item_id, state, snoozed_until, note, now, now),
        )
    return attention_states(user_id)[attention_item_id]


def delete_attention_state(user_id: str, attention_item_id: str) -> None:
    prefix, placeholder = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        conn.execute(
            f"DELETE FROM {prefix}attention_item_states WHERE user_id={placeholder} AND attention_item_id={placeholder}",
            (user_id, attention_item_id),
        )


def save_portfolio_health_snapshot(user_id: str, portfolio_id: str | int, result: dict[str, Any],
                                   trigger: str, snapshot_hash: str) -> dict[str, Any]:
    now = utc_now()
    snapshot_id = str(uuid.uuid4())
    health = result.get("health") or {}
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.portfolio_health_snapshots(
                id,user_id,portfolio_id,snapshot_date,trigger,input_hash,health_score,health_band,
                confidence,coverage,components,holding_metrics,changes,warnings,result,
                methodology_version,effective_at,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(user_id,portfolio_id,trigger,input_hash) DO UPDATE SET
                effective_at=excluded.effective_at,result=excluded.result,changes=excluded.changes,warnings=excluded.warnings
                RETURNING id,result,effective_at,trigger,input_hash""",
                (snapshot_id, user_id, portfolio_id, now[:10], trigger, snapshot_hash,
                 health.get("score", 0), health.get("band", "Critical"), health.get("confidence", "Low"),
                 health.get("coverage", 0), _jsonb(health.get("components", {})), _jsonb(result.get("holdings", [])),
                 _jsonb(result.get("changes", [])), _jsonb(result.get("warnings", [])), _jsonb(result),
                 result.get("version", "portfolio-health-v1"), result.get("as_of", now), now),
            ).fetchone()
        return {"id": str(row["id"]), "result": row["result"], "effective_at": _iso(row["effective_at"]),
                "trigger": row["trigger"], "input_hash": row["input_hash"]}
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO portfolio_health_snapshots(
            id,user_id,portfolio_id,snapshot_date,trigger,input_hash,health_score,health_band,confidence,
            coverage,components_json,holding_metrics_json,changes_json,warnings_json,result_json,
            methodology_version,effective_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,portfolio_id,trigger,input_hash) DO UPDATE SET
            effective_at=excluded.effective_at,result_json=excluded.result_json,
            changes_json=excluded.changes_json,warnings_json=excluded.warnings_json""",
            (snapshot_id, user_id, str(portfolio_id), now[:10], trigger, snapshot_hash,
             health.get("score", 0), health.get("band", "Critical"), health.get("confidence", "Low"),
             health.get("coverage", 0), json.dumps(health.get("components", {}), default=str),
             json.dumps(result.get("holdings", []), default=str), json.dumps(result.get("changes", []), default=str),
             json.dumps(result.get("warnings", []), default=str), json.dumps(result, default=str),
             result.get("version", "portfolio-health-v1"), result.get("as_of", now), now),
        )
        row = conn.execute(
            "SELECT * FROM portfolio_health_snapshots WHERE user_id=? AND portfolio_id=? AND trigger=? AND input_hash=?",
            (user_id, str(portfolio_id), trigger, snapshot_hash),
        ).fetchone()
    return {"id": row["id"], "result": json.loads(row["result_json"]), "effective_at": row["effective_at"],
            "trigger": row["trigger"], "input_hash": row["input_hash"]}


def portfolio_health_history(user_id: str, portfolio_id: str | int, limit: int = 90,
                             trigger: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 365))
    if DATABASE_URL:
        params: list[Any] = [user_id, portfolio_id]
        clause = ""
        if trigger:
            clause = " AND trigger=%s"
            params.append(trigger)
        params.append(limit)
        with postgres_connection() as conn:
            rows = conn.execute(
                f"""SELECT id,result,effective_at,trigger,input_hash FROM public.portfolio_health_snapshots
                WHERE user_id=%s AND portfolio_id=%s{clause} ORDER BY effective_at DESC,created_at DESC LIMIT %s""",
                tuple(params),
            ).fetchall()
        return [{"id": str(row["id"]), "result": row["result"], "effective_at": _iso(row["effective_at"]),
                 "trigger": row["trigger"], "input_hash": row["input_hash"]} for row in rows]
    params = [user_id, str(portfolio_id)]
    clause = ""
    if trigger:
        clause = " AND trigger=?"
        params.append(trigger)
    params.append(limit)
    with sqlite_connection() as conn:
        rows = conn.execute(
            f"""SELECT * FROM portfolio_health_snapshots WHERE user_id=? AND portfolio_id=?{clause}
            ORDER BY effective_at DESC,created_at DESC LIMIT ?""", tuple(params),
        ).fetchall()
    return [{"id": row["id"], "result": json.loads(row["result_json"]), "effective_at": row["effective_at"],
             "trigger": row["trigger"], "input_hash": row["input_hash"]} for row in rows]


def latest_portfolio_health(user_id: str, portfolio_id: str | int) -> dict[str, Any] | None:
    rows = portfolio_health_history(user_id, portfolio_id, 1)
    return rows[0] if rows else None


def sync_portfolio_actions(user_id: str, portfolio_id: str | int, actions: list[dict[str, Any]]) -> None:
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute("UPDATE public.portfolio_action_items SET active=false,updated_at=%s WHERE user_id=%s AND portfolio_id=%s", (now, user_id, portfolio_id))
            for item in actions:
                conn.execute(
                    """INSERT INTO public.portfolio_action_items(
                    id,user_id,portfolio_id,source_key,source,action_type,title,reason,payload,priority,
                    state,active,first_seen_at,last_seen_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',true,%s,%s,%s)
                    ON CONFLICT(user_id,portfolio_id,source_key) DO UPDATE SET source=excluded.source,
                    action_type=excluded.action_type,title=excluded.title,reason=excluded.reason,payload=excluded.payload,
                    priority=excluded.priority,active=true,last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at""",
                    (str(uuid.uuid4()), user_id, portfolio_id, item["source_key"], item["source"], item["action"],
                     item["title"], item["reason"], _jsonb(item), item["priority"], now, now, now),
                )
        return
    with sqlite_connection() as conn:
        conn.execute("UPDATE portfolio_action_items SET active=0,updated_at=? WHERE user_id=? AND portfolio_id=?", (now, user_id, str(portfolio_id)))
        for item in actions:
            conn.execute(
                """INSERT INTO portfolio_action_items(
                id,user_id,portfolio_id,source_key,source,action_type,title,reason,payload_json,priority,
                state,active,snoozed_until,note,first_seen_at,last_seen_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,'OPEN',1,NULL,'',?,?,?)
                ON CONFLICT(user_id,portfolio_id,source_key) DO UPDATE SET source=excluded.source,
                action_type=excluded.action_type,title=excluded.title,reason=excluded.reason,payload_json=excluded.payload_json,
                priority=excluded.priority,active=1,last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at""",
                (str(uuid.uuid4()), user_id, str(portfolio_id), item["source_key"], item["source"], item["action"],
                 item["title"], item["reason"], json.dumps(item, default=str), item["priority"], now, now, now),
            )


def portfolio_actions(user_id: str, portfolio_id: str | int, include_inactive: bool = False) -> list[dict[str, Any]]:
    prefix, placeholder = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    active_clause = "" if include_inactive else " AND active=true" if DATABASE_URL else " AND active=1"
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT * FROM {prefix}portfolio_action_items WHERE user_id={placeholder}
            AND portfolio_id={placeholder}{active_clause} ORDER BY priority DESC,last_seen_at DESC""",
            (user_id, str(portfolio_id)),
        ).fetchall()
    output = []
    now = datetime.now(timezone.utc)
    for row in rows:
        item = dict(row)
        payload = item.get("payload") if DATABASE_URL else json.loads(item.get("payload_json") or "{}")
        snoozed = _iso(item.get("snoozed_until"))
        state = item["state"]
        if state == "SNOOZED" and snoozed:
            try:
                if datetime.fromisoformat(snoozed.replace("Z", "+00:00")) <= now:
                    state = "OPEN"
            except ValueError:
                pass
        output.append({**payload, "id": str(item["id"]), "state": state, "active": bool(item["active"]),
                       "snoozed_until": snoozed, "note": item.get("note") or "",
                       "first_seen_at": _iso(item["first_seen_at"]), "last_seen_at": _iso(item["last_seen_at"])})
    return output


def save_portfolio_action_state(user_id: str, action_id: str, state: str,
                                snoozed_until: str | None = None, note: str = "") -> dict[str, Any]:
    now = utc_now()
    prefix, placeholder = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        row = conn.execute(
            f"""UPDATE {prefix}portfolio_action_items SET state={placeholder},snoozed_until={placeholder},
            note={placeholder},updated_at={placeholder} WHERE id={placeholder} AND user_id={placeholder} RETURNING portfolio_id""",
            (state, snoozed_until, note, now, action_id, user_id),
        ).fetchone()
    if row is None:
        raise KeyError(action_id)
    return next(item for item in portfolio_actions(user_id, str(row["portfolio_id"]), True) if item["id"] == action_id)


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


def save_simulation_run(user_id: str, result: dict[str, Any]) -> str:
    run_id = str(result["id"])
    payload = result.get("input") or {}
    created_at = result.get("created_at") or utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.simulation_runs(
                id,user_id,portfolio_id,input_snapshot,result_summary,model_version,seed,status,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'complete',%s)""",
                (run_id, user_id, payload.get("portfolio_id"), _jsonb(payload), _jsonb(result),
                 result["model_version"], payload.get("seed", 0), created_at),
            )
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO simulation_runs(id,user_id,portfolio_id,input_json,result_json,model_version,seed,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, user_id, payload.get("portfolio_id"), json.dumps(payload, default=str),
                 json.dumps(result, default=str), result["model_version"], payload.get("seed", 0), "complete", created_at),
            )
    return run_id


def load_simulation_run(user_id: str, run_id: str) -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT result_summary FROM public.simulation_runs WHERE id=%s AND user_id=%s",
                (run_id, user_id),
            ).fetchone()
        return dict(row["result_summary"]) if row else None
    with sqlite_connection() as conn:
        row = conn.execute("SELECT result_json FROM simulation_runs WHERE id=? AND user_id=?", (run_id, user_id)).fetchone()
    return json.loads(row["result_json"]) if row else None


def latest_simulation_run(user_id: str, portfolio_id: str) -> dict[str, Any] | None:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """SELECT result_summary FROM public.simulation_runs
                   WHERE user_id=%s AND portfolio_id=%s AND status='complete'
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id, portfolio_id),
            ).fetchone()
        return dict(row["result_summary"]) if row else None
    with sqlite_connection() as conn:
        row = conn.execute(
            """SELECT result_json FROM simulation_runs
               WHERE user_id=? AND portfolio_id=? AND status='complete'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, portfolio_id),
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def save_builder_run(user_id: str, builder_type: str, request: dict[str, Any], result: dict[str, Any]) -> str:
    run_id = str(uuid.uuid4())
    created_at = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.allocation_builder_runs(
                id,user_id,builder_type,request_snapshot,result,model_version,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (run_id, user_id, builder_type, _jsonb(request), _jsonb(result), result["model_version"], created_at),
            )
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO allocation_builder_runs(id,user_id,builder_type,request_json,result_json,model_version,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (run_id, user_id, builder_type, json.dumps(request, default=str), json.dumps(result, default=str), result["model_version"], created_at),
            )
    return run_id


def _model_portfolio_row(row: Any) -> dict[str, Any]:
    if not row:
        return {}
    def value(json_key: str, sqlite_key: str) -> Any:
        raw = row.get(json_key) if isinstance(row, dict) else None
        if raw is not None:
            return raw
        text = row[sqlite_key]
        return json.loads(text) if isinstance(text, str) else text
    return {
        "id": str(row["id"]), "name": row["name"], "portfolio_type": row["portfolio_type"],
        "status": row["status"],
        "candidate_universe": value("candidate_universe", "candidate_universe_json") or {},
        "basket": value("basket", "basket_json") or [],
        "configuration": value("configuration", "configuration_json") or {},
        "comparison_results": value("comparison_results", "comparison_results_json") or {},
        "backtest_results": value("backtest_results", "backtest_results_json") or {},
        "simulation_run_id": row.get("simulation_run_id") if isinstance(row, dict) else row["simulation_run_id"],
        "converted_portfolio_id": row.get("converted_portfolio_id") if isinstance(row, dict) else row["converted_portfolio_id"],
        "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"]),
    }


def save_model_portfolio(user_id: str, payload: dict[str, Any], model_id: str | None = None) -> dict[str, Any]:
    model_id = model_id or str(uuid.uuid4())
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.model_portfolios(
                id,user_id,name,portfolio_type,status,candidate_universe,basket,configuration,
                comparison_results,backtest_results,simulation_run_id,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,portfolio_type=excluded.portfolio_type,
                status=excluded.status,candidate_universe=excluded.candidate_universe,basket=excluded.basket,
                configuration=excluded.configuration,comparison_results=excluded.comparison_results,
                backtest_results=excluded.backtest_results,simulation_run_id=excluded.simulation_run_id,
                updated_at=excluded.updated_at
                WHERE model_portfolios.user_id=excluded.user_id RETURNING *""",
                (model_id,user_id,payload["name"],payload["portfolio_type"],payload.get("status","draft"),
                 _jsonb(payload.get("candidate_universe",{})),_jsonb(payload.get("basket",[])),
                 _jsonb(payload.get("configuration",{})),_jsonb(payload.get("comparison_results",{})),
                 _jsonb(payload.get("backtest_results",{})),payload.get("simulation_run_id"),now),
            ).fetchone()
        if not row:
            raise KeyError(model_id)
        return _model_portfolio_row(row)
    with sqlite_connection() as conn:
        existing = conn.execute("SELECT user_id,created_at,converted_portfolio_id FROM model_portfolios WHERE id=?", (model_id,)).fetchone()
        if existing and existing["user_id"] != user_id:
            raise KeyError(model_id)
        created_at = existing["created_at"] if existing else now
        converted = existing["converted_portfolio_id"] if existing else None
        conn.execute(
            """INSERT INTO model_portfolios(id,user_id,name,portfolio_type,status,candidate_universe_json,basket_json,
            configuration_json,comparison_results_json,backtest_results_json,simulation_run_id,converted_portfolio_id,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,portfolio_type=excluded.portfolio_type,status=excluded.status,
            candidate_universe_json=excluded.candidate_universe_json,basket_json=excluded.basket_json,
            configuration_json=excluded.configuration_json,comparison_results_json=excluded.comparison_results_json,
            backtest_results_json=excluded.backtest_results_json,simulation_run_id=excluded.simulation_run_id,updated_at=excluded.updated_at""",
            (model_id,user_id,payload["name"],payload["portfolio_type"],payload.get("status","draft"),
             json.dumps(payload.get("candidate_universe",{}),default=str),json.dumps(payload.get("basket",[]),default=str),
             json.dumps(payload.get("configuration",{}),default=str),json.dumps(payload.get("comparison_results",{}),default=str),
             json.dumps(payload.get("backtest_results",{}),default=str),payload.get("simulation_run_id"),converted,created_at,now),
        )
    return get_model_portfolio(user_id, model_id)


def list_model_portfolios(user_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute("SELECT * FROM public.model_portfolios WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)).fetchall()
    else:
        with sqlite_connection() as conn:
            rows = conn.execute("SELECT * FROM model_portfolios WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    return [_model_portfolio_row(row) for row in rows]


def get_model_portfolio(user_id: str, model_id: str) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute("SELECT * FROM public.model_portfolios WHERE id=%s AND user_id=%s", (model_id,user_id)).fetchone()
    else:
        with sqlite_connection() as conn:
            row = conn.execute("SELECT * FROM model_portfolios WHERE id=? AND user_id=?", (model_id,user_id)).fetchone()
    if not row:
        raise KeyError(model_id)
    return _model_portfolio_row(row)


def delete_model_portfolio(user_id: str, model_id: str) -> None:
    prefix, placeholder = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        cursor = conn.execute(f"DELETE FROM {prefix}model_portfolios WHERE id={placeholder} AND user_id={placeholder}", (model_id,user_id))
        if cursor.rowcount == 0:
            raise KeyError(model_id)


def mark_model_portfolio_converted(user_id: str, model_id: str, portfolio_id: str | int) -> dict[str, Any]:
    prefix, placeholder = ("public.", "%s") if DATABASE_URL else ("", "?")
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE {prefix}model_portfolios SET status='converted',converted_portfolio_id={placeholder},updated_at={placeholder} WHERE id={placeholder} AND user_id={placeholder}",
            (str(portfolio_id),utc_now(),model_id,user_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(model_id)
    return get_model_portfolio(user_id, model_id)


def price_coverage_by_symbol(tickers: list[str]) -> list[dict[str, Any]]:
    """Return one coherent daily-price provider and adjustment coverage per symbol."""
    normalized = sorted({
        ticker.strip().upper() for ticker in tickers
        if ticker.strip() and ticker.upper() != "CASH"
    })
    if not DATABASE_URL or not normalized:
        return []
    with postgres_connection() as conn:
        rows = conn.execute(
            """WITH provider_stats AS (
              SELECT s.ticker, p.provider, count(*) AS observations,
                count(p.adjusted_close) AS explicit_adjusted_observations,
                min(p.ts)::date AS first_date, max(p.ts)::date AS last_date
              FROM public.price_bars p
              JOIN public.securities s ON s.id=p.security_id
              WHERE s.ticker = ANY(%s) AND p.interval='1d'
                AND coalesce(p.adjusted_close,p.close) IS NOT NULL
              GROUP BY s.ticker,p.provider
            ), ranked AS (
              SELECT *, row_number() OVER (
                PARTITION BY ticker
                ORDER BY (last_date-first_date) DESC, observations DESC,
                  CASE WHEN provider='tiingo' THEN 0 WHEN provider='polygon' THEN 1 ELSE 2 END
              ) AS priority
              FROM provider_stats
            )
            SELECT ticker,provider,observations,explicit_adjusted_observations,
              first_date,last_date FROM ranked WHERE priority=1 ORDER BY ticker""",
            (normalized,),
        ).fetchall()
    return [{
        "ticker": row["ticker"], "provider": row["provider"],
        "observations": int(row["observations"] or 0),
        "explicit_adjusted_observations": int(row["explicit_adjusted_observations"] or 0),
        "first_date": _iso(row["first_date"]), "last_date": _iso(row["last_date"]),
    } for row in rows]


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


DEFAULT_WIDGET_PREFERENCES = {
    "overview_widgets": ["portfolio", "macro", "scenarios", "research", "freshness"],
    "macro_widgets": ["rates", "inflation", "growth", "labor", "credit"],
    "research_widgets": ["market", "scores", "fundamentals", "news", "prediction_markets"],
    "focused_tickers": [],
    "density": "comfortable",
    "presentation_level": "detailed",
    "terminal_widgets": [
        {"id": "portfolio-return", "type": "portfolio_return", "size": "wide"},
        {"id": "macro-regime", "type": "macro_regime", "size": "small"},
        {"id": "scenario-map", "type": "scenario_probabilities", "size": "small"},
        {"id": "macro-indicators", "type": "macro_indicators", "size": "wide"},
        {"id": "price-board", "type": "price_board", "size": "wide"},
        {"id": "research-scores", "type": "research_scores", "size": "wide"},
    ],
}


def ensure_user_workspace(user_id: str, default_profile: dict[str, Any]) -> None:
    if not DATABASE_URL:
        return
    # This project started as a local single-user app. Preserve that pre-auth
    # workspace by assigning unowned records to the first authenticated owner.
    # The advisory lock prevents simultaneous first-login claims.
    with postgres_connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('investment_dashboard_legacy_claim'))")
        owned = conn.execute("SELECT 1 FROM public.portfolios WHERE user_id IS NOT NULL LIMIT 1").fetchone()
        user_has_portfolio = conn.execute("SELECT 1 FROM public.portfolios WHERE user_id=%s LIMIT 1", (user_id,)).fetchone()
        if not owned and not user_has_portfolio:
            conn.execute("UPDATE public.portfolios SET user_id=%s WHERE user_id IS NULL", (user_id,))
            conn.execute("UPDATE public.investor_profiles SET user_id=%s WHERE user_id IS NULL", (user_id,))
            conn.execute(
                """UPDATE public.analysis_runs a SET user_id=%s
                WHERE a.user_id IS NULL AND (a.portfolio_id IS NULL OR EXISTS (
                  SELECT 1 FROM public.portfolios p WHERE p.id=a.portfolio_id AND p.user_id=%s
                ))""",
                (user_id, user_id),
            )
            conn.execute("UPDATE public.chat_conversations SET user_id=%s WHERE user_id IS NULL", (user_id,))
    if load_profile(user_id) is None:
        save_profile(default_profile, user_id)
    save_preferences(user_id, load_preferences(user_id))


def load_preferences(user_id: str) -> dict[str, Any]:
    if not DATABASE_URL:
        return dict(DEFAULT_WIDGET_PREFERENCES)
    with postgres_connection() as conn:
        row = conn.execute(
            "SELECT * FROM public.dashboard_preferences WHERE user_id = %s", (user_id,)
        ).fetchone()
    if row is None:
        return dict(DEFAULT_WIDGET_PREFERENCES)
    return {key: row[key] for key in DEFAULT_WIDGET_PREFERENCES}


def save_preferences(user_id: str, preferences: dict[str, Any]) -> dict[str, Any]:
    clean = {
        "overview_widgets": preferences.get("overview_widgets", DEFAULT_WIDGET_PREFERENCES["overview_widgets"]),
        "macro_widgets": preferences.get("macro_widgets", DEFAULT_WIDGET_PREFERENCES["macro_widgets"]),
        "research_widgets": preferences.get("research_widgets", DEFAULT_WIDGET_PREFERENCES["research_widgets"]),
        "focused_tickers": preferences.get("focused_tickers", []),
        "density": preferences.get("density", "comfortable"),
        "presentation_level": preferences.get("presentation_level", "detailed"),
        "terminal_widgets": preferences.get("terminal_widgets", DEFAULT_WIDGET_PREFERENCES["terminal_widgets"]),
    }
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.dashboard_preferences(
                user_id, overview_widgets, macro_widgets, research_widgets, focused_tickers, density, terminal_widgets, presentation_level
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET
                overview_widgets=excluded.overview_widgets, macro_widgets=excluded.macro_widgets,
                research_widgets=excluded.research_widgets, focused_tickers=excluded.focused_tickers,
                density=excluded.density, terminal_widgets=excluded.terminal_widgets,
                presentation_level=excluded.presentation_level""",
                (user_id, clean["overview_widgets"], clean["macro_widgets"], clean["research_widgets"], clean["focused_tickers"], clean["density"], _jsonb(clean["terminal_widgets"]), clean["presentation_level"]),
            )
    return clean


def create_conversation(user_id: str, title: str, portfolio_id: str | None = None,
                        workspace: str = "research") -> dict[str, Any]:
    workspace = workspace if workspace in {"research", "portfolio"} else "research"
    with postgres_connection() as conn:
        row = conn.execute(
            """INSERT INTO public.chat_conversations(user_id, portfolio_id, title, workspace)
            VALUES (%s,%s,%s,%s)
            RETURNING id, portfolio_id, title, workspace, summary, summary_message_count, created_at, updated_at""",
            (user_id, portfolio_id, title[:120], workspace),
        ).fetchone()
    return {**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])}


def list_conversations(user_id: str, workspace: str | None = None,
                       portfolio_id: str | None = None) -> list[dict[str, Any]]:
    workspace_clause = " AND c.workspace=%s" if workspace else ""
    portfolio_clause = " AND c.portfolio_id=%s" if portfolio_id else ""
    params: tuple[Any, ...] = tuple(value for value in (user_id, workspace, portfolio_id) if value is not None)
    with postgres_connection() as conn:
        rows = conn.execute(
            f"""SELECT c.id, c.portfolio_id, c.title, c.workspace, c.summary, c.summary_message_count,
                      c.created_at, c.updated_at,
                      (SELECT count(*)::int FROM public.chat_messages m WHERE m.conversation_id=c.id) AS message_count,
                      (SELECT left(m.content, 180) FROM public.chat_messages m
                       WHERE m.conversation_id=c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message_preview,
                      (SELECT count(*)::int FROM public.chat_artifact_links a WHERE a.conversation_id=c.id) AS artifact_count
               FROM public.chat_conversations c
               WHERE c.user_id=%s{workspace_clause}{portfolio_clause}
               ORDER BY c.updated_at DESC LIMIT 50""",
            params,
        ).fetchall()
    return [{**dict(row), "id": str(row["id"]), "portfolio_id": str(row["portfolio_id"]) if row.get("portfolio_id") else None, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} for row in rows]


def get_conversation(user_id: str, conversation_id: str) -> dict[str, Any]:
    with postgres_connection() as conn:
        row = conn.execute(
            """SELECT id,portfolio_id,title,workspace,summary,summary_message_count,created_at,updated_at
               FROM public.chat_conversations WHERE id=%s AND user_id=%s""",
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        raise KeyError(conversation_id)
    return {**dict(row), "id": str(row["id"]), "portfolio_id": str(row["portfolio_id"]) if row.get("portfolio_id") else None, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])}


def rename_conversation(user_id: str, conversation_id: str, title: str) -> dict[str, Any]:
    with postgres_connection() as conn:
        row = conn.execute(
            """UPDATE public.chat_conversations SET title=%s,updated_at=now()
               WHERE id=%s AND user_id=%s
               RETURNING id,title,workspace,summary,summary_message_count,created_at,updated_at""",
            (title.strip()[:120], conversation_id, user_id),
        ).fetchone()
    if not row:
        raise KeyError(conversation_id)
    return {**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])}


def delete_conversation(user_id: str, conversation_id: str) -> None:
    with postgres_connection() as conn:
        row = conn.execute(
            "DELETE FROM public.chat_conversations WHERE id=%s AND user_id=%s RETURNING id",
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        raise KeyError(conversation_id)


def update_conversation_summary(user_id: str, conversation_id: str, summary: str,
                                message_count: int) -> None:
    with postgres_connection() as conn:
        row = conn.execute(
            """UPDATE public.chat_conversations
               SET summary=%s,summary_message_count=%s,updated_at=now()
               WHERE id=%s AND user_id=%s RETURNING id""",
            (summary[:4000], message_count, conversation_id, user_id),
        ).fetchone()
    if not row:
        raise KeyError(conversation_id)


def conversation_artifacts(user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT a.id,a.artifact_type,a.artifact_id,a.label,a.metadata,a.created_at
               FROM public.chat_artifact_links a JOIN public.chat_conversations c ON c.id=a.conversation_id
               WHERE a.conversation_id=%s AND c.user_id=%s ORDER BY a.created_at DESC""",
            (conversation_id, user_id),
        ).fetchall()
    return [{**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"])} for row in rows]


def link_conversation_artifact(user_id: str, conversation_id: str, artifact_type: str,
                               artifact_id: str, label: str, *, message_id: str | None = None,
                               metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    with postgres_connection() as conn:
        owned = conn.execute(
            "SELECT 1 FROM public.chat_conversations WHERE id=%s AND user_id=%s",
            (conversation_id, user_id),
        ).fetchone()
        if not owned:
            raise KeyError(conversation_id)
        row = conn.execute(
            """INSERT INTO public.chat_artifact_links(
                 user_id,conversation_id,message_id,artifact_type,artifact_id,label,metadata
               ) VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(conversation_id,artifact_type,artifact_id) DO UPDATE SET
                 message_id=coalesce(excluded.message_id,public.chat_artifact_links.message_id),
                 label=excluded.label,metadata=excluded.metadata
               RETURNING id,artifact_type,artifact_id,label,metadata,created_at""",
            (user_id, conversation_id, message_id, artifact_type, artifact_id, label, _jsonb(metadata or {})),
        ).fetchone()
    return {**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"])}


def conversation_messages(user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    with postgres_connection() as conn:
        rows = conn.execute(
            """SELECT m.id, m.role, m.content, m.structured_content, m.model, m.created_at
            FROM public.chat_messages m JOIN public.chat_conversations c ON c.id=m.conversation_id
            WHERE c.user_id=%s AND c.id=%s ORDER BY m.created_at""",
            (user_id, conversation_id),
        ).fetchall()
    return [{**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"])} for row in rows]


def save_chat_message(user_id: str, conversation_id: str, role: str, content: str,
                      structured: dict[str, Any] | None = None, model: str | None = None) -> dict[str, Any]:
    with postgres_connection() as conn:
        owned = conn.execute("SELECT 1 FROM public.chat_conversations WHERE id=%s AND user_id=%s", (conversation_id, user_id)).fetchone()
        if not owned:
            raise KeyError(conversation_id)
        row = conn.execute(
            """INSERT INTO public.chat_messages(conversation_id, role, content, structured_content, model)
            VALUES (%s,%s,%s,%s,%s) RETURNING id, role, content, structured_content, model, created_at""",
            (conversation_id, role, content, _jsonb(structured or {}), model),
        ).fetchone()
        conn.execute("UPDATE public.chat_conversations SET updated_at=now() WHERE id=%s", (conversation_id,))
    return {**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"])}


DASHBOARD_JOB_JSON_FIELDS = {"plan", "specification", "widget_results", "warnings"}
DASHBOARD_JOB_FIELDS = DASHBOARD_JOB_JSON_FIELDS | {
    "state", "progress", "narrative", "error", "cancelled_at", "source_view_id",
}


def _dashboard_job(row: Any) -> dict[str, Any]:
    item = dict(row)
    if not DATABASE_URL:
        for key in DASHBOARD_JOB_JSON_FIELDS:
            raw = item.pop(f"{key}_json", None)
            item[key] = json.loads(raw) if raw else ([] if key in {"widget_results", "warnings"} else None)
    for key in ("id", "portfolio_id", "source_view_id", "conversation_id"):
        if item.get(key) is not None:
            item[key] = str(item[key])
    for key in ("created_at", "updated_at", "expires_at", "cancelled_at"):
        item[key] = _iso(item.get(key))
    return item


def create_dashboard_job(user_id: str, prompt: str, portfolio_id: str | None = None,
                         source_view_id: str | None = None,
                         conversation_id: str | None = None) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.dashboard_jobs(
                    id,user_id,portfolio_id,source_view_id,conversation_id,prompt,state,progress
                ) VALUES (%s,%s,%s,%s,%s,%s,'PLANNING',0) RETURNING *""",
                (job_id, user_id, portfolio_id, source_view_id, conversation_id, prompt),
            ).fetchone()
        return _dashboard_job(row)
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO dashboard_jobs(
                id,user_id,portfolio_id,source_view_id,conversation_id,prompt,state,progress,plan_json,
                specification_json,widget_results_json,warnings_json,expires_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,'PLANNING',0,NULL,NULL,'[]','[]',?,?,?)""",
            (job_id, user_id, portfolio_id, source_view_id, conversation_id, prompt, expires.isoformat(), now.isoformat(), now.isoformat()),
        )
    return get_dashboard_job(job_id, user_id)


def update_dashboard_job(job_id: str, user_id: str, **changes: Any) -> dict[str, Any]:
    values = {key: value for key, value in changes.items() if key in DASHBOARD_JOB_FIELDS}
    if not values:
        return get_dashboard_job(job_id, user_id)
    if DATABASE_URL:
        assignments, params = [], []
        for key, value in values.items():
            assignments.append(f"{key}=%s")
            params.append(_jsonb(value) if key in DASHBOARD_JOB_JSON_FIELDS else value)
        params.extend([job_id, user_id])
        with postgres_connection() as conn:
            row = conn.execute(
                f"UPDATE public.dashboard_jobs SET {', '.join(assignments)} WHERE id=%s AND user_id=%s RETURNING *",
                params,
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _dashboard_job(row)
    assignments, params = [], []
    for key, value in values.items():
        column = f"{key}_json" if key in DASHBOARD_JOB_JSON_FIELDS else key
        assignments.append(f"{column}=?")
        params.append(json.dumps(value, default=str) if key in DASHBOARD_JOB_JSON_FIELDS else value)
    assignments.append("updated_at=?")
    params.extend([utc_now(), job_id, user_id])
    with sqlite_connection() as conn:
        cursor = conn.execute(
            f"UPDATE dashboard_jobs SET {', '.join(assignments)} WHERE id=? AND user_id=?", params
        )
        if cursor.rowcount == 0:
            raise KeyError(job_id)
    return get_dashboard_job(job_id, user_id)


def get_dashboard_job(job_id: str, user_id: str) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT * FROM public.dashboard_jobs WHERE id=%s AND user_id=%s", (job_id, user_id)
            ).fetchone()
    else:
        with sqlite_connection() as conn:
            row = conn.execute("SELECT * FROM dashboard_jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return _dashboard_job(row)


def save_dashboard_task(job_id: str, task: dict[str, Any], *, state: str = "PENDING",
                        result: Any = None, error: str | None = None) -> None:
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.dashboard_job_tasks(
                    job_id,task_key,task_type,depends_on,required_for_narrative,state,attempts,
                    calculation_version,query,result,error,started_at,completed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s='RUNNING' THEN now() END,
                    CASE WHEN %s IN ('READY','FAILED','CANCELLED') THEN now() END)
                ON CONFLICT(job_id,task_key) DO UPDATE SET state=excluded.state,
                    attempts=public.dashboard_job_tasks.attempts + CASE WHEN excluded.state='RUNNING' THEN 1 ELSE 0 END,
                    result=coalesce(excluded.result,public.dashboard_job_tasks.result),error=excluded.error,
                    started_at=coalesce(public.dashboard_job_tasks.started_at,excluded.started_at),
                    completed_at=coalesce(excluded.completed_at,public.dashboard_job_tasks.completed_at)""",
                (job_id, task["id"], task["task_type"], task.get("depends_on", []),
                 task.get("required_for_narrative", False), state, 1 if state == "RUNNING" else 0,
                 task["calculation_version"], _jsonb(task.get("query", {})),
                 _jsonb(result) if result is not None else None, error, state, state),
            )
        return
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO dashboard_job_tasks(
                job_id,task_key,task_type,depends_on_json,required_for_narrative,state,attempts,
                calculation_version,query_json,result_json,error,started_at,completed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id,task_key) DO UPDATE SET state=excluded.state,
                attempts=dashboard_job_tasks.attempts + CASE WHEN excluded.state='RUNNING' THEN 1 ELSE 0 END,
                result_json=coalesce(excluded.result_json,dashboard_job_tasks.result_json),
                error=excluded.error,started_at=coalesce(dashboard_job_tasks.started_at,excluded.started_at),
                completed_at=coalesce(excluded.completed_at,dashboard_job_tasks.completed_at)""",
            (job_id, task["id"], task["task_type"], json.dumps(task.get("depends_on", [])),
             int(task.get("required_for_narrative", False)), state, int(state == "RUNNING"),
             task["calculation_version"], json.dumps(task.get("query", {}), default=str),
             json.dumps(result, default=str) if result is not None else None, error,
             now if state == "RUNNING" else None, now if state in {"READY", "FAILED", "CANCELLED"} else None),
        )


def dashboard_cache_get(cache_key: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "SELECT result,lineage,expires_at FROM public.dashboard_widget_cache WHERE cache_key=%s AND expires_at>now()",
                (cache_key,),
            ).fetchone()
        return None if row is None else {"result": row["result"], "lineage": row["lineage"], "expires_at": _iso(row["expires_at"])}
    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM dashboard_widget_cache WHERE cache_key=? AND expires_at>?", (cache_key, now.isoformat())).fetchone()
    return None if row is None else {"result": json.loads(row["result_json"]), "lineage": json.loads(row["lineage_json"]), "expires_at": row["expires_at"]}


def dashboard_cache_put(cache_key: str, task_type: str, calculation_version: str,
                        result: dict[str, Any], lineage: list[dict[str, Any]], ttl_seconds: int = 3600) -> None:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    effective = result.get("as_of")
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.dashboard_widget_cache(
                    cache_key,task_type,calculation_version,result,lineage,effective_through,expires_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(cache_key) DO UPDATE SET result=excluded.result,lineage=excluded.lineage,
                    effective_through=excluded.effective_through,expires_at=excluded.expires_at,created_at=now()""",
                (cache_key, task_type, calculation_version, _jsonb(result), _jsonb(lineage), effective, expires),
            )
        return
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO dashboard_widget_cache(
                cache_key,task_type,calculation_version,result_json,lineage_json,effective_through,expires_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET
                result_json=excluded.result_json,lineage_json=excluded.lineage_json,
                effective_through=excluded.effective_through,expires_at=excluded.expires_at,created_at=excluded.created_at""",
            (cache_key, task_type, calculation_version, json.dumps(result, default=str),
             json.dumps(lineage, default=str), effective, expires.isoformat(), now.isoformat()),
        )


def save_dashboard_view(user_id: str, job_id: str, name: str | None = None,
                        layout: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    job = get_dashboard_job(job_id, user_id)
    if not job.get("plan") or not job.get("specification"):
        raise ValueError("Dashboard draft is not ready to save")
    view_id = str(uuid.uuid4())
    view_name = (name or job["specification"].get("title") or "AI research view")[:120]
    now = utc_now()
    layout = layout or job["specification"].get("widgets", [])
    spec_version = str(job["specification"].get("spec_version") or job["specification"].get("version") or "dashboard-spec-v1")
    layout_version = str(job["specification"].get("layout_version") or "dashboard-layout-v1")
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.dashboard_views(
                    id,user_id,name,original_prompt,plan,specification,layout,spec_version,layout_version,conversation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (view_id,user_id,view_name,job["prompt"],_jsonb(job["plan"]),
                 _jsonb(job["specification"]),_jsonb(layout),spec_version,layout_version,job.get("conversation_id")),
            ).fetchone()
            conn.execute(
                """INSERT INTO public.dashboard_view_runs(
                    view_id,job_id,user_id,input_snapshot,widget_results,narrative,lineage,warnings,model_versions,status,
                    spec_version,layout_version
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (view_id,job_id,user_id,_jsonb({"prompt":job["prompt"],"plan":job["plan"],"guidance_decision":job["specification"].get("guidance_decision")}),
                 _jsonb(job["widget_results"]),job.get("narrative"),_jsonb([line for item in job["widget_results"] for line in item.get("lineage",[])]),
                 _jsonb(job["warnings"]),_jsonb({"compiler":job["specification"].get("compiler_version"),"guidance":(job["specification"].get("guidance_decision") or {}).get("calculation_version")}),job["state"],spec_version,layout_version),
            )
        saved = _dashboard_view(row)
        save_dashboard_revision(saved, user_id, "created", source_view_id=job.get("source_view_id"))
        return get_dashboard_view(view_id, user_id)
    with sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO dashboard_views(id,user_id,name,original_prompt,plan_json,specification_json,
                layout_json,refresh_policy,spec_version,layout_version,conversation_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'manual',?,?,?,?,?)""",
            (view_id,user_id,view_name,job["prompt"],json.dumps(job["plan"]),
             json.dumps(job["specification"]),json.dumps(layout),spec_version,layout_version,job.get("conversation_id"),now,now),
        )
        conn.execute(
            """INSERT INTO dashboard_view_runs(id,view_id,job_id,user_id,input_snapshot_json,
                widget_results_json,narrative,lineage_json,warnings_json,model_versions_json,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()),view_id,job_id,user_id,json.dumps({"prompt":job["prompt"],"plan":job["plan"],"guidance_decision":job["specification"].get("guidance_decision")}),
             json.dumps(job["widget_results"]),job.get("narrative"),json.dumps([line for item in job["widget_results"] for line in item.get("lineage",[])]),
             json.dumps(job["warnings"]),json.dumps({"compiler":job["specification"].get("compiler_version"),"guidance":(job["specification"].get("guidance_decision") or {}).get("calculation_version")}),job["state"],now),
        )
    saved = get_dashboard_view(view_id, user_id)
    save_dashboard_revision(saved, user_id, "created", source_view_id=job.get("source_view_id"))
    return get_dashboard_view(view_id, user_id)


def _dashboard_view(row: Any) -> dict[str, Any]:
    item = dict(row)
    if not DATABASE_URL:
        for key in ("plan", "specification", "layout"):
            item[key] = json.loads(item.pop(f"{key}_json"))
    item["id"] = str(item["id"])
    item["spec_version"] = item.get("spec_version") or (item.get("specification") or {}).get("version") or "dashboard-spec-v1"
    item["layout_version"] = item.get("layout_version") or "dashboard-layout-v1"
    item["created_at"], item["updated_at"] = _iso(item["created_at"]), _iso(item["updated_at"])
    return item


def list_dashboard_views(user_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute("SELECT * FROM public.dashboard_views WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)).fetchall()
    else:
        with sqlite_connection() as conn:
            rows = conn.execute("SELECT * FROM dashboard_views WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    return [_dashboard_view(row) for row in rows]


def get_dashboard_view(view_id: str, user_id: str) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute("SELECT * FROM public.dashboard_views WHERE id=%s AND user_id=%s", (view_id,user_id)).fetchone()
    else:
        with sqlite_connection() as conn:
            row = conn.execute("SELECT * FROM dashboard_views WHERE id=? AND user_id=?", (view_id,user_id)).fetchone()
    if row is None:
        raise KeyError(view_id)
    view = _dashboard_view(row)
    if DATABASE_URL:
        with postgres_connection() as conn:
            run = conn.execute(
                """SELECT id,job_id,widget_results,narrative,warnings,status,created_at
                FROM public.dashboard_view_runs WHERE view_id=%s AND user_id=%s
                ORDER BY created_at DESC LIMIT 1""", (view_id,user_id)
            ).fetchone()
        if run:
            view["latest_run"] = {**dict(run), "id": str(run["id"]), "job_id": str(run["job_id"]) if run["job_id"] else None, "created_at": _iso(run["created_at"])}
    else:
        with sqlite_connection() as conn:
            run = conn.execute(
                "SELECT * FROM dashboard_view_runs WHERE view_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1",
                (view_id,user_id),
            ).fetchone()
        if run:
            view["latest_run"] = {"id":run["id"],"job_id":run["job_id"],"widget_results":json.loads(run["widget_results_json"]),
                                  "narrative":run["narrative"],"warnings":json.loads(run["warnings_json"]),
                                  "status":run["status"],"created_at":run["created_at"]}
    view["revisions"] = list_dashboard_revisions(view_id, user_id, limit=20)
    return view


def persist_dashboard_widget_results(view_id: str, user_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Append one refreshed widget result without mutating historical view runs."""
    view = get_dashboard_view(view_id, user_id)
    latest = view.get("latest_run") or {}
    results = [dict(item) for item in latest.get("widget_results") or []]
    result_id = str(result.get("widget_id") or result.get("task_id") or result.get("id") or "")
    results = [item for item in results if str(item.get("widget_id") or item.get("task_id") or item.get("id") or "") != result_id]
    results.append(result)
    lineage = [line for item in results for line in item.get("lineage", [])]
    warnings = list(dict.fromkeys(str(warning) for item in results for warning in item.get("warnings", []) if warning))
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            original = None
            if latest.get("id"):
                original = conn.execute(
                    "SELECT * FROM public.dashboard_view_runs WHERE id=%s AND user_id=%s",
                    (latest["id"], user_id),
                ).fetchone()
            conn.execute(
                """INSERT INTO public.dashboard_view_runs(
                    view_id,job_id,user_id,input_snapshot,widget_results,narrative,lineage,warnings,
                    model_versions,status,spec_version,layout_version
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    view_id,
                    original["job_id"] if original else latest.get("job_id"),
                    user_id,
                    original["input_snapshot"] if original else _jsonb({"source": "conversational-widget"}),
                    _jsonb(results),
                    original["narrative"] if original else None,
                    _jsonb(lineage),
                    _jsonb(warnings),
                    original["model_versions"] if original else _jsonb({"dashboard_actions": "dashboard-action-v1"}),
                    "READY",
                    view.get("spec_version", "dashboard-spec-v1"),
                    view.get("layout_version", "dashboard-layout-v2"),
                ),
            )
            conn.execute("UPDATE public.dashboard_views SET updated_at=now() WHERE id=%s AND user_id=%s", (view_id, user_id))
    else:
        with sqlite_connection() as conn:
            original = None
            if latest.get("id"):
                original = conn.execute(
                    "SELECT * FROM dashboard_view_runs WHERE id=? AND user_id=?",
                    (latest["id"], user_id),
                ).fetchone()
            conn.execute(
                """INSERT INTO dashboard_view_runs(
                    id,view_id,job_id,user_id,input_snapshot_json,widget_results_json,narrative,
                    lineage_json,warnings_json,model_versions_json,status,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), view_id,
                    original["job_id"] if original else latest.get("job_id"), user_id,
                    original["input_snapshot_json"] if original else json.dumps({"source": "conversational-widget"}),
                    json.dumps(results, default=str), original["narrative"] if original else None,
                    json.dumps(lineage, default=str), json.dumps(warnings, default=str),
                    original["model_versions_json"] if original else json.dumps({"dashboard_actions": "dashboard-action-v1"}),
                    "READY", now,
                ),
            )
            conn.execute("UPDATE dashboard_views SET updated_at=? WHERE id=? AND user_id=?", (now, view_id, user_id))
    return get_dashboard_view(view_id, user_id)


def _layout_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    old = {str(item.get("id")): item for item in before}
    new = {str(item.get("id")): item for item in after}
    added = [key for key in new if key not in old]
    removed = [key for key in old if key not in new]
    resized = [key for key in new if key in old and new[key].get("grid") != old[key].get("grid")]
    old_order, new_order = list(old), list(new)
    moved = [key for key in new_order if key in old and old_order.index(key) != new_order.index(key)]
    return {"added": added, "removed": removed, "resized": resized, "moved": moved,
            "before_count": len(before), "after_count": len(after)}


def save_dashboard_revision(view: dict[str, Any], user_id: str, revision_type: str,
                            before_layout: list[dict[str, Any]] | None = None,
                            source_view_id: str | None = None) -> dict[str, Any]:
    revision_id, now = str(uuid.uuid4()), utc_now()
    before = before_layout if before_layout is not None else []
    diff = _layout_diff(before, view.get("layout") or [])
    if DATABASE_URL:
        with postgres_connection() as conn:
            number = int(conn.execute(
                "SELECT coalesce(max(revision_number),0)+1 AS value FROM public.dashboard_view_revisions WHERE view_id=%s",
                (view["id"],),
            ).fetchone()["value"])
            row = conn.execute(
                """INSERT INTO public.dashboard_view_revisions(
                    id,view_id,user_id,revision_number,revision_type,prompt,plan,specification,layout,diff,
                    spec_version,layout_version,source_view_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (revision_id,view["id"],user_id,number,revision_type,view.get("original_prompt"),
                 _jsonb(view.get("plan") or {}),_jsonb(view.get("specification") or {}),_jsonb(view.get("layout") or []),
                 _jsonb(diff),view.get("spec_version","dashboard-spec-v1"),view.get("layout_version","dashboard-layout-v1"),source_view_id),
            ).fetchone()
        return {**dict(row), "id": str(row["id"]), "view_id": str(row["view_id"]), "created_at": _iso(row["created_at"])}
    with sqlite_connection() as conn:
        number = int(conn.execute("SELECT coalesce(max(revision_number),0)+1 FROM dashboard_view_revisions WHERE view_id=?",(view["id"],)).fetchone()[0])
        conn.execute(
            """INSERT INTO dashboard_view_revisions(id,view_id,user_id,revision_number,revision_type,prompt,
            plan_json,specification_json,layout_json,diff_json,spec_version,layout_version,source_view_id,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (revision_id,view["id"],user_id,number,revision_type,view.get("original_prompt"),json.dumps(view.get("plan") or {}),
             json.dumps(view.get("specification") or {}),json.dumps(view.get("layout") or []),json.dumps(diff),
             view.get("spec_version","dashboard-spec-v1"),view.get("layout_version","dashboard-layout-v1"),source_view_id,now),
        )
    return {"id":revision_id,"view_id":view["id"],"revision_number":number,"revision_type":revision_type,"diff":diff,"created_at":now}


def list_dashboard_revisions(view_id: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute(
                """SELECT r.* FROM public.dashboard_view_revisions r JOIN public.dashboard_views v ON v.id=r.view_id
                WHERE r.view_id=%s AND v.user_id=%s ORDER BY r.revision_number DESC LIMIT %s""",
                (view_id,user_id,limit),
            ).fetchall()
        return [{**dict(row),"id":str(row["id"]),"view_id":str(row["view_id"]),"created_at":_iso(row["created_at"])} for row in rows]
    with sqlite_connection() as conn:
        rows=conn.execute("SELECT * FROM dashboard_view_revisions WHERE view_id=? AND user_id=? ORDER BY revision_number DESC LIMIT ?",(view_id,user_id,limit)).fetchall()
    return [{**dict(row),"plan":json.loads(row["plan_json"]),"specification":json.loads(row["specification_json"]),
             "layout":json.loads(row["layout_json"]),"diff":json.loads(row["diff_json"])} for row in rows]


def restore_previous_dashboard_revision(
    view_id: str,
    user_id: str,
    widget_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restore the state immediately before the latest relevant saved-view change.

    Revisions are full snapshots, so this uses the existing durable history rather
    than maintaining an AI-specific undo log.  A widget-scoped revert finds the
    newest revision whose layout diff mentions that widget, then restores the
    preceding snapshot.
    """
    revisions = list_dashboard_revisions(view_id, user_id, limit=100)
    if len(revisions) < 2:
        raise ValueError("There is no earlier saved dashboard revision to restore")
    current_index = 0
    if widget_id:
        current_index = next((
            index for index, revision in enumerate(revisions[:-1])
            if widget_id in {
                str(value)
                for key in ("added", "removed", "resized", "moved")
                for value in (revision.get("diff") or {}).get(key, [])
            }
        ), -1)
        if current_index < 0:
            raise ValueError("No saved revision changed that widget")
    target = revisions[current_index + 1]
    before = get_dashboard_view(view_id, user_id)
    specification = dict(target.get("specification") or {})
    layout = list(target.get("layout") or specification.get("widgets") or [])
    specification["widgets"] = layout
    restored_name = str(specification.get("title") or before.get("name") or "Saved dashboard")[:120]
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """UPDATE public.dashboard_views
                SET name=%s,original_prompt=%s,plan=%s,specification=%s,layout=%s,
                    spec_version=%s,layout_version=%s,updated_at=now()
                WHERE id=%s AND user_id=%s RETURNING id""",
                (restored_name, target.get("prompt") or before.get("original_prompt"),
                 _jsonb(target.get("plan") or {}), _jsonb(specification), _jsonb(layout),
                 target.get("spec_version") or before.get("spec_version"),
                 target.get("layout_version") or before.get("layout_version"), view_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(view_id)
    else:
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """UPDATE dashboard_views SET name=?,original_prompt=?,plan_json=?,specification_json=?,
                layout_json=?,spec_version=?,layout_version=?,updated_at=? WHERE id=? AND user_id=?""",
                (restored_name, target.get("prompt") or before.get("original_prompt"),
                 json.dumps(target.get("plan") or {}), json.dumps(specification), json.dumps(layout),
                 target.get("spec_version") or before.get("spec_version"),
                 target.get("layout_version") or before.get("layout_version"), now, view_id, user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(view_id)
    restored = get_dashboard_view(view_id, user_id)
    revision = save_dashboard_revision(
        restored,
        user_id,
        f"reverted_to_{target.get('revision_number')}",
        before.get("layout") or [],
    )
    return get_dashboard_view(view_id, user_id), revision


def update_dashboard_view(view_id: str, user_id: str, name: str | None = None,
                          layout: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    before = get_dashboard_view(view_id, user_id)
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """UPDATE public.dashboard_views SET name=coalesce(%s,name),layout=coalesce(%s,layout)
                WHERE id=%s AND user_id=%s RETURNING *""",
                (name, _jsonb(layout) if layout is not None else None, view_id, user_id),
            ).fetchone()
        if row is None: raise KeyError(view_id)
        updated = _dashboard_view(row)
        save_dashboard_revision(updated,user_id,"layout" if layout is not None else "renamed",before.get("layout") or [])
        return get_dashboard_view(view_id,user_id)
    assignments, params = [], []
    if name is not None: assignments.append("name=?"); params.append(name)
    if layout is not None: assignments.append("layout_json=?"); params.append(json.dumps(layout))
    if not assignments: return get_dashboard_view(view_id,user_id)
    assignments.append("updated_at=?"); params.extend([utc_now(),view_id,user_id])
    with sqlite_connection() as conn:
        cursor=conn.execute(f"UPDATE dashboard_views SET {', '.join(assignments)} WHERE id=? AND user_id=?",params)
        if cursor.rowcount==0: raise KeyError(view_id)
    updated=get_dashboard_view(view_id,user_id)
    save_dashboard_revision(updated,user_id,"layout" if layout is not None else "renamed",before.get("layout") or [])
    return get_dashboard_view(view_id,user_id)


def persist_dashboard_action(view_id: str, user_id: str, *, name: str | None,
                             layout: list[dict[str, Any]], specification: dict[str, Any],
                             revision_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist one validated dashboard action and exactly one compatible revision."""
    before = get_dashboard_view(view_id, user_id)
    now = utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """UPDATE public.dashboard_views
                SET name=%s,layout=%s,specification=%s,layout_version=%s,updated_at=now()
                WHERE id=%s AND user_id=%s RETURNING *""",
                (name, _jsonb(layout), _jsonb(specification), "dashboard-layout-v2", view_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(view_id)
    else:
        with sqlite_connection() as conn:
            cursor = conn.execute(
                """UPDATE dashboard_views
                SET name=?,layout_json=?,specification_json=?,layout_version=?,updated_at=?
                WHERE id=? AND user_id=?""",
                (name, json.dumps(layout), json.dumps(specification), "dashboard-layout-v2", now, view_id, user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(view_id)
    updated = get_dashboard_view(view_id, user_id)
    revision = save_dashboard_revision(updated, user_id, revision_type, before.get("layout") or [])
    return get_dashboard_view(view_id, user_id), revision


def mutate_dashboard_layout(view_id: str, user_id: str, widget_id: str, operation: str,
                            width: int | None = None, height: int | None = None,
                            direction: int | None = None) -> dict[str, Any]:
    # Compatibility adapter: callers of the legacy database helper still use the
    # same validated action executor as the HTTP and canvas paths.
    view = get_dashboard_view(view_id, user_id)
    layout = view.get("layout") or []
    index = next((position for position, item in enumerate(layout) if str(item.get("id")) == widget_id), -1)
    if index < 0:
        raise KeyError(widget_id)
    if operation == "remove":
        action = {"type": "DELETE_WIDGET", "widget_id": widget_id}
    elif operation == "resize":
        action = {"type": "RESIZE_WIDGET", "widget_id": widget_id, "width": width, "height": height}
    elif operation == "move":
        action = {"type": "MOVE_WIDGET", "widget_id": widget_id,
                  "to_index": index + (-1 if (direction or 0) < 0 else 1)}
    else:
        raise ValueError("Unsupported deterministic layout operation")
    from .dashboard_workspace import run_dashboard_action
    result = run_dashboard_action(user_id, "view", view_id, action)
    if result.status.value != "SUCCESS":
        raise ValueError(result.error or "Dashboard action failed")
    return result.dashboard or view


def duplicate_dashboard_view(view_id: str, user_id: str, name: str | None = None) -> dict[str, Any]:
    source=get_dashboard_view(view_id,user_id)
    duplicate_id=str(uuid.uuid4()); now=utc_now(); duplicate_name=(name or f"{source['name']} copy")[:120]
    if DATABASE_URL:
        with postgres_connection() as conn:
            row=conn.execute(
                """INSERT INTO public.dashboard_views(id,user_id,name,original_prompt,plan,specification,layout,
                refresh_policy,spec_version,layout_version,conversation_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (duplicate_id,user_id,duplicate_name,source["original_prompt"],_jsonb(source["plan"]),
                 _jsonb(source["specification"]),_jsonb(source["layout"]),source.get("refresh_policy","manual"),
                 source.get("spec_version","dashboard-spec-v1"),source.get("layout_version","dashboard-layout-v1"),source.get("conversation_id")),
            ).fetchone()
            latest=source.get("latest_run")
            if latest:
                original=conn.execute("SELECT * FROM public.dashboard_view_runs WHERE id=%s AND user_id=%s",(latest["id"],user_id)).fetchone()
                if original:
                    conn.execute(
                        """INSERT INTO public.dashboard_view_runs(view_id,job_id,user_id,input_snapshot,widget_results,narrative,
                        lineage,warnings,model_versions,status,spec_version,layout_version)
                        VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (duplicate_id,user_id,original["input_snapshot"],original["widget_results"],original["narrative"],
                         original["lineage"],original["warnings"],original["model_versions"],original["status"],
                         source.get("spec_version","dashboard-spec-v1"),source.get("layout_version","dashboard-layout-v1")),
                    )
        duplicated=_dashboard_view(row)
    else:
        with sqlite_connection() as conn:
            conn.execute("""INSERT INTO dashboard_views(id,user_id,name,original_prompt,plan_json,specification_json,layout_json,
                refresh_policy,spec_version,layout_version,conversation_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (duplicate_id,user_id,duplicate_name,source["original_prompt"],json.dumps(source["plan"]),json.dumps(source["specification"]),
                 json.dumps(source["layout"]),source.get("refresh_policy","manual"),source.get("spec_version","dashboard-spec-v1"),
                 source.get("layout_version","dashboard-layout-v1"),source.get("conversation_id"),now,now))
            latest=source.get("latest_run")
            if latest:
                original=conn.execute(
                    "SELECT * FROM dashboard_view_runs WHERE id=? AND user_id=?",
                    (latest["id"],user_id),
                ).fetchone()
                if original:
                    conn.execute(
                        """INSERT INTO dashboard_view_runs(id,view_id,job_id,user_id,input_snapshot_json,
                        widget_results_json,narrative,lineage_json,warnings_json,model_versions_json,status,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()),duplicate_id,None,user_id,original["input_snapshot_json"],
                         original["widget_results_json"],original["narrative"],original["lineage_json"],
                         original["warnings_json"],original["model_versions_json"],original["status"],now),
                    )
        duplicated=get_dashboard_view(duplicate_id,user_id)
    save_dashboard_revision(duplicated,user_id,"duplicated",source_view_id=view_id)
    return get_dashboard_view(duplicate_id,user_id)


def delete_dashboard_view(view_id: str, user_id: str) -> None:
    table = "public.dashboard_views" if DATABASE_URL else "dashboard_views"
    marker = "%s" if DATABASE_URL else "?"
    connection = postgres_connection if DATABASE_URL else sqlite_connection
    with connection() as conn:
        cursor = conn.execute(f"DELETE FROM {table} WHERE id={marker} AND user_id={marker}", (view_id,user_id))
        if cursor.rowcount == 0: raise KeyError(view_id)


def load_learning_preferences(user_id: str) -> dict[str, Any]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute("SELECT * FROM public.learning_preferences WHERE user_id=%s", (user_id,)).fetchone()
    else:
        with sqlite_connection() as conn:
            row = conn.execute("SELECT * FROM learning_preferences WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return {"selected_path": None, "knowledge_level": "beginner", "interests": [], "portfolio_context_enabled": False}
    item = dict(row)
    interests = item.get("interests") if DATABASE_URL else json.loads(item.get("interests_json") or "[]")
    return {
        "selected_path": item.get("selected_path"), "knowledge_level": item.get("knowledge_level", "beginner"),
        "interests": interests or [], "portfolio_context_enabled": bool(item.get("portfolio_context_enabled")),
        "updated_at": _iso(item.get("updated_at")),
    }


def save_learning_preferences(user_id: str, preferences: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    selected_path = preferences.get("selected_path") or None
    level = preferences.get("knowledge_level", "beginner")
    interests = list(dict.fromkeys(str(item).strip() for item in preferences.get("interests", []) if str(item).strip()))[:20]
    portfolio_context = bool(preferences.get("portfolio_context_enabled", False))
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.learning_preferences(user_id,selected_path,knowledge_level,interests,portfolio_context_enabled,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET selected_path=excluded.selected_path,
                knowledge_level=excluded.knowledge_level,interests=excluded.interests,
                portfolio_context_enabled=excluded.portfolio_context_enabled,updated_at=excluded.updated_at""",
                (user_id, selected_path, level, _jsonb(interests), portfolio_context, now),
            )
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO learning_preferences(user_id,selected_path,knowledge_level,interests_json,portfolio_context_enabled,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET selected_path=excluded.selected_path,
                knowledge_level=excluded.knowledge_level,interests_json=excluded.interests_json,
                portfolio_context_enabled=excluded.portfolio_context_enabled,updated_at=excluded.updated_at""",
                (user_id, selected_path, level, json.dumps(interests), int(portfolio_context), now, now),
            )
    return load_learning_preferences(user_id)


def list_learning_quiz_attempts(user_id: str, lesson_id: str | None = None) -> list[dict[str, Any]]:
    if DATABASE_URL:
        query = "SELECT * FROM public.learning_quiz_attempts WHERE user_id=%s"
        params: tuple[Any, ...] = (user_id,)
        if lesson_id:
            query += " AND lesson_id=%s"; params += (lesson_id,)
        query += " ORDER BY attempted_at DESC"
        with postgres_connection() as conn:
            rows = conn.execute(query, params).fetchall()
    else:
        query = "SELECT * FROM learning_quiz_attempts WHERE user_id=?"
        params = (user_id,)
        if lesson_id:
            query += " AND lesson_id=?"; params += (lesson_id,)
        query += " ORDER BY attempted_at DESC"
        with sqlite_connection() as conn:
            rows = conn.execute(query, params).fetchall()
    return [{
        **dict(row), "id": str(row["id"]), "percentage": float(row["percentage"]),
        "answers": row.get("answers") if DATABASE_URL else json.loads(row["answers_json"]),
        "attempted_at": _iso(row["attempted_at"]),
    } for row in rows]


def list_learning_progress(user_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute("SELECT * FROM public.learning_progress WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)).fetchall()
    else:
        with sqlite_connection() as conn:
            rows = conn.execute("SELECT * FROM learning_progress WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    attempts = list_learning_quiz_attempts(user_id)
    best: dict[tuple[str, str], float] = {}
    for attempt in attempts:
        key = (attempt["lesson_id"], attempt["content_version"])
        best[key] = max(best.get(key, 0), float(attempt["percentage"]))
    return [{
        **dict(row), "id": str(row["id"]), "completion_percentage": float(row["completion_percentage"]),
        "best_score": best.get((row["lesson_id"], row["content_version"])),
        "started_at": _iso(row["started_at"]), "completed_at": _iso(row["completed_at"]), "updated_at": _iso(row["updated_at"]),
    } for row in rows]


def save_learning_progress(user_id: str, module_id: str, lesson_id: str, content_version: str,
                           status: str, completion_percentage: float) -> dict[str, Any]:
    now = utc_now()
    current = next((item for item in list_learning_progress(user_id) if item["lesson_id"] == lesson_id and item["content_version"] == content_version), None)
    started_at = current.get("started_at") if current else now
    best = current.get("best_score") if current else None
    completion = min(1.0, max(0.0, float(completion_percentage)))
    if completion >= 1 and status in {"completed", "mastered"} and best is not None and best >= .80:
        status = "mastered"
    completed_at = (current or {}).get("completed_at") or (now if completion >= 1 else None)
    progress_id = (current or {}).get("id") or str(uuid.uuid4())
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                """INSERT INTO public.learning_progress(id,user_id,module_id,lesson_id,content_version,status,completion_percentage,started_at,completed_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,lesson_id,content_version)
                DO UPDATE SET module_id=excluded.module_id,status=excluded.status,completion_percentage=excluded.completion_percentage,
                started_at=coalesce(public.learning_progress.started_at,excluded.started_at),
                completed_at=coalesce(public.learning_progress.completed_at,excluded.completed_at),updated_at=excluded.updated_at RETURNING *""",
                (progress_id, user_id, module_id, lesson_id, content_version, status, completion, started_at, completed_at, now),
            ).fetchone()
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO learning_progress(id,user_id,module_id,lesson_id,content_version,status,completion_percentage,started_at,completed_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,lesson_id,content_version) DO UPDATE SET
                module_id=excluded.module_id,status=excluded.status,completion_percentage=excluded.completion_percentage,
                started_at=coalesce(learning_progress.started_at,excluded.started_at),completed_at=coalesce(learning_progress.completed_at,excluded.completed_at),
                updated_at=excluded.updated_at""",
                (progress_id, user_id, module_id, lesson_id, content_version, status, completion, started_at, completed_at, now, now),
            )
            row = conn.execute("SELECT * FROM learning_progress WHERE user_id=? AND lesson_id=? AND content_version=?", (user_id, lesson_id, content_version)).fetchone()
    item = dict(row)
    return {**item, "id": str(item["id"]), "completion_percentage": float(item["completion_percentage"]), "best_score": best,
            "started_at": _iso(item["started_at"]), "completed_at": _iso(item["completed_at"]), "updated_at": _iso(item["updated_at"])}


def save_learning_quiz_attempt(user_id: str, result: dict[str, Any], answers: list[int]) -> dict[str, Any]:
    attempt_id, now = str(result.get("attempt_id") or uuid.uuid4()), utc_now()
    values = (attempt_id, user_id, result["module_id"], result["lesson_id"], result["content_version"], result["quiz_id"],
              result["quiz_version"], result["score"], result["total_questions"], result["percentage"])
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.learning_quiz_attempts(id,user_id,module_id,lesson_id,content_version,quiz_id,quiz_version,
                score,total_questions,percentage,answers,attempted_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO NOTHING""",
                (*values, _jsonb(answers), now),
            )
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO learning_quiz_attempts(id,user_id,module_id,lesson_id,content_version,quiz_id,quiz_version,
                score,total_questions,percentage,answers_json,attempted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING""",
                (*values, json.dumps(answers), now),
            )
    progress = next((item for item in list_learning_progress(user_id) if item["lesson_id"] == result["lesson_id"] and item["content_version"] == result["content_version"]), None)
    if progress:
        save_learning_progress(user_id, result["module_id"], result["lesson_id"], result["content_version"], progress["status"], progress["completion_percentage"])
    return next(item for item in list_learning_quiz_attempts(user_id, result["lesson_id"]) if item["id"] == attempt_id)


def create_learning_tutor_thread(user_id: str, lesson_id: str, title: str) -> dict[str, Any]:
    thread_id, now = str(uuid.uuid4()), utc_now()
    if DATABASE_URL:
        with postgres_connection() as conn:
            row = conn.execute(
                "INSERT INTO public.learning_tutor_threads(id,user_id,lesson_id,title,updated_at) VALUES(%s,%s,%s,%s,%s) RETURNING *",
                (thread_id, user_id, lesson_id, title[:120], now),
            ).fetchone()
    else:
        with sqlite_connection() as conn:
            conn.execute("INSERT INTO learning_tutor_threads(id,user_id,lesson_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?)", (thread_id, user_id, lesson_id, title[:120], now, now))
            row = conn.execute("SELECT * FROM learning_tutor_threads WHERE id=?", (thread_id,)).fetchone()
    item = dict(row); item["id"] = str(item["id"]); item["created_at"] = _iso(item["created_at"]); item["updated_at"] = _iso(item["updated_at"])
    return item


def list_learning_tutor_threads(user_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            rows = conn.execute("SELECT * FROM public.learning_tutor_threads WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)).fetchall()
    else:
        with sqlite_connection() as conn:
            rows = conn.execute("SELECT * FROM learning_tutor_threads WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    return [{**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} for row in rows]


def learning_tutor_messages(user_id: str, thread_id: str) -> list[dict[str, Any]]:
    if DATABASE_URL:
        with postgres_connection() as conn:
            owner = conn.execute("SELECT id FROM public.learning_tutor_threads WHERE id=%s AND user_id=%s", (thread_id, user_id)).fetchone()
            if owner is None: raise KeyError(thread_id)
            rows = conn.execute("SELECT * FROM public.learning_tutor_messages WHERE thread_id=%s AND user_id=%s ORDER BY created_at", (thread_id, user_id)).fetchall()
    else:
        with sqlite_connection() as conn:
            owner = conn.execute("SELECT id FROM learning_tutor_threads WHERE id=? AND user_id=?", (thread_id, user_id)).fetchone()
            if owner is None: raise KeyError(thread_id)
            rows = conn.execute("SELECT * FROM learning_tutor_messages WHERE thread_id=? AND user_id=? ORDER BY created_at", (thread_id, user_id)).fetchall()
    return [{
        **dict(row), "id": str(row["id"]),
        "source_references": row.get("source_references") if DATABASE_URL else json.loads(row["source_references_json"]),
        "retrieval_quality": row.get("retrieval_quality") if DATABASE_URL else json.loads(row["retrieval_quality_json"]),
        "created_at": _iso(row["created_at"]),
    } for row in rows]


def save_learning_tutor_message(user_id: str, thread_id: str, role: str, content: str,
                                source_references: list[dict[str, Any]] | None = None,
                                retrieval_quality: dict[str, Any] | None = None,
                                model_version: str | None = None) -> dict[str, Any]:
    learning_tutor_messages(user_id, thread_id)
    message_id, now = str(uuid.uuid4()), utc_now()
    sources, quality = source_references or [], retrieval_quality or {}
    if DATABASE_URL:
        with postgres_connection() as conn:
            conn.execute(
                """INSERT INTO public.learning_tutor_messages(id,thread_id,user_id,role,content,source_references,retrieval_quality,model_version,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (message_id, thread_id, user_id, role, content, _jsonb(sources), _jsonb(quality), model_version, now),
            )
            conn.execute("UPDATE public.learning_tutor_threads SET updated_at=%s WHERE id=%s AND user_id=%s", (now, thread_id, user_id))
    else:
        with sqlite_connection() as conn:
            conn.execute(
                """INSERT INTO learning_tutor_messages(id,thread_id,user_id,role,content,source_references_json,retrieval_quality_json,model_version,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", (message_id, thread_id, user_id, role, content, json.dumps(sources), json.dumps(quality), model_version, now),
            )
            conn.execute("UPDATE learning_tutor_threads SET updated_at=? WHERE id=? AND user_id=?", (now, thread_id, user_id))
    return next(item for item in learning_tutor_messages(user_id, thread_id) if item["id"] == message_id)
