from __future__ import annotations

import json
import math
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import pandas as pd

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import database
from .analysis import latest_macro, macro_factor_dashboard, run_analysis, security_research
from .auth import AuthenticatedUser, optional_user, require_user
from .chat import ask_gemini, retrieve_evidence
from .company_markets import refresh_company_markets
from .dashboard_workspace import (
    DraftRequest, RevisionRequest, SaveViewRequest, UpdateViewRequest, WidgetAddRequest,
    LayoutMutationRequest, DuplicateViewRequest, TERMINAL_STATES,
    add_widget_to_draft, add_widget_to_view, create_draft, dashboard_data_catalog,
    mutate_draft_layout, portfolio_performance_widget, revise_draft,
)
from .dashboard_workspace import MACRO_SENSITIVITY_FACTORS, calculate_macro_sensitivity
from .explanations import generate_explanation
from .ingestion import refresh_fred, refresh_polygon, refresh_sec, refresh_security_catalog, refresh_security_evidence, refresh_tiingo
from .models import (
    AnalysisRequest, ExplanationRequest, FinancialGoal, GoalProjectionRequest, InvestmentPolicy,
    Holding, InvestorProfile, PortfolioPayload, TransactionCsvImport, AccountPerformanceRequest,
    StatementReconciliationRequest, SimulationRunInput, ETFAllocationRequest, StockBasketRequest,
)
from .simulation_engine import goal_projection as shared_goal_projection, run_simulation
from .allocation_builders import optimize_etfs, optimize_stocks
from .security_snapshot import overview as security_snapshot_overview
from .security_snapshot import sentiment as security_snapshot_sentiment
from .security_snapshot import technicals as security_snapshot_technicals
from .portfolio_import import parse_portfolio_csv
from .portfolio_ledger import calculate_performance, parse_transaction_csv, reconstruct_positions, tax_lot_coverage
from .portfolio_diagnostics import build_portfolio_diagnostics
from .planning import build_guidance
from .provider_health import build_provider_health
from .historical_coverage import attach_coverage, build_historical_coverage
from .fund_data import ensure_fund_data, holdings_freshness, recognized_fund, refresh_etf_catalog
from .research_workspace import comparisons as research_comparison_payload
from .research_workspace import ideas as research_ideas_payload
from .research_workspace import search as research_search_payload
from .research_workspace import sector_summaries, theme_summaries
from .scenarios import refresh as refresh_scenarios
from .today_briefing import INDEXES, MARKET_SERIES, SECTORS, build_today_briefing
from .error_monitoring import configure_error_monitoring
from .operational_monitoring import operational_snapshot
from .production_middleware import production_guard
from .resilience import TTLCache
from .market_context import (
    PolygonSnapshotProvider, ResearchMarketEventProvider, normalize_observation,
    overlay_observations,
)
from .learning import (
    calculate_lab, catalog_payload, grade_quiz, learning_tutor_answer, lesson_payload,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    if not database.DATABASE_URL and database.load_profile() is None:
        database.save_profile(InvestorProfile().model_dump(mode="json"))
    if not database.DATABASE_URL and not database.list_portfolios():
        database.save_portfolio(
            "Starter portfolio",
            [
                {"ticker": "AAPL", "weight": 0.28, "account_type": "taxable"},
                {"ticker": "MU", "weight": 0.22, "account_type": "taxable"},
                {"ticker": "CSCO", "weight": 0.18, "account_type": "taxable"},
                {"ticker": "SPY", "weight": 0.22, "account_type": "taxable"},
                {"ticker": "CASH", "weight": 0.10, "account_type": "taxable"},
            ],
        )
    yield


app = FastAPI(title="InvestmentDashboard Local API", version="0.1.0", lifespan=lifespan)
ERROR_MONITORING = configure_error_monitoring()
app.middleware("http")(production_guard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


class CsvImport(BaseModel):
    name: str = "Imported portfolio"
    csv_text: str


class ResearchRefresh(BaseModel):
    tickers: list[str]
    ingest_tickers: list[str] = Field(default_factory=list)


class TerminalWidgetPreference(BaseModel):
    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal[
        "portfolio_return", "portfolio_allocation", "positions", "price_board",
        "macro_regime", "macro_indicators", "market_indicators", "scenario_probabilities", "recession_monitor",
        "prediction_market_search", "research_scores", "security_scorecard",
        "optimizer_snapshot", "data_freshness", "model_monitoring",
    ]
    size: Literal["small", "wide", "full"] = "wide"


class WidgetPreferences(BaseModel):
    overview_widgets: list[str] = Field(default_factory=lambda: list(database.DEFAULT_WIDGET_PREFERENCES["overview_widgets"]))
    macro_widgets: list[str] = Field(default_factory=lambda: list(database.DEFAULT_WIDGET_PREFERENCES["macro_widgets"]))
    research_widgets: list[str] = Field(default_factory=lambda: list(database.DEFAULT_WIDGET_PREFERENCES["research_widgets"]))
    focused_tickers: list[str] = Field(default_factory=list)
    density: str = "comfortable"
    presentation_level: Literal["simple", "detailed", "expert"] = "detailed"
    terminal_widgets: list[TerminalWidgetPreference] = Field(default_factory=lambda: [TerminalWidgetPreference.model_validate(item) for item in database.DEFAULT_WIDGET_PREFERENCES["terminal_widgets"]], max_length=24)


class TerminalLayoutPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    widgets: list[TerminalWidgetPreference] = Field(max_length=24)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = None
    workspace: Literal["general", "research", "portfolio"] = "general"


class ConversationCreate(BaseModel):
    workspace: Literal["research", "portfolio"]
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class LearningPreferencesPayload(BaseModel):
    selected_path: str | None = Field(default=None, max_length=80)
    knowledge_level: Literal["beginner", "developing", "confident"] = "beginner"
    interests: list[str] = Field(default_factory=list, max_length=20)
    portfolio_context_enabled: bool = False


class LearningProgressPayload(BaseModel):
    module_id: str = Field(min_length=2, max_length=80)
    content_version: str = Field(min_length=2, max_length=40)
    status: Literal["not_started", "in_progress", "completed", "mastered"]
    completion_percentage: float = Field(ge=0, le=1)


class LearningQuizAttemptPayload(BaseModel):
    answers: list[int] = Field(min_length=1, max_length=20)


class LearningLabPayload(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class LearningTutorThreadPayload(BaseModel):
    lesson_id: str = Field(min_length=2, max_length=80)
    title: str | None = Field(default=None, max_length=120)


class LearningTutorMessagePayload(BaseModel):
    question: str = Field(min_length=2, max_length=1200)


def _goal_projection(payload: GoalProjectionRequest) -> dict[str, Any]:
    return shared_goal_projection(payload)


def regime_summary() -> dict[str, Any]:
    history = database.regime_history(1000)
    counts: dict[str, int] = {}
    for row in history:
        key = row["dominant_regime"]
        counts[key] = counts.get(key, 0) + 1
    return {"latest": history[0] if history else None, "sample_counts": counts, "total_samples": len(history)}


@app.get("/api/health")
def health() -> dict[str, Any]:
    mode = database.storage_mode()
    return {"status": "ok", "mode": mode, "storage": mode, "trading_enabled": False}


@app.get("/api/overview")
def overview(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    database.ensure_user_workspace(user.id, InvestorProfile().model_dump(mode="json"))
    # Supabase-backed reads each establish an isolated connection.  These
    # datasets are independent, so fetch them concurrently to keep the shared
    # application shell from serially paying every network round trip.
    with ThreadPoolExecutor(max_workers=8) as pool:
        portfolios_future = pool.submit(database.list_portfolios, user.id)
        profile_future = pool.submit(database.load_profile, user.id)
        scenarios_future = pool.submit(database.latest_scenario_snapshot)
        macro_future = pool.submit(latest_macro)
        analysis_future = pool.submit(database.latest_analysis, user.id)
        preferences_future = pool.submit(database.load_preferences, user.id)
        regime_future = pool.submit(regime_summary)
        monitoring_future = pool.submit(database.latest_monitoring_run)
        promotions_future = pool.submit(database.promotion_decisions, 5)
        portfolios = portfolios_future.result()
        profile = profile_future.result() or InvestorProfile().model_dump(mode="json")
        scenarios = scenarios_future.result()
        macro = macro_future.result()
        latest_analysis = analysis_future.result()
        preferences = preferences_future.result()
        regime_history = regime_future.result()
        monitoring = monitoring_future.result()
        promotions = promotions_future.result()
    portfolio = portfolios[0] if portfolios else None
    # Ordinary page reads must not wait on prediction-market networks.
    scenarios = scenarios or {"scenarios": [], "contracts": [], "warnings": ["No validated prediction-market snapshot is stored yet."], "fetched_at": None}
    if scenarios and "cached" not in scenarios:
        scenarios = {**scenarios, "cached": True}
    holdings = portfolio["holdings"] if portfolio else []
    # The application shell only needs portfolio-linked research. Loading an
    # entire watchlist (including years of prices and filings) made every page
    # wait tens of seconds. Research search/Watchlist load their own evidence
    # on demand instead.
    tickers = [holding["ticker"] for holding in holdings]
    research = security_research(tickers)
    return {
        "portfolio": portfolio, "profile": profile, "macro": macro, "macro_factors": {"factors": []},
        "scenarios": scenarios, "research": research, "storage": database.storage_mode(),
        # Detailed provider counts and factor panels are loaded by their own
        # Research/Advanced endpoints; they should not block every page.
        "data_status": {"counts": {}, "freshness": {}}, "latest_analysis": latest_analysis,
        "regime_history": regime_history,
        "model_monitoring": monitoring,
        "promotion_decisions": promotions,
        "preferences": preferences, "user": {"id": user.id, "email": user.email},
    }


@app.get("/api/home/briefing")
@app.get("/api/today/briefing")
def home_briefing(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    payload = overview(user)
    holdings = (payload.get("portfolio") or {}).get("holdings", [])
    portfolio_tickers = [str(row.get("ticker") or "").upper() for row in holdings]
    market_universe = sorted(set(portfolio_tickers + list(INDEXES) + list(SECTORS)))
    with ThreadPoolExecutor(max_workers=5) as pool:
        prices_future = pool.submit(database.security_data, market_universe, 40)
        observations_future = pool.submit(database.latest_market_observations, market_universe)
        macro_rows_future = pool.submit(database.macro_observation_history, list(MARKET_SERIES), 2)
        events_future = pool.submit(database.upcoming_market_events, portfolio_tickers, 45)
        previous_future = pool.submit(database.latest_briefing_snapshot, user.id)
        price_rows = prices_future.result().get("prices", [])
        observations = [normalize_observation(row) for row in observations_future.result()]
        macro_rows = macro_rows_future.result()
        stored_events = events_future.result()
        previous = previous_future.result()
    has_fresh_snapshot = any(row["data_status"] in {"live", "delayed"} for row in observations)
    # Keep the read path fast: provider I/O belongs to the explicit refresh
    # endpoint.  Snapshot mode is opt-in for installations with the appropriate
    # market-data entitlement; otherwise Today renders stored evidence first.
    if os.getenv("MARKET_SNAPSHOT_MODE", "").strip().lower() == "polygon" and not has_fresh_snapshot:
        try:
            observations = PolygonSnapshotProvider().latest(market_universe)
            database.save_market_observations(observations)
        except Exception:
            # Today must remain available with stored daily prices and a truthful
            # end-of-day/cached label when snapshot access or entitlement fails.
            observations = observations or []
    price_rows = overlay_observations(price_rows, observations)
    events = [*stored_events, *ResearchMarketEventProvider(payload.get("research", [])).upcoming(portfolio_tickers, 45)]
    briefing = build_today_briefing(payload, price_rows, macro_rows, events, previous)
    payload["briefing"] = briefing
    if briefing.get("evidence_state") == "current":
        database.save_briefing_snapshot(user.id, briefing)
    return payload


@app.post("/api/home/refresh")
@app.post("/api/today/refresh")
def refresh_home_briefing(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    """Refresh the market tape and FRED observations before rebuilding Today.

    This is deliberately user initiated because free-provider refreshes can take
    several seconds.  Provider failures are disclosed while the last validated
    snapshot remains usable.
    """
    warnings: list[str] = []
    market_tickers = sorted(set(INDEXES) | set(SECTORS))
    try:
        if os.getenv("TIINGO_API_KEY", "").strip():
            refresh_tiingo(market_tickers)
        elif os.getenv("POLYGON_API_KEY", "").strip():
            refresh_polygon(market_tickers)
        else:
            warnings.append("No price-history provider key is configured for an on-demand market refresh.")
    except Exception as exc:
        warnings.append(f"Market refresh failed; retained the latest validated prices ({type(exc).__name__}).")
    try:
        if os.getenv("FRED_API_KEY", "").strip():
            refresh_fred()
        else:
            warnings.append("FRED is not configured for an on-demand macro refresh.")
    except Exception as exc:
        warnings.append(f"FRED refresh failed; retained the latest validated observations ({type(exc).__name__}).")
    payload = home_briefing(user)
    payload["briefing"]["warnings"] = list(dict.fromkeys([*payload["briefing"].get("warnings", []), *warnings]))
    payload["refresh"] = {"completed_at": datetime.now(timezone.utc).isoformat(), "warnings": warnings}
    return payload


@app.get("/api/terminal/portfolio-performance")
def terminal_portfolio_performance(
    years: int = Query(default=1, ge=1, le=20),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    portfolios = database.list_portfolios(user.id)
    if not portfolios:
        raise HTTPException(404, "No saved portfolio is available")
    return portfolio_performance_widget(portfolios[0], years)


@app.get("/api/terminal/market-indicators")
def terminal_market_indicators(_: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    definitions = {
        "DCOILWTICO": ("WTI crude oil", "USD/barrel"),
        "DGS10": ("10-year Treasury", "% yield"),
        "DTWEXBGS": ("Broad U.S. dollar", "index"),
        "GOLDAMGBD228NLBM": ("Gold fixing", "USD/ounce"),
    }
    rows = database.macro_observation_history(list(definitions), limit_per_series=2)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["series_id"], []).append(row)
    output = []
    for series_id, (label, unit) in definitions.items():
        values = grouped.get(series_id, [])
        if not values:
            continue
        latest, previous = values[0], values[1] if len(values) > 1 else None
        output.append({
            "series_id": series_id, "label": label, "unit": unit,
            "value": latest["value"], "date": latest["date"],
            "change": None if previous is None else round(float(latest["value"]) - float(previous["value"]), 4),
            "source": latest.get("source_url") or f"https://fred.stlouisfed.org/series/{series_id}",
        })
    return output


@app.get("/api/terminal/layouts")
def terminal_layouts(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_terminal_layouts(user.id)


@app.post("/api/terminal/layouts")
def create_terminal_layout(payload: TerminalLayoutPayload, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.save_terminal_layout(user.id, payload.name, [item.model_dump() for item in payload.widgets])


@app.put("/api/terminal/layouts/{layout_id}")
def update_terminal_layout(layout_id: str, payload: TerminalLayoutPayload,
                           user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.save_terminal_layout(user.id, payload.name, [item.model_dump() for item in payload.widgets], layout_id)
    except KeyError as exc:
        raise HTTPException(404, "Terminal layout not found") from exc


@app.delete("/api/terminal/layouts/{layout_id}", status_code=204)
def delete_terminal_layout(layout_id: str, user: AuthenticatedUser = Depends(require_user)) -> None:
    try:
        database.delete_terminal_layout(layout_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Terminal layout not found") from exc


@app.get("/api/portfolios")
def portfolios(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_portfolios(user.id)


@app.post("/api/portfolios")
def create_portfolio(payload: PortfolioPayload, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.save_portfolio(payload.name, [item.model_dump(mode="json") for item in payload.holdings], user_id=user.id)


@app.put("/api/portfolios/{portfolio_id}")
def update_portfolio(portfolio_id: str, payload: PortfolioPayload, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.save_portfolio(payload.name, [item.model_dump(mode="json") for item in payload.holdings], portfolio_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Portfolio not found") from exc


@app.post("/api/portfolios/import")
def import_portfolio(payload: CsvImport, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = parse_portfolio_csv(payload.csv_text, payload.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    holdings = result["holdings"]
    portfolio = database.save_portfolio(payload.name, holdings, user_id=user.id)
    return {
        "portfolio": portfolio,
        "validated_rows": len(holdings),
        **{key: result[key] for key in (
            "warnings", "detected_columns", "ignored_columns", "source_rows",
            "review_rows", "excluded_market_value",
        )},
    }


@app.get("/api/portfolio/diagnostics")
def portfolio_diagnostics(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    portfolios = database.list_portfolios(user.id)
    holdings = portfolios[0].get("holdings", []) if portfolios else []
    tickers = [str(row.get("ticker") or "").upper() for row in holdings if str(row.get("ticker") or "").upper() != "CASH"]
    latest = database.latest_analysis(user.id) or {}
    return build_portfolio_diagnostics(
        holdings,
        database.security_data(tickers, price_limit=1300),
        database.fund_reference_data(tickers),
        latest.get("implementation_paths") or [],
    )


@app.get("/api/profile")
def get_profile(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.load_profile(user.id) or InvestorProfile().model_dump(mode="json")


@app.get("/api/learn/catalog")
def learning_catalog(user: AuthenticatedUser | None = Depends(optional_user)) -> dict[str, Any]:
    payload = catalog_payload(public_only=user is None)
    if user is not None:
        payload["preferences"] = database.load_learning_preferences(user.id)
        payload["progress"] = database.list_learning_progress(user.id)
    return payload


@app.get("/api/learn/lessons/{lesson_id}")
def learning_lesson(lesson_id: str, user: AuthenticatedUser | None = Depends(optional_user)) -> dict[str, Any]:
    try:
        return lesson_payload(lesson_id, public_only=user is None)
    except KeyError as exc:
        raise HTTPException(404, "Learning lesson not found") from exc
    except PermissionError as exc:
        raise HTTPException(401, "Sign in to continue this learning path") from exc


@app.post("/api/learn/labs/{lab_id}/calculate")
def learning_lab(lab_id: str, payload: LearningLabPayload) -> dict[str, Any]:
    try:
        return calculate_lab(lab_id, payload.inputs)
    except KeyError as exc:
        raise HTTPException(404, "Learning lab not found") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/learn/preferences")
def learning_preferences(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.load_learning_preferences(user.id)


@app.put("/api/learn/preferences")
def update_learning_preferences(payload: LearningPreferencesPayload, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    catalog = catalog_payload()
    paths = {module["id"] for module in catalog["modules"]}
    if payload.selected_path is not None and payload.selected_path not in paths:
        raise HTTPException(422, "Unknown learning path")
    return database.save_learning_preferences(user.id, payload.model_dump(mode="json"))


@app.get("/api/learn/progress")
def learning_progress(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_learning_progress(user.id)


@app.put("/api/learn/progress/{lesson_id}")
def update_learning_progress(lesson_id: str, payload: LearningProgressPayload,
                             user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        lesson = lesson_payload(lesson_id)
    except KeyError as exc:
        raise HTTPException(404, "Learning lesson not found") from exc
    if payload.module_id != lesson["module_id"] or payload.content_version != lesson["content_version"]:
        raise HTTPException(422, "Progress must reference the current lesson and content version")
    if payload.status == "mastered":
        attempts = database.list_learning_quiz_attempts(user.id, lesson_id)
        if not attempts or max(float(item["percentage"]) for item in attempts) < .80 or payload.completion_percentage < 1:
            raise HTTPException(422, "Mastery requires lesson completion and a quiz score of at least 80%")
    return database.save_learning_progress(
        user.id, lesson["module_id"], lesson_id, lesson["content_version"],
        payload.status, payload.completion_percentage,
    )


@app.post("/api/learn/quizzes/{quiz_id}/attempts", status_code=201)
def submit_learning_quiz(quiz_id: str, payload: LearningQuizAttemptPayload,
                         user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = grade_quiz(quiz_id, payload.answers)
    except KeyError as exc:
        raise HTTPException(404, "Learning quiz not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    attempt = database.save_learning_quiz_attempt(user.id, result, payload.answers)
    progress = next((item for item in database.list_learning_progress(user.id)
                     if item["lesson_id"] == result["lesson_id"] and item["content_version"] == result["content_version"]), None)
    return {**result, "attempt": attempt, "progress": progress}


@app.get("/api/learn/tutor/threads")
def learning_tutor_threads(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_learning_tutor_threads(user.id)


@app.post("/api/learn/tutor/threads", status_code=201)
def create_learning_tutor_thread(payload: LearningTutorThreadPayload,
                                 user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        lesson = lesson_payload(payload.lesson_id)
    except KeyError as exc:
        raise HTTPException(404, "Learning lesson not found") from exc
    return database.create_learning_tutor_thread(user.id, lesson["id"], payload.title or lesson["title"])


@app.get("/api/learn/tutor/threads/{thread_id}/messages")
def get_learning_tutor_messages(thread_id: str, user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    try:
        return database.learning_tutor_messages(user.id, thread_id)
    except KeyError as exc:
        raise HTTPException(404, "Learning tutor thread not found") from exc


@app.post("/api/learn/tutor/threads/{thread_id}/messages")
def post_learning_tutor_message(thread_id: str, payload: LearningTutorMessagePayload,
                                user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    thread = next((item for item in database.list_learning_tutor_threads(user.id) if item["id"] == thread_id), None)
    if thread is None:
        raise HTTPException(404, "Learning tutor thread not found")
    lesson = lesson_payload(thread["lesson_id"])
    history = database.learning_tutor_messages(user.id, thread_id)
    user_message = database.save_learning_tutor_message(user.id, thread_id, "user", payload.question)
    try:
        answer, model, sources = learning_tutor_answer(payload.question, lesson, history)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    assistant = database.save_learning_tutor_message(
        user.id, thread_id, "assistant", answer, sources,
        {"data_quality": "high", "source_count": len(sources), "method": "lesson-structured-retrieval-v1"}, model,
    )
    return {"thread_id": thread_id, "user_message": user_message, "message": assistant, "sources": sources}


@app.put("/api/profile")
def put_profile(profile: InvestorProfile, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.save_profile(profile.model_dump(mode="json"), user.id)


@app.get("/api/plan/profile")
def plan_profile(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return get_profile(user)


@app.put("/api/plan/profile")
def update_plan_profile(profile: InvestorProfile, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return put_profile(profile, user)


@app.get("/api/plan/goals")
def plan_goals(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_goals(user.id)


@app.post("/api/plan/goals")
def create_plan_goal(goal: FinancialGoal, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.save_goal(user.id, goal.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.put("/api/plan/goals/{goal_id}")
def update_plan_goal(goal_id: str, goal: FinancialGoal, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.save_goal(user.id, goal.model_dump(mode="json"), goal_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Goal not found") from exc


@app.delete("/api/plan/goals/{goal_id}", status_code=204)
def delete_plan_goal(goal_id: str, user: AuthenticatedUser = Depends(require_user)) -> None:
    try:
        database.delete_goal(goal_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Goal not found") from exc


@app.post("/api/plan/projections")
def plan_projection(payload: GoalProjectionRequest, _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return _goal_projection(payload)


@app.get("/api/plan/policy")
def get_plan_policy(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.load_investment_policy(user.id) or InvestmentPolicy().model_dump(mode="json")


@app.put("/api/plan/policy")
def put_plan_policy(policy: InvestmentPolicy, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.save_investment_policy(user.id, policy.model_dump(mode="json"))


@app.post("/api/plan/policy/approve")
def approve_plan_policy(policy: InvestmentPolicy, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    approved = policy.model_copy(update={"status": "approved", "approved_at": datetime.now(timezone.utc)})
    return database.save_investment_policy(user.id, approved.model_dump(mode="json"))


@app.get("/api/plan/guidance")
def plan_guidance(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    portfolios = database.list_portfolios(user.id)
    holdings = portfolios[0].get("holdings", []) if portfolios else []
    goals = database.list_goals(user.id)
    policy = database.load_investment_policy(user.id) or InvestmentPolicy().model_dump(mode="json")
    profile = database.load_profile(user.id) or InvestorProfile().model_dump(mode="json")
    projections = [_goal_projection(GoalProjectionRequest(goal=FinancialGoal.model_validate(goal))) for goal in goals]
    tickers = [row["ticker"] for row in holdings]
    return build_guidance(
        holdings, goals, policy, security_research(tickers), database.provider_data_status(), projections,
        database.latest_monitoring_run(), profile,
    )


@app.post("/api/providers/refresh")
def refresh_providers(force: bool = Query(default=True), _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return refresh_scenarios(force=force)


@app.get("/api/providers/status")
def provider_status(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.provider_data_status()


@app.get("/api/providers/health")
def providers_health(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return build_provider_health()


@app.post("/api/providers/refresh/{provider}")
def refresh_named_provider(
    provider: Literal["fred", "prices", "prediction_markets", "sec"],
    tickers: str = Query(default="SPY", max_length=200),
    _: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    selected = list(dict.fromkeys(value.strip().upper() for value in tickers.split(",") if value.strip()))[:10]
    if provider == "fred":
        rows = refresh_fred()
    elif provider == "prices":
        rows = refresh_tiingo(selected) if os.getenv("TIINGO_API_KEY") else refresh_polygon(selected)
    elif provider == "sec":
        rows = refresh_sec(selected)
    else:
        payload = refresh_scenarios(force=True)
        rows = len(payload.get("contracts", []))
    return {"provider": provider, "rows": rows, "health": build_provider_health()}


@app.get("/api/scenarios")
def scenarios(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return refresh_scenarios(force=False)


@app.get("/api/regimes")
def regimes(limit: int = Query(default=240, ge=1, le=1000), _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return {"model_version": "macro-regime-rules-v1", "history": database.regime_history(limit)}


@app.get("/api/research")
def research(tickers: str = Query(default=""), _: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    values = [ticker.strip().upper() for ticker in tickers.split(",") if ticker.strip()]
    return security_research(values[:50])


def _research_context(user: AuthenticatedUser, query: str = "", explicit: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, Any]]:
    portfolios = database.list_portfolios(user.id)
    holdings = [str(row.get("ticker") or "").upper() for row in (portfolios[0].get("holdings", []) if portfolios else [])]
    profile = database.load_profile(user.id) or InvestorProfile().model_dump(mode="json")
    watchlist = [str(ticker).upper() for ticker in profile.get("watchlist", [])]
    requested = list(explicit or [])
    normalized_query = query.strip().upper()
    fund_lookup: dict[str, dict[str, Any]] = {}
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", normalized_query):
        requested = list(dict.fromkeys([normalized_query, *requested]))
        if recognized_fund(normalized_query):
            fund_lookup[normalized_query] = ensure_fund_data(normalized_query)
    # Explicit symbol lookups are detail requests, not broad discovery scans.
    # Avoid loading and scoring the entire catalog before returning one ticker.
    catalog = [] if explicit and not query else database.list_security_universe(limit=200, query=query or None)
    catalog_tickers = [str(row.get("ticker") or "").upper() for row in catalog]
    # A direct symbol detail request should not pay the cost of rescoring every
    # holding and watchlist item. Those are still passed separately for portfolio-fit context.
    tickers = list(dict.fromkeys(requested if explicit else requested + holdings + watchlist + catalog_tickers))[:200]
    reference = database.research_reference_data(tickers)
    reference["fund_lookup"] = fund_lookup
    return security_research(tickers), holdings, watchlist, reference


@app.get("/api/research/search")
def research_search(
    q: str = Query(default="", max_length=120), fundamentals: str = Query(default=""),
    valuation: str = Query(default=""), theme: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=200), user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    exact = q.strip().upper() if re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,9}", q.strip()) else ""
    rows, holdings, watchlist, reference = _research_context(user, explicit=[exact]) if exact else _research_context(user, q)
    if exact:
        rows = [row for row in rows if str(row.get("ticker") or "").upper() == exact]
    if exact:
        # Exact lookup prioritizes first-card latency. The row already contains
        # stored statistics, freshness, and provider dates; full-universe cycle
        # auditing remains available from /api/research/coverage.
        enriched = rows
        coverage = {
            "summary": {"requested": len(rows), "full_cycle": 0, "insufficient": 0, "insufficient_symbols": []},
            "warnings": [],
        }
    else:
        enriched, coverage = attach_coverage(rows)
    requested = [exact] if exact else []
    payload = research_search_payload(enriched, q, fundamentals, valuation, theme, holdings, watchlist, requested=requested, limit=limit, context=reference)
    payload["historical_coverage"] = coverage
    payload["supported_scope"] = ({
        "query": q,
        "scope": "Active U.S.-listed common stocks and ETFs are core; other instrument tiers are conditional.",
        "results": [{
            "ticker": exact,
            "name": rows[0].get("company") or exact,
            "coverage_tier": "core_us",
            "instrument_type": "common_stock",
            "active": True,
        }] if rows else [],
        "unsupported_reason": None if rows else "No stored research evidence matched this exact symbol.",
    } if exact else database.search_security_master(q, limit=limit)) if q.strip() else {
        "query": "", "scope": "Active U.S.-listed common stocks and ETFs are core; other instrument tiers are conditional.",
        "results": [], "unsupported_reason": None,
    }
    return payload


@app.get("/api/research/universe-support")
def research_universe_support(
    q: str = Query(default="", max_length=120), limit: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    return database.search_security_master(q, limit)


@app.post("/api/research/universe-support/refresh")
def research_universe_refresh(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    rows = refresh_security_catalog()
    return {
        "status": "success", "rows": rows, "version": "security-master-ingestion-v1",
        "scope": "Active U.S. common stocks plus separately labeled conditional ADR coverage.",
        "warning": "Catalog presence establishes discoverability, not complete research evidence.",
    }


@app.get("/api/research/securities/{ticker}")
def research_security(ticker: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    normalized = ticker.strip().upper()
    if not normalized or len(normalized) > 10:
        raise HTTPException(422, "Invalid ticker")
    rows, holdings, watchlist, reference = _research_context(user, explicit=[normalized])
    enriched, coverage = attach_coverage(rows)
    payload = research_search_payload(enriched, normalized, holdings=holdings, watchlist=watchlist, requested=[normalized], limit=1, context=reference)
    if not payload["results"]:
        raise HTTPException(404, "Security research is not available")
    return {"security": payload["results"][0], "universe": payload["universe"], "method": payload["method"], "historical_coverage": coverage}


@app.get("/api/research/securities/{ticker}/overview")
def research_security_overview(ticker: str, _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    payload = security_snapshot_overview(ticker.strip().upper())
    if payload.get("status") == "unavailable":
        raise HTTPException(404, payload["warnings"][0])
    return payload


@app.get("/api/research/securities/{ticker}/technicals")
def research_security_technicals(ticker: str, _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return security_snapshot_technicals(ticker.strip().upper())


@app.get("/api/research/securities/{ticker}/sentiment")
def research_security_sentiment(ticker: str, _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return security_snapshot_sentiment(ticker.strip().upper())


@app.get("/api/research/coverage")
def research_coverage(
    tickers: str = Query(default="", max_length=500),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    explicit = list(dict.fromkeys(value.strip().upper() for value in tickers.split(",") if value.strip()))[:200]
    rows, _, _, _ = _research_context(user, explicit=explicit)
    if explicit:
        rows = [row for row in rows if row.get("ticker") in explicit]
    return build_historical_coverage(rows)


@app.get("/api/research/sectors")
def research_sectors(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    rows, _, _, _ = _research_context(user)
    return sector_summaries(rows)


@app.get("/api/research/themes")
def research_themes(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    rows, _, _, _ = _research_context(user)
    return theme_summaries(rows)


@app.get("/api/research/ideas")
def research_ideas(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    rows, holdings, _, _ = _research_context(user)
    return research_ideas_payload(rows, holdings)


@app.get("/api/research/etfs")
def research_etfs(
    q: str = Query(default="", max_length=120), issuer: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=120), limit: int = Query(default=50, ge=1, le=200),
    _: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    payload = database.search_etf_catalog(q, issuer, category, limit)
    for row in payload["results"]:
        expected = (row.get("metadata") or {}).get("holdings_frequency")
        row["holdings_freshness"] = holdings_freshness(row.get("holdings_as_of"), expected)
    payload["method"] = {
        "name": "US ETF reference catalog with latest dated holdings snapshot",
        "version": "etf-catalog-v1",
        "universe": "Active US-listed ETF and single-security ETF reference records returned by Massive Reference.",
    }
    return payload


@app.get("/api/research/etfs/{ticker}")
def research_etf_detail(ticker: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    normalized = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", normalized):
        raise HTTPException(422, "Invalid ETF ticker")
    portfolios = database.list_portfolios(user.id)
    portfolio_tickers = [str(row.get("ticker") or "").upper() for row in (portfolios[0].get("holdings", []) if portfolios else [])]
    detail = database.etf_research_detail(normalized, portfolio_tickers)
    if not detail:
        raise HTTPException(404, "ETF is not present in the catalog")
    holdings = detail.get("holdings") or []
    expected = (detail["catalog"].get("metadata") or {}).get("holdings_frequency")
    detail["holdings_freshness"] = holdings_freshness(holdings[0].get("as_of") if holdings else None, expected)
    detail["lineage"] = [{
        "provider": holdings[0].get("provider") if holdings else detail["catalog"].get("provider"),
        "dataset": "dated ETF constituent holdings" if holdings else "ETF reference catalog",
        "effective_through": holdings[0].get("as_of") if holdings else detail["catalog"].get("effective_at"),
        "source_url": holdings[0].get("source_url") if holdings else detail["catalog"].get("source_url"),
    }]
    detail["how_calculated"] = "Concentration uses the latest stored holdings snapshot. Top-10 weight is the sum of the ten largest weights; effective holdings is 1 / sum(weight²). Portfolio overlap sums the fund weights of directly held constituents. Sector exposure is a look-through rollup and keeps unclassified weight visible."
    return detail


@app.post("/api/research/etfs/refresh-catalog")
def research_etf_catalog_refresh(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return refresh_etf_catalog()


@app.post("/api/research/etfs/{ticker}/refresh")
def research_etf_refresh(ticker: str, _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    normalized = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", normalized):
        raise HTTPException(422, "Invalid ETF ticker")
    result = ensure_fund_data(normalized, force=True)
    if result.get("status") == "not_applicable":
        raise HTTPException(404, result["reason"])
    return result


@app.get("/api/research/comparisons")
def research_comparisons(
    tickers: str = Query(default="", max_length=200), user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    values = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers.split(",") if ticker.strip()))[:12]
    rows, holdings, _, _ = _research_context(user, explicit=values)
    return research_comparison_payload(rows, values, holdings)


@app.get("/api/explore/securities")
def explore_securities(tickers: str = Query(default=""), user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return research(tickers, user)


@app.get("/api/explore/macro")
def explore_macro(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return {"macro": latest_macro(), "factors": macro_factor_dashboard(), "as_of": latest_macro().get("as_of")}


@app.get("/api/research/macro-workshop")
def research_macro_workshop(
    factor: str = Query(default="inflation"), tickers: str = Query(default="", max_length=500),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    if factor not in MACRO_SENSITIVITY_FACTORS:
        raise HTTPException(422, f"Unsupported macro factor: {factor}")
    requested = list(dict.fromkeys(value.strip().upper() for value in tickers.split(",") if value.strip()))[:30]
    if not requested:
        portfolios = database.list_portfolios(user.id)
        requested = [str(row.get("ticker") or "").upper() for row in (portfolios[0].get("holdings", []) if portfolios else []) if str(row.get("ticker") or "").upper() != "CASH"]
    if not requested:
        requested = ["SPY", "QQQ", "IWM", "XLE", "XLK", "XLF", "XLV"]
    definition = MACRO_SENSITIVITY_FACTORS[factor]
    price_rows = database.price_history(requested, limit_per_ticker=5000)
    macro_rows = database.macro_point_in_time_history([definition["series"]], limit_per_series=600)
    sensitivity = calculate_macro_sensitivity(price_rows, macro_rows, factor)
    regimes = database.regime_history(600)
    counts: dict[str, int] = {}
    for row in regimes:
        key = str(row.get("dominant_regime") or "unclassified")
        counts[key] = counts.get(key, 0) + 1
    return {
        "factor": factor, "factor_definition": definition, "tickers": requested,
        "sensitivity": sensitivity,
        "historical_states": {"total_samples": len(regimes), "counts": counts, "latest_samples": regimes[:24]},
        "coverage": {
            "requested": len(requested),
            "priced": len({row.get("ticker") for row in price_rows}),
            "macro_observations": len(macro_rows),
        },
        "lineage": [
            {"provider": "stored adjusted-price providers", "dataset": "adjusted daily prices", "symbols": requested, "effective_through": max((row.get("date") for row in price_rows if row.get("date")), default=None)},
            {"provider": "FRED/ALFRED", "dataset": definition["series"], "symbols": [], "effective_through": max((row.get("date") for row in macro_rows if row.get("date")), default=None)},
        ],
        "calculation": {"method": "monthly OLS macro sensitivity", "version": "macro-workshop-v1"},
        "warnings": [] if sensitivity.get("rows") else [sensitivity.get("reason") or "Insufficient overlapping monthly history for a quantitative comparison."],
        "disclaimer": "Historical association is not causation, a forecast, or a trade recommendation.",
    }


def _independent_macro_conditions(row: dict[str, Any]) -> dict[str, str]:
    inputs = row.get("inputs") or {}
    industrial = float(inputs.get("industrial_growth_yoy") or 0)
    unemployment_change = float(inputs.get("unemployment_change_3m") or 0)
    inflation = float(inputs.get("inflation_yoy") or 0)
    rate_change = float(inputs.get("policy_rate_change_3m") or 0)
    oil_change = float(inputs.get("oil_change_3m") or 0)
    credit = float(inputs.get("credit_spread") or 0)
    economic = "recession" if industrial < 0 and unemployment_change > .15 else "slowdown" if industrial < 1 or unemployment_change > .05 else "expansion"
    inflation_state = "accelerating" if inflation >= 3 else "cooling" if inflation <= 2 else "stable"
    rate_state = "tightening" if rate_change > .15 else "easing" if rate_change < -.15 else "stable"
    shocks: list[str] = []
    if oil_change >= .15:
        shocks.append("oil")
    if credit >= 5:
        shocks.append("credit")
    return {"economic": economic, "inflation": inflation_state, "rates": rate_state, "shock": "+".join(shocks) if shocks else "none"}


@app.get("/api/research/macro-combination")
def research_macro_combination(
    economic: str = Query(default="any"), inflation: str = Query(default="any"),
    rates: str = Query(default="any"), shock: str = Query(default="any"),
    tickers: str = Query(default="SPY,QQQ,IWM,XLE,XLK", max_length=500),
    _: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    allowed = {
        "economic": {"any", "expansion", "slowdown", "recession"},
        "inflation": {"any", "cooling", "stable", "accelerating"},
        "rates": {"any", "easing", "stable", "tightening"},
        "shock": {"any", "none", "oil", "credit"},
    }
    selected = {"economic": economic, "inflation": inflation, "rates": rates, "shock": shock}
    for key, value in selected.items():
        if value not in allowed[key]:
            raise HTTPException(422, f"Unsupported {key} condition: {value}")
    requested = list(dict.fromkeys(value.strip().upper() for value in tickers.split(",") if value.strip()))[:30]
    labels = database.regime_history(1000)
    classified = [{**row, "conditions": _independent_macro_conditions(row)} for row in labels]
    def matches(row: dict[str, Any]) -> bool:
        conditions = row["conditions"]
        return all(
            value == "any" or (key == "shock" and value in conditions[key].split("+")) or conditions[key] == value
            for key, value in selected.items()
        )
    analogs = [row for row in classified if matches(row)]
    prices = database.price_history(requested, limit_per_ticker=5000)
    results: list[dict[str, Any]] = []
    if prices and analogs:
        frame = pd.DataFrame(prices)
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        monthly = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().resample("ME").last().pct_change(fill_method=None)
        monthly.index = monthly.index.tz_localize(None).to_period("M")
        analog_months = {pd.Period(pd.Timestamp(row["as_of_date"]), freq="M") for row in analogs}
        for ticker in requested:
            if ticker not in monthly:
                continue
            sample = monthly.loc[monthly.index.isin(analog_months), ticker].dropna()
            if sample.empty:
                continue
            results.append({
                "ticker": ticker, "sample_count": int(len(sample)),
                "average_monthly_return": round(float(sample.mean()), 6),
                "median_monthly_return": round(float(sample.median()), 6),
                "positive_month_frequency": round(float((sample > 0).mean()), 6),
                "worst_month": round(float(sample.min()), 6),
                "best_month": round(float(sample.max()), 6),
                "annualized_return_equivalent": round(float((1 + sample.mean()) ** 12 - 1), 6) if float(sample.mean()) > -1 else None,
            })
    results.sort(key=lambda row: row["average_monthly_return"], reverse=True)
    current = classified[0] if classified else None
    return {
        "selected_conditions": selected,
        "current_conditions": current.get("conditions") if current else None,
        "current_as_of": current.get("as_of_date") if current else None,
        "analog_count": len(analogs),
        "analog_dates": [row["as_of_date"] for row in analogs[:24]],
        "results": results,
        "coverage": {"requested": len(requested), "priced": len({row.get("ticker") for row in prices}), "classified_months": len(labels)},
        "lineage": [
            {"provider": "FRED/ALFRED", "dataset": "point-in-time macro regime inputs", "effective_through": labels[0]["as_of_date"] if labels else None},
            {"provider": "stored adjusted-price providers", "dataset": "monthly adjusted closes", "effective_through": max((row.get("date") for row in prices if row.get("date")), default=None)},
        ],
        "calculation": {"method": "independent-condition historical intersection", "version": "macro-combination-v1"},
        "warnings": [] if len(analogs) >= 12 else [f"Only {len(analogs)} historical months matched; treat the comparison as low-confidence."],
        "disclaimer": "Conditions are deterministic research labels. Historical association is not a forecast or recommendation.",
    }


@app.get("/api/explore/scenarios")
def explore_scenarios(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return scenarios(user)


@app.get("/api/explore/prediction-markets")
def explore_prediction_markets(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    payload = scenarios(user)
    return {"contracts": payload.get("contracts", []), "fetched_at": payload.get("fetched_at"), "warnings": payload.get("warnings", [])}


@app.post("/api/research/refresh")
def refresh_research(payload: ResearchRefresh, _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    values = list(dict.fromkeys(
        ticker.strip().upper() for ticker in payload.tickers if ticker.strip() and ticker.upper() != "CASH"
    ))[:50]
    ingest_values = list(dict.fromkeys(
        ticker.strip().upper() for ticker in payload.ingest_tickers
        if ticker.strip() and ticker.upper() != "CASH" and ticker.strip().upper() in values
    ))
    evidence = refresh_security_evidence(ingest_values)
    master_records = database.sync_security_master(ingest_values) if ingest_values else 0
    current = security_research(values)
    coverage_snapshots = database.save_security_coverage_snapshots(current) if ingest_values else 0
    companies = {row["ticker"]: row.get("company") or row["ticker"] for row in current}
    provider = refresh_company_markets(companies)
    return {
        "research": security_research(values),
        "provider": "Polymarket",
        "searched": provider["searched"],
        "markets_found": len(provider["markets"]),
        "warnings": [*evidence["warnings"], *provider["warnings"]],
        "evidence_refresh": evidence, "security_master_records": master_records,
        "coverage_snapshots": coverage_snapshots,
    }


@app.post("/api/analyses")
def create_analysis(request: AnalysisRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    if request.portfolio is not None:
        holdings = [item.model_dump(mode="json") for item in request.portfolio.holdings]
    else:
        portfolios = database.list_portfolios(user.id)
        portfolio_id = request.portfolio_id or (portfolios[0]["id"] if portfolios else None)
        if portfolio_id is None:
            raise HTTPException(422, "A portfolio is required")
        try:
            holdings = database.get_portfolio(portfolio_id, user.id)["holdings"]
        except KeyError as exc:
            raise HTTPException(404, "Portfolio not found") from exc
    profile = request.profile or InvestorProfile.model_validate(database.load_profile(user.id) or {})
    result = run_analysis(holdings, profile)
    database.save_analysis(result["id"], request.model_dump(mode="json"), result, user.id)
    return result


@app.post("/api/portfolio/analysis")
def portfolio_analysis(request: AnalysisRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return create_analysis(request, user)


@app.post("/api/simulations/runs")
def create_simulation_run(payload: SimulationRunInput, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = run_simulation(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    database.save_simulation_run(user.id, result)
    return result


@app.get("/api/simulations/runs/{run_id}")
def get_simulation_run(run_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    result = database.load_simulation_run(user.id, run_id)
    if not result:
        raise HTTPException(404, "Simulation run not found")
    return result


@app.post("/api/simulations/runs/{run_id}/compare")
def compare_simulation_run(run_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    result = database.load_simulation_run(user.id, run_id)
    if not result:
        raise HTTPException(404, "Simulation run not found")
    return {"id": run_id, "shared_path_fingerprint": result["shared_path_fingerprint"], "outcomes": result["outcomes"], "model_version": result["model_version"]}


@app.post("/api/simulations/runs/{run_id}/optimize")
def optimize_simulation_run(run_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    result = database.load_simulation_run(user.id, run_id)
    if not result:
        raise HTTPException(404, "Simulation run not found")
    outcomes = result["outcomes"]
    candidates = [
        ("Least disruptive", min(outcomes, key=lambda row: (row.get("turnover", 1), row.get("regret", 0)))),
        ("Lower downside", min(outcomes, key=lambda row: (row.get("probability_of_loss", 1), row.get("drawdown_percentiles", {}).get("p10", -1) * -1))),
        ("Balanced tradeoff", next((row for row in outcomes if row.get("strategy_key") == "balanced"), outcomes[0])),
        ("Higher goal potential", max(outcomes, key=lambda row: row.get("wealth_percentiles", {}).get("p50", 0))),
    ]
    choices = []
    used: set[str] = set()
    for label, outcome in candidates:
        key = outcome.get("strategy_key", label)
        if key in used:
            alternative = next((row for row in outcomes if row.get("strategy_key") not in used), None)
            if alternative is not None:
                outcome, key = alternative, alternative.get("strategy_key", label)
        used.add(key)
        choices.append({"frontier_label": label, **outcome})
    return {"id": run_id, "decision_frontier": choices, "diagnostics": [], "note": "No option is labeled the single best portfolio."}


@app.post("/api/builders/etf/optimize")
def build_etf_allocation(payload: ETFAllocationRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    result = optimize_etfs(payload)
    result["id"] = database.save_builder_run(user.id, "etf", payload.model_dump(mode="json"), result)
    return result


@app.post("/api/builders/stocks/optimize")
def build_stock_basket(payload: StockBasketRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    result = optimize_stocks(payload)
    result["id"] = database.save_builder_run(user.id, "stock", payload.model_dump(mode="json"), result)
    return result


@app.post("/api/portfolio/transactions/import")
def portfolio_transaction_import(payload: TransactionCsvImport, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    parsed = parse_transaction_csv(payload.csv_text, payload.account_id)
    result = {**parsed, "reconstruction": reconstruct_positions(parsed["rows"]), "saved": None}
    if payload.save and parsed["rows"]:
        if parsed["errors"]:
            raise HTTPException(422, {"message": "Resolve transaction import errors before saving.", **result})
        result["saved"] = database.save_portfolio_transactions(user.id, payload.account_id, parsed["rows"])
    return result


@app.post("/api/portfolio/performance")
def portfolio_account_performance(payload: AccountPerformanceRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    transactions = payload.transactions or database.account_transactions(user.id, payload.account_id)
    result = calculate_performance(transactions, payload.valuations)
    return {
        **result, "label": "Actual account performance from imported transaction and valuation history" if result.get("status") == "ready" else "Actual account performance unavailable",
        "hypothetical_label": "Hypothetical one-year return using current holdings and weights",
        "lineage": [{"provider": "user-imported ledger", "dataset": "transactions and reconciled valuations", "symbols": sorted({row.get('ticker') for row in transactions if row.get('ticker')})}],
    }


@app.post("/api/portfolio/reconcile")
def portfolio_reconcile(payload: StatementReconciliationRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.save_statement_reconciliation(user.id, payload.model_dump(mode="json"))


@app.get("/api/portfolio/tax-coverage")
def portfolio_tax_coverage(
    account_id: str = Query(min_length=1, max_length=120), jurisdiction: str | None = Query(default=None, max_length=80),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    return tax_lot_coverage(database.account_transactions(user.id, account_id), jurisdiction)


@app.get("/api/analyses/{run_id}")
def get_analysis(run_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.load_analysis(run_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Analysis run not found") from exc


@app.get("/api/model-validation")
def model_validation(limit: int = Query(default=20, ge=1, le=100), _: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return {"runs": database.validation_history(limit)}


@app.get("/api/model-monitoring")
def model_monitoring(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return {
        "latest": database.latest_monitoring_run(),
        "promotion_decisions": database.promotion_decisions(20),
    }


@app.get("/api/operations/metrics")
def operations_metrics(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return {
        **operational_snapshot(),
        "providers": build_provider_health(),
        "models": {
            "latest_monitoring": database.latest_monitoring_run(),
            "latest_validation": database.validation_history(1),
        },
        "error_monitoring": ERROR_MONITORING,
    }


@app.get("/api/models/diagnostics")
def model_diagnostics(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return {
        "monitoring": model_monitoring(user), "validation": model_validation(20, user),
        "latest_analysis": database.latest_analysis(user.id),
    }


@app.post("/api/analyses/{run_id}/explanation")
def explain(run_id: str, request: ExplanationRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = database.load_analysis(run_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Analysis run not found") from exc
    return generate_explanation(result, request.provider, request.endpoint, request.model)


@app.get("/api/preferences")
def get_preferences(user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return database.load_preferences(user.id)


@app.put("/api/preferences")
def put_preferences(payload: WidgetPreferences, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    if payload.density not in {"compact", "comfortable"}:
        raise HTTPException(422, "Density must be compact or comfortable")
    return database.save_preferences(user.id, payload.model_dump())


@app.get("/api/macro/factors")
def macro_factors(_: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    return macro_factor_dashboard()


@app.get("/api/chat/conversations")
def conversations(workspace: Literal["research", "portfolio"] | None = None,
                  user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_conversations(user.id, workspace)


@app.post("/api/chat/conversations", status_code=201)
def create_chat_conversation(payload: ConversationCreate,
                             user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    portfolio = (database.list_portfolios(user.id) or [{}])[0]
    return database.create_conversation(user.id, payload.title, portfolio.get("id"), payload.workspace)


@app.get("/api/chat/conversations/{conversation_id}")
def conversation(conversation_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        item = database.get_conversation(user.id, conversation_id)
    except KeyError as exc:
        raise HTTPException(404, "Conversation not found") from exc
    return {**item, "messages": database.conversation_messages(user.id, conversation_id),
            "artifacts": database.conversation_artifacts(user.id, conversation_id)}


@app.patch("/api/chat/conversations/{conversation_id}")
def rename_chat_conversation(conversation_id: str, payload: ConversationUpdate,
                             user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.rename_conversation(user.id, conversation_id, payload.title)
    except KeyError as exc:
        raise HTTPException(404, "Conversation not found") from exc


@app.delete("/api/chat/conversations/{conversation_id}", status_code=204)
def delete_chat_conversation(conversation_id: str,
                             user: AuthenticatedUser = Depends(require_user)) -> None:
    try:
        database.delete_conversation(user.id, conversation_id)
    except KeyError as exc:
        raise HTTPException(404, "Conversation not found") from exc


_CHAT_SECURITY_STOPWORDS = {
    "AI", "ETF", "ETFS", "SEC", "CPI", "GDP", "FED", "USD", "CEO", "THE", "WHEN", "WHAT", "WHY",
    "HOW", "WILL", "WITH", "HIGH", "LOW", "SELL", "BUY", "HOLD", "STOCK", "PRICE", "PRICES", "MARKET",
    "MEMORY", "DATACENTERS", "DATA", "CENTER", "CENTERS", "TIMEFRAME", "NEWS", "CURRENT", "LATEST",
}

_CHAT_RESEARCH_CACHE = TTLCache(max_entries=128)
_CHAT_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="chat-tool")


def _resolve_chat_tickers(question: str) -> list[str]:
    """Resolve explicit symbols and unambiguous company-name tokens against the supported master."""
    resolved: list[str] = []
    explicit = [value for value in re.findall(r"\b[A-Z]{1,5}\b", question) if value not in _CHAT_SECURITY_STOPWORDS]
    for token in explicit[:8]:
        try:
            matches = database.search_security_master(token, limit=5).get("results", [])
        except Exception:
            matches = []
        exact = next((row for row in matches if str(row.get("ticker", "")).upper() == token), None)
        if exact:
            resolved.append(token)
    if resolved:
        return list(dict.fromkeys(resolved))[:3]
    candidate_words = [
        word for word in re.findall(r"\b[A-Za-z][A-Za-z.&-]{3,}\b", question)
        if word.upper() not in _CHAT_SECURITY_STOPWORDS
    ]
    for word in candidate_words[:10]:
        try:
            matches = database.search_security_master(word, limit=5).get("results", [])
        except Exception:
            continue
        exact_names = [row for row in matches if str(row.get("name", "")).lower().split(" ")[0] == word.lower()]
        if len(exact_names) == 1:
            resolved.append(str(exact_names[0]["ticker"]).upper())
    return list(dict.fromkeys(resolved))[:3]


def _evidence_age_days(value: Any) -> int | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return max(0, (datetime.now(timezone.utc) - parsed.to_pydatetime()).days)


def _company_research_chat_tools(question: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tickers = _resolve_chat_tickers(question)
    if not tickers:
        return [], []
    cache_key = ",".join(sorted(tickers))
    cached = _CHAT_RESEARCH_CACHE.get(cache_key)
    if cached is not None:
        from .operational_monitoring import record_metric
        record_metric("chat.company_research_cache_hit")
        return cached
    before = {row["ticker"]: row for row in security_research(tickers)}
    refresh_tickers = [
        ticker for ticker in tickers
        if before.get(ticker, {}).get("price") is None
        or (_evidence_age_days(before.get(ticker, {}).get("price_as_of")) or 999) > 3
        or before.get(ticker, {}).get("fundamentals_as_of") is None
        or before.get(ticker, {}).get("latest_news") is None
    ]
    refresh_result = {"providers": {}, "warnings": []}
    if refresh_tickers:
        refresh_result = refresh_security_evidence(refresh_tickers, news_lookback_days=90)
    rows = {row["ticker"]: row for row in security_research(tickers)}
    raw = database.security_data(tickers, price_limit=10) if database.DATABASE_URL else {"news": []}
    news_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for item in raw.get("news", []):
        news_by_ticker.setdefault(str(item.get("ticker", "")).upper(), []).append(item)
    tools: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for ticker in tickers:
        row = rows.get(ticker, {})
        articles = news_by_ticker.get(ticker, [])[:12]
        article_summaries = [{
            "title": item.get("title"), "published_at": item.get("published_at"), "source_url": item.get("source_url"),
            "source": (item.get("metadata") or {}).get("source"), "summary": (item.get("metadata") or {}).get("summary"),
        } for item in articles]
        missing = [label for key, label in (
            ("price", "current price history"), ("fundamentals_as_of", "recent fundamentals"),
        ) if row.get(key) is None]
        if not articles:
            missing.append("recent company news")
        warnings = [*refresh_result.get("warnings", [])]
        if missing:
            warnings.append(f"Missing: {', '.join(missing)}.")
        tool = {
            "tool_name": "company_research_refresh", "status": "partial" if warnings else "complete", "title": f"{ticker} company evidence", "ticker": ticker,
            "input_summary": {"news_lookback_days": 90, "refresh_performed": ticker in refresh_tickers},
            "summary": {
                "company": row.get("company") or ticker, "price": row.get("price"), "price_as_of": row.get("price_as_of"),
                "fundamentals_as_of": row.get("fundamentals_as_of"), "revenue_growth": row.get("revenue_growth"),
                "net_margin": row.get("net_margin"), "valuation": row.get("valuation_evidence") or {},
                "market_statistics": row.get("market_statistics") or {}, "component_coverage": row.get("component_coverage") or {},
                "news": {"article_count": len(articles), "articles": article_summaries},
                "warnings": warnings, "model_version": "company-chat-research-v1",
            },
        }
        tools.append(tool)
        evidence.append({
            "label": f"{ticker} refreshed company research", "as_of": row.get("price_as_of") or row.get("fundamentals_as_of"),
            "url": row.get("fundamental_statistics", {}).get("source") or row.get("source"),
            "data": {key: row.get(key) for key in (
                "ticker", "company", "sector", "industry", "price", "price_as_of", "fundamentals_as_of", "revenue_growth",
                "net_margin", "valuation_evidence", "market_statistics", "fundamental_statistics", "news_sentiment",
                "component_coverage", "risk_flags", "data_quality",
            )} | {"refresh_warnings": warnings},
        })
        for article in article_summaries[:8]:
            evidence.append({
                "label": f"{ticker} news: {article.get('title') or 'Untitled article'}", "as_of": article.get("published_at"),
                "url": article.get("source_url"), "data": {"ticker": ticker, **article},
            })
    result = (tools, evidence)
    _CHAT_RESEARCH_CACHE.put(cache_key, result, ttl_seconds=120)
    return result


def _simulation_scenario_from_question(question: str) -> dict[str, Any]:
    lowered = question.lower()
    if "recession" in lowered or "market falls" in lowered or "market fell" in lowered:
        economic = "recession"
    elif "slowdown" in lowered:
        economic = "slowdown"
    elif "expansion" in lowered:
        economic = "expansion"
    else:
        economic = "unconditioned"
    if "accelerating inflation" in lowered or "higher inflation" in lowered or "inflation rises" in lowered:
        inflation = "accelerating"
    elif "cooling inflation" in lowered or "lower inflation" in lowered:
        inflation = "cooling"
    else:
        inflation = "unconditioned"
    if "rate hike" in lowered or "higher rates" in lowered or "tightening" in lowered:
        rates = "tightening"
    elif "rate cut" in lowered or "lower rates" in lowered or "easing" in lowered:
        rates = "easing"
    else:
        rates = "unconditioned"
    shocks = [shock for shock in ("oil", "credit", "geopolitical") if shock in lowered]
    return {"economic_state": economic, "inflation_state": inflation, "rate_state": rates, "shocks": shocks}


def _portfolio_chat_tools(user_id: str, question: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Route portfolio questions to a small allowlist of deterministic, read-only tools."""
    lowered = question.lower()
    tool_results: list[dict[str, Any]] = []
    tool_evidence: list[dict[str, Any]] = []
    simulation_requested = any(term in lowered for term in (
        "simulate", "simulation", "what if", "stress test", "market falls", "market fell",
        "drawdown scenario", "recession scenario", "oil shock", "credit shock",
    ))
    if simulation_requested:
        portfolios = database.list_portfolios(user_id)
        if not portfolios or not portfolios[0].get("holdings"):
            tool_results.append({
                "tool_name": "portfolio_decision_lab", "status": "failed", "title": "Portfolio simulation",
                "error": "Save at least one supported holding before running a portfolio simulation.",
            })
        else:
            portfolio = portfolios[0]
            try:
                simulation_input = SimulationRunInput.model_validate({
                    "portfolio_id": portfolio.get("id"),
                    "holdings": portfolio["holdings"],
                    "profile": database.load_profile(user_id) or {},
                    "goals": database.list_goals(user_id),
                    "scenario": _simulation_scenario_from_question(question),
                    "paths": 1000,
                    "seed": 90210,
                })
                result = run_simulation(simulation_input)
                if re.search(r"\b\d{1,2}\s*%", question):
                    result.setdefault("warnings", []).append(
                        "The engine conditions on historical states; it does not impose the question's exact percentage as an instantaneous market shock."
                    )
                database.save_simulation_run(user_id, result)
                strategies = [{
                    "key": item["strategy_key"], "label": item.get("label") or item["strategy_key"].replace("_", " ").title(),
                    "median_wealth": item["wealth_percentiles"]["p50"],
                    "probability_of_loss": item["probability_of_loss"],
                    "modeled_drawdown": item["drawdown_percentiles"]["p10"],
                    "robustness": item["robustness"],
                } for item in result["outcomes"]]
                tool_result = {
                    "tool_name": "portfolio_decision_lab", "status": "complete", "title": "Portfolio simulation",
                    "run_id": result["id"],
                    "input_summary": {"paths": simulation_input.paths, "horizon_years": simulation_input.horizon_years or simulation_input.profile.horizon_years, "scenario": simulation_input.scenario.model_dump()},
                    "summary": {"strategies": strategies, "warnings": result.get("warnings", []), "model_version": result["model_version"]},
                }
                tool_results.append(tool_result)
                tool_evidence.append({
                    "label": "Portfolio Decision Lab tool result", "as_of": result["created_at"], "url": None,
                    "data": {"run_id": result["id"], "input": tool_result["input_summary"], "outcomes": strategies, "warnings": result.get("warnings", []), "assumptions": result.get("assumptions", []), "lineage": result.get("lineage", [])},
                })
            except Exception as exc:
                tool_results.append({
                    "tool_name": "portfolio_decision_lab", "status": "failed", "title": "Portfolio simulation",
                    "error": str(exc),
                })
    if any(term in lowered for term in ("rebalance", "alternative", "optimizer", "allocation", "concentration", "risk")):
        analysis = database.latest_analysis(user_id)
        if analysis:
            tool_results.append({
                "tool_name": "latest_portfolio_analysis", "status": "complete",
                "title": "Latest portfolio analysis", "run_id": analysis.get("id"),
            })
    if any(term in lowered for term in ("stock", "holding", "research", "evidence", "replacement", "strongest", "weakest")):
        tool_results.append({"tool_name": "security_research", "status": "complete", "title": "Stored security research"})
    return tool_results, tool_evidence


def _conversation_summary(messages: list[dict[str, Any]], previous: str = "") -> str:
    """Create compact deterministic memory without asking the LLM to invent context."""
    user_topics = [
        " ".join(str(item.get("content", "")).split())[:220]
        for item in messages if item.get("role") == "user" and item.get("content")
    ][-8:]
    tools: list[str] = []
    for item in messages[-20:]:
        structured = item.get("structured_content") or {}
        for result in structured.get("tool_results", []) if isinstance(structured, dict) else []:
            label = str(result.get("title") or result.get("tool_name") or "tool result")
            identifier = result.get("run_id") or result.get("ticker")
            tools.append(f"{label}{f' ({identifier})' if identifier else ''}")
    sections = []
    if previous:
        sections.append(f"Earlier context: {previous[:1400]}")
    if user_topics:
        sections.append("User topics: " + " | ".join(user_topics))
    if tools:
        sections.append("Validated tools used: " + ", ".join(dict.fromkeys(tools[-10:])))
    return "\n".join(sections)[-4000:]


def _persist_chat_tool_links(user_id: str, conversation_id: str, message_id: str,
                             tool_results: list[dict[str, Any]]) -> None:
    for result in tool_results:
        tool_name = result.get("tool_name")
        artifact_type: str | None = None
        artifact_id: str | None = None
        if tool_name == "portfolio_decision_lab" and result.get("run_id"):
            artifact_type, artifact_id = "simulation_run", str(result["run_id"])
        elif tool_name == "latest_portfolio_analysis" and result.get("run_id"):
            artifact_type, artifact_id = "analysis_run", str(result["run_id"])
        elif tool_name == "company_research_refresh" and result.get("ticker"):
            as_of = (result.get("summary") or {}).get("price_as_of") or "latest"
            artifact_type, artifact_id = "research_snapshot", f"{result['ticker']}:{as_of}"
        if artifact_type and artifact_id:
            database.link_conversation_artifact(
                user_id, conversation_id, artifact_type, artifact_id,
                str(result.get("title") or tool_name), message_id=message_id,
                metadata={"tool_name": tool_name, "status": result.get("status")},
            )


@app.post("/api/chat/messages")
def chat_message(payload: ChatRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    if not database.DATABASE_URL:
        raise HTTPException(503, "Chat history requires Supabase storage")
    conversation_id = payload.conversation_id
    if conversation_id is None:
        portfolio = (database.list_portfolios(user.id) or [{}])[0]
        workspace = payload.workspace if payload.workspace in {"research", "portfolio"} else "research"
        created = database.create_conversation(user.id, payload.question[:72], portfolio.get("id"), workspace)
        conversation_id = created["id"]
    try:
        conversation_meta = database.get_conversation(user.id, conversation_id)
    except KeyError as exc:
        raise HTTPException(404, "Conversation not found") from exc
    if payload.workspace in {"research", "portfolio"} and conversation_meta.get("workspace") != payload.workspace:
        raise HTTPException(409, "This conversation belongs to a different workspace")
    history = database.conversation_messages(user.id, conversation_id)
    if not history and str(conversation_meta.get("title", "")).lower().startswith("new conversation"):
        conversation_meta = database.rename_conversation(user.id, conversation_id, payload.question[:72])
    database.save_chat_message(user.id, conversation_id, "user", payload.question)
    evidence_future = _CHAT_TOOL_EXECUTOR.submit(retrieve_evidence, user.id, payload.question)
    company_future = _CHAT_TOOL_EXECUTOR.submit(_company_research_chat_tools, payload.question)
    portfolio_future = (
        _CHAT_TOOL_EXECUTOR.submit(_portfolio_chat_tools, user.id, payload.question)
        if payload.workspace == "portfolio" else None
    )
    tool_results: list[dict[str, Any]] = []
    try:
        evidence = evidence_future.result(timeout=12)
    except (FuturesTimeoutError, Exception) as exc:
        evidence = []
        tool_results.append({"tool_name": "stored_evidence", "status": "failed", "title": "Stored evidence", "error": f"Evidence lookup did not complete quickly: {type(exc).__name__}"})
    try:
        company_tools, company_evidence = company_future.result(timeout=18)
        tool_results.extend(company_tools)
        evidence = company_evidence + evidence
    except (FuturesTimeoutError, Exception) as exc:
        tool_results.append({"tool_name": "company_research_refresh", "status": "failed", "title": "Company evidence", "error": f"Provider refresh timed out; the answer uses other available evidence ({type(exc).__name__})."})
    if portfolio_future is not None:
        try:
            portfolio_tools, tool_evidence = portfolio_future.result(timeout=18)
            tool_results.extend(portfolio_tools)
            evidence.extend(tool_evidence)
        except (FuturesTimeoutError, Exception) as exc:
            tool_results.append({"tool_name": "portfolio_tools", "status": "failed", "title": "Portfolio calculation", "error": f"Calculation timed out; no result was invented ({type(exc).__name__})."})
    # Keep the grounded prompt bounded even when several securities each have
    # multiple articles. On-demand company evidence is ordered first so the
    # tool the user explicitly requested cannot be crowded out by older context.
    evidence = evidence[:36]
    try:
        answer, model = ask_gemini(payload.question, evidence, history, conversation_meta.get("summary") or "")
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    sources = [{"id": f"S{index + 1}", "label": item["label"], "url": item.get("url"), "as_of": item.get("as_of")} for index, item in enumerate(evidence)]
    structured_content = {"sources": sources, "tool_results": tool_results}
    message = database.save_chat_message(user.id, conversation_id, "assistant", answer, structured_content, model)
    _persist_chat_tool_links(user.id, conversation_id, message["id"], tool_results)
    updated_history = [*history, {"role": "user", "content": payload.question}, message]
    summarized_count = int(conversation_meta.get("summary_message_count") or 0)
    if len(updated_history) >= 12 and len(updated_history) - summarized_count >= 8:
        database.update_conversation_summary(
            user.id, conversation_id,
            _conversation_summary(updated_history, conversation_meta.get("summary") or ""),
            len(updated_history),
        )
    return {"conversation_id": conversation_id, "message": message, "sources": sources, "tool_results": tool_results}


@app.post("/api/dashboard/drafts", status_code=202)
def dashboard_draft(payload: DraftRequest, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return create_draft(user.id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/dashboard/drafts/{job_id}")
def dashboard_draft_status(job_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.get_dashboard_job(job_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard draft not found") from exc


@app.get("/api/dashboard/drafts/{job_id}/events")
def dashboard_draft_events(job_id: str, user: AuthenticatedUser = Depends(require_user)) -> StreamingResponse:
    try:
        database.get_dashboard_job(job_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard draft not found") from exc

    def events():
        last_signature = None
        for _ in range(600):
            job = database.get_dashboard_job(job_id, user.id)
            signature = (job.get("updated_at"), job.get("state"), job.get("progress"))
            if signature != last_signature:
                yield f"event: dashboard\ndata: {json.dumps(job, default=str)}\n\n"
                last_signature = signature
            if job["state"] in TERMINAL_STATES:
                yield f"event: done\ndata: {json.dumps({'state': job['state']})}\n\n"
                return
            time.sleep(.35)
        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/dashboard/drafts/{job_id}/revise", status_code=202)
def revise_dashboard_draft(job_id: str, payload: RevisionRequest,
                           user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return revise_draft(user.id, job_id, payload)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard draft not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/dashboard/catalog")
def dashboard_catalog(_: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return dashboard_data_catalog()


@app.post("/api/dashboard/drafts/{job_id}/widgets", status_code=202)
def add_dashboard_draft_widget(job_id: str, payload: WidgetAddRequest,
                               user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return add_widget_to_draft(user.id, job_id, payload.widget_type)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard draft not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch("/api/dashboard/drafts/{job_id}/layout/widgets/{widget_id}")
def mutate_dashboard_draft_widget(job_id: str, widget_id: str, payload: LayoutMutationRequest,
                                  user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return mutate_draft_layout(user.id,job_id,widget_id,payload)
    except KeyError as exc:
        raise HTTPException(404,"Dashboard widget not found") from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@app.post("/api/dashboard/drafts/{job_id}/cancel")
def cancel_dashboard_draft(job_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        job = database.get_dashboard_job(job_id, user.id)
        if job["state"] not in TERMINAL_STATES:
            job = database.update_dashboard_job(job_id, user.id, state="CANCELLED", cancelled_at=database.utc_now())
        return job
    except KeyError as exc:
        raise HTTPException(404, "Dashboard draft not found") from exc


@app.post("/api/dashboard/drafts/{job_id}/save")
def save_dashboard_draft(job_id: str, payload: SaveViewRequest,
                         user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        job = database.get_dashboard_job(job_id, user.id)
        if job["state"] not in {"COMPLETE", "PARTIAL_SUCCESS"}:
            raise HTTPException(409, "Dashboard draft must finish before it can be saved")
        saved = database.save_dashboard_view(user.id, job_id, payload.name, payload.layout)
        if job.get("conversation_id"):
            database.link_conversation_artifact(
                user.id, job["conversation_id"], "dashboard_view", saved["id"],
                saved.get("name") or "Saved research board",
                metadata={"job_id": job_id},
            )
        return saved
    except KeyError as exc:
        raise HTTPException(404, "Dashboard draft not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/dashboard/views")
def dashboard_views(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    return database.list_dashboard_views(user.id)


@app.get("/api/dashboard/views/{view_id}")
def dashboard_view(view_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.get_dashboard_view(view_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard view not found") from exc


@app.get("/api/dashboard/views/{view_id}/revisions")
def dashboard_view_revisions(view_id: str, user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
    try:
        database.get_dashboard_view(view_id,user.id)
        return database.list_dashboard_revisions(view_id,user.id)
    except KeyError as exc:
        raise HTTPException(404,"Dashboard view not found") from exc


@app.post("/api/dashboard/views/{view_id}/duplicate")
def duplicate_dashboard_view(view_id: str, payload: DuplicateViewRequest,
                             user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.duplicate_dashboard_view(view_id,user.id,payload.name)
    except KeyError as exc:
        raise HTTPException(404,"Dashboard view not found") from exc


@app.put("/api/dashboard/views/{view_id}")
def update_dashboard_view(view_id: str, payload: UpdateViewRequest,
                          user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.update_dashboard_view(view_id, user.id, payload.name, payload.layout)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard view not found") from exc


@app.delete("/api/dashboard/views/{view_id}", status_code=204)
def delete_dashboard_view(view_id: str, user: AuthenticatedUser = Depends(require_user)) -> None:
    try:
        database.delete_dashboard_view(view_id, user.id)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard view not found") from exc


@app.post("/api/dashboard/views/{view_id}/refresh", status_code=202)
def refresh_dashboard_view(view_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        view = database.get_dashboard_view(view_id, user.id)
        portfolio_id = (view.get("plan") or {}).get("entities", {}).get("portfolio_id")
        return create_draft(user.id, DraftRequest(prompt=view["original_prompt"], portfolio_id=portfolio_id), view_id)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard view not found") from exc


@app.post("/api/dashboard/views/{view_id}/widgets", status_code=202)
def add_dashboard_view_widget(view_id: str, payload: WidgetAddRequest,
                              user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return add_widget_to_view(user.id, view_id, payload.widget_type)
    except KeyError as exc:
        raise HTTPException(404, "Dashboard view not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch("/api/dashboard/views/{view_id}/layout/widgets/{widget_id}")
def mutate_dashboard_view_widget(view_id: str, widget_id: str, payload: LayoutMutationRequest,
                                 user: AuthenticatedUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return database.mutate_dashboard_layout(view_id,user.id,widget_id,payload.operation,payload.width,payload.height,payload.direction)
    except KeyError as exc:
        raise HTTPException(404,"Dashboard widget not found") from exc
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
