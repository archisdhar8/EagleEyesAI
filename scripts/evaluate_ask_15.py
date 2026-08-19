from __future__ import annotations

import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import (  # noqa: E402
    ask_orchestration,
    chat,
    database,
    forecasting,
    main,
    portfolio_intelligence,
    portfolio_overview,
    thesis_monitor,
    theses,
)
from backend.analysis import security_research  # noqa: E402
from backend.auth import AuthenticatedUser  # noqa: E402
from backend.main import ChatPageContext, ChatRequest  # noqa: E402
from backend.models import SimulationRunInput  # noqa: E402
from backend.planning import build_guidance  # noqa: E402
from backend.portfolio_diagnostics import build_portfolio_diagnostics  # noqa: E402
from backend.portfolio_eligibility import equity_analysis_holdings  # noqa: E402
from backend.simulation_engine import run_simulation  # noqa: E402


QUESTIONS = [
    "What are the three strongest opportunities in my portfolio today, and what evidence supports each one?",
    "Which holding has the weakest investment thesis, and what should I replace it with?",
    "What has materially changed in my portfolio since my last review?",
    "Which positions are most overvalued relative to their growth and fundamentals?",
    "Where am I taking hidden concentration risk across sectors, themes, and correlated companies?",
    "What would happen to my portfolio if interest rates rose, the economy entered a recession, or AI spending slowed?",
    "Which watchlist stocks now have a stronger risk-adjusted case than my existing holdings?",
    "What upcoming earnings reports, economic events, or company catalysts could materially affect my portfolio?",
    "Which holdings are missing reliable data, and how much should I trust their rankings?",
    "Why did this company’s EagleEyes score change, and which inputs contributed most to the change?",
    "What evidence would invalidate the thesis for each of my largest positions?",
    "How should I rebalance the portfolio while minimizing unnecessary turnover, taxes, and trading costs?",
    "Which companies combine improving fundamentals, reasonable valuation, and positive momentum?",
    "What are the strongest arguments against EagleEyes’ current top recommendation?",
    "If I invested new cash today, where should it go—and why is that better than holding cash?",
]


DIAGNOSTIC_GEMINI_TIMEOUT_SECONDS = 90


def _diagnostic_gemini_request(
    api_key: str,
    model: str,
    contents: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    """Call the configured model with a diagnostic timeout, without retries.

    Production remains unchanged.  This deliberately separates "can Gemini
    answer from this evidence?" from the application's shorter interactive
    deadline, which is evaluated in the saved baseline report.
    """
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": contents,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        },
        timeout=(5, DIAGNOSTIC_GEMINI_TIMEOUT_SECONDS),
    )
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message", "Gemini request failed")
        except ValueError:
            message = response.text[:300] or "Gemini request failed"
        raise RuntimeError(message)
    return response.json()


def _renormalize(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = copy.deepcopy(holdings)
    values = [max(0.0, float(row.get("market_value") or 0)) for row in rows]
    if sum(values) <= 0:
        values = [max(0.0, float(row.get("weight") or 0)) for row in rows]
    total = sum(values)
    for row, value in zip(rows, values):
        row["weight"] = value / total if total else 0.0
    return rows


def _filtered_analysis(raw: dict[str, Any] | None, allowed: set[str]) -> dict[str, Any] | None:
    if not raw:
        return None
    result = copy.deepcopy(raw)
    for alternative in result.get("alternatives") or []:
        allocations = [
            row for row in alternative.get("allocations") or []
            if str(row.get("ticker") or "").upper() in allowed
        ]
        current_total = sum(float(row.get("current_weight") or 0) for row in allocations)
        target_total = sum(float(row.get("target_weight") or 0) for row in allocations)
        for row in allocations:
            current = float(row.get("current_weight") or 0) / current_total if current_total else 0.0
            target = float(row.get("target_weight") or 0) / target_total if target_total else 0.0
            row["current_weight"] = current
            row["target_weight"] = target
            row["delta"] = target - current
        alternative["allocations"] = allocations
    current = result.get("current_portfolio")
    if isinstance(current, dict) and isinstance(current.get("holdings"), list):
        current["holdings"] = [
            row for row in current["holdings"]
            if str(row.get("ticker") or "").upper() in allowed
        ]
    return result


def _build_ephemeral_overview(
    user_id: str,
    portfolio: dict[str, Any],
    source_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    holdings = portfolio["holdings"]
    tickers = [str(row["ticker"]).upper() for row in holdings]
    allowed = set(tickers)
    print(f"Preparing stored evidence for {len(tickers)} eligible positions...", flush=True)
    bundle = database.security_data(tickers, price_limit=1300)
    research = security_research(tickers, price_limit=1300, stored=bundle)
    raw_analysis = database.latest_analysis(user_id, portfolio["id"])
    analysis = _filtered_analysis(raw_analysis, allowed)
    diagnostics = build_portfolio_diagnostics(
        holdings,
        bundle,
        database.fund_reference_data(tickers),
        (analysis or {}).get("implementation_paths") or [],
    )
    workspace = theses.workspace(user_id, holdings, [])
    active_theses = workspace.get("active_theses", [])
    monitors = thesis_monitor.latest_results(user_id, [str(row["id"]) for row in active_theses])
    cached_ask = source_snapshot.get("ask_cache") or {}
    cached_intelligence = cached_ask.get("portfolio_intelligence") or {}
    prediction_markets = list(cached_intelligence.get("prediction_market_exposure") or [])
    events = list(cached_ask.get("events") or [])
    diagnostics["intelligence"] = portfolio_intelligence.build_portfolio_intelligence(
        holdings=holdings,
        security_data=bundle,
        diagnostics=diagnostics,
        theses=active_theses,
        monitor_results=monitors,
        forecasting={"markets": prediction_markets},
        events=events,
        scenario_outcomes=[],
    )
    profile = database.load_profile(user_id) or {}
    policy = database.load_investment_policy(user_id) or {}
    guidance = build_guidance(
        holdings,
        database.list_goals(user_id),
        policy,
        research,
        database.provider_data_status(),
        [],
        database.latest_monitoring_run(),
        profile,
    )
    overview = portfolio_overview.build_portfolio_overview(
        portfolio=portfolio,
        diagnostics=diagnostics,
        research=research,
        theses=active_theses,
        monitors=monitors,
        decisions=workspace.get("recent_decisions", []),
        attention_items=[],
        guidance=guidance,
        previous_nightly=None,
        trigger="LOCAL_ASK_EVALUATION",
    )
    original_changes = [
        row for row in source_snapshot.get("changes") or []
        if not row.get("ticker") or str(row.get("ticker")).upper() in allowed
    ]
    overview["changes"] = original_changes
    overview["history"] = source_snapshot.get("history") or []

    print("Running one local cached scenario for the filtered portfolio...", flush=True)
    scenario_question = QUESTIONS[5]
    scenario_input = SimulationRunInput.model_validate({
        "portfolio_id": portfolio["id"],
        "holdings": holdings,
        "profile": profile,
        "goals": database.list_goals(user_id),
        "scenario": main._simulation_scenario_from_question(scenario_question),
        "paths": 300,
        "seed": 90210,
    })
    try:
        local_simulation = run_simulation(scenario_input, price_limit_per_ticker=1260)
    except Exception as exc:
        print(f"Scenario preparation failed: {type(exc).__name__}: {exc}", flush=True)
        local_simulation = None

    watchlist = list(dict.fromkeys(str(value).upper() for value in profile.get("watchlist", []) if value))[:40]
    watchlist_bundle = database.security_data(watchlist, price_limit=260) if watchlist else {}
    watchlist_research = security_research(watchlist, price_limit=260, stored=watchlist_bundle) if watchlist else []
    overview["ask_cache"] = {
        "portfolio_intelligence": diagnostics["intelligence"],
        "watchlist_research": watchlist_research,
        "latest_simulation": local_simulation,
        "latest_optimizer": analysis,
        "events": events,
        "scenarios": list(cached_ask.get("scenarios") or []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return overview, analysis, {
        "research_rows": len(research),
        "active_theses": len(active_theses),
        "scenario_input": scenario_input.scenario.model_dump(mode="json"),
        "scenario_ready": local_simulation is not None,
    }


def main_run() -> None:
    if not database.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not configured")
    target_email = os.getenv("ASK_EVAL_USER_EMAIL", "").strip()
    if not target_email:
        raise SystemExit("ASK_EVAL_USER_EMAIL is required")
    with database.postgres_connection() as conn:
        user_row = conn.execute(
            "select id, email from auth.users where lower(email)=lower(%s)",
            (target_email,),
        ).fetchone()
    if not user_row:
        raise SystemExit("Target user not found")
    user_id = str(user_row["id"])
    candidates = [row for row in database.list_portfolios(user_id) if len(row.get("holdings") or []) == 61]
    if not candidates:
        raise SystemExit("No 61-row portfolio found")
    source = candidates[0]
    eligible, excluded = equity_analysis_holdings(source["holdings"])
    portfolio = {**source, "name": f"{source['name']} — eligible positions evaluation", "holdings": _renormalize(eligible)}
    source_health = database.latest_portfolio_health(user_id, source["id"])
    source_snapshot = dict((source_health or {}).get("result") or {})
    overview, filtered_analysis, preparation = _build_ephemeral_overview(user_id, portfolio, source_snapshot)

    original_get_portfolio = database.get_portfolio
    original_latest_analysis = database.latest_analysis
    original_latest_health = database.latest_portfolio_health
    original_list_portfolios = database.list_portfolios
    conversations: dict[str, dict[str, Any]] = {}
    messages: dict[str, list[dict[str, Any]]] = {}
    serial = {"conversation": 0, "message": 0}

    def get_portfolio(portfolio_id: str, owner_id: str | None = None) -> dict[str, Any]:
        if str(portfolio_id) == str(portfolio["id"]) and owner_id == user_id:
            return copy.deepcopy(portfolio)
        return original_get_portfolio(portfolio_id, owner_id)

    def latest_analysis(owner_id: str, portfolio_id: str | None = None) -> dict[str, Any] | None:
        if owner_id == user_id and str(portfolio_id) == str(portfolio["id"]):
            return copy.deepcopy(filtered_analysis)
        return original_latest_analysis(owner_id, portfolio_id)

    def latest_health(owner_id: str, portfolio_id: str) -> dict[str, Any] | None:
        if owner_id == user_id and str(portfolio_id) == str(portfolio["id"]):
            return {"id": "local-evaluation", "result": copy.deepcopy(overview)}
        return original_latest_health(owner_id, portfolio_id)

    def create_conversation(owner_id: str, title: str, portfolio_id: str | None = None, workspace: str = "research") -> dict[str, Any]:
        serial["conversation"] += 1
        row = {"id": f"eval-conversation-{serial['conversation']}", "title": title, "portfolio_id": portfolio_id,
               "workspace": workspace, "summary": "", "summary_message_count": 0}
        conversations[row["id"]] = row
        messages[row["id"]] = []
        return copy.deepcopy(row)

    def save_message(owner_id: str, conversation_id: str, role: str, content: str,
                     structured: dict[str, Any] | None = None, model: str | None = None) -> dict[str, Any]:
        serial["message"] += 1
        row = {"id": f"eval-message-{serial['message']}", "role": role, "content": content,
               "structured_content": structured or {}, "model": model}
        messages.setdefault(conversation_id, []).append(row)
        return copy.deepcopy(row)

    database.get_portfolio = get_portfolio
    database.latest_analysis = latest_analysis
    database.latest_portfolio_health = latest_health
    database.list_portfolios = lambda owner_id=None: [copy.deepcopy(portfolio)] if owner_id == user_id else original_list_portfolios(owner_id)
    database.create_conversation = create_conversation
    database.get_conversation = lambda owner_id, cid: copy.deepcopy(conversations[cid])
    database.rename_conversation = lambda owner_id, cid, title: copy.deepcopy({**conversations[cid], "title": title})
    database.conversation_messages = lambda owner_id, cid: copy.deepcopy(messages.get(cid, []))
    database.save_chat_message = save_message
    database.update_conversation_summary = lambda *args, **kwargs: None
    database.link_conversation_artifact = lambda *args, **kwargs: None
    database.save_simulation_run = lambda owner_id, result: str(result.get("id") or "local-evaluation")
    main.record_metric = lambda *args, **kwargs: None

    baseline_path = ROOT / "artifacts" / "ask-15-app-timeout-baseline.json"
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    baseline_by_question = {
        str(row.get("question")): row for row in baseline_payload.get("results") or []
    }
    # Test-only override: preserve the exact production prompt and answer
    # parser, but allow the provider enough time to prove whether it can
    # synthesize the supplied evidence. This does not alter application code.
    chat._gemini_request = _diagnostic_gemini_request
    # The product defaults to the deterministic renderer so Gemini is not on
    # the critical path. The evaluation explicitly enables the optional
    # narrator to exercise success/timeout behavior without changing prod.
    os.environ["ASK_GEMINI_ENRICHMENT"] = "1"

    largest = max(portfolio["holdings"], key=lambda row: float(row.get("weight") or 0))["ticker"]
    user = AuthenticatedUser(id=user_id, email=str(user_row["email"]))
    results = []
    for index, question in enumerate(QUESTIONS, 1):
        page_ticker = largest if index == 10 else None
        context = ChatPageContext(
            portfolio_id=str(portfolio["id"]),
            ticker=page_ticker,
            route="/ask",
            workspace="portfolio",
            enabled_context=["evidence", "thesis", "portfolio"],
        )
        request = ChatRequest(question=question, workspace="portfolio", page_context=context)
        planned = ask_orchestration.build_plan(question, "portfolio", context.model_dump(exclude_none=True))
        print(f"[{index:02d}/15] {planned.intent}: calling local API + Gemini...", flush=True)
        started = time.monotonic()
        try:
            response = main.chat_message(request, user)
            message = response["message"]
            structured = message.get("structured_content") or {}
            analysis_context = structured.get("analysis_context") or {}
            analysis_result = structured.get("analysis_result") or {}
            verification = analysis_result.get("verification") or {}
            execution = structured.get("execution_plan") or {}
            results.append({
                "number": index,
                "question": question,
                "page_ticker": page_ticker,
                "status": "answered",
                "intent": analysis_context.get("intent") or planned.intent,
                "model": message.get("model"),
                "answer": message.get("content"),
                "answer_complete": analysis_context.get("answer_complete"),
                "tool_names": analysis_context.get("tool_names") or [],
                "evidence_coverage": analysis_context.get("evidence_coverage"),
                "verification_status": verification.get("status"),
                "warnings": verification.get("warnings") or [],
                "failures": verification.get("failures") or [],
                "final_answer_source": "gemini" if not str(message.get("model") or "").startswith("deterministic") else "deterministic",
                "timings": execution.get("timings") or {},
                "wall_seconds": round(time.monotonic() - started, 3),
                "app_baseline": baseline_by_question.get(question),
            })
        except Exception as exc:
            results.append({
                "number": index, "question": question, "page_ticker": page_ticker,
                "status": "error", "intent": planned.intent, "model": None,
                "answer": f"{type(exc).__name__}: {exc}", "answer_complete": False,
                "tool_names": list(planned.tools), "evidence_coverage": 0,
                "verification_status": "ERROR", "warnings": [], "failures": [f"{type(exc).__name__}: {exc}"],
                "final_answer_source": "error",
                "timings": {}, "wall_seconds": round(time.monotonic() - started, 3),
                "app_baseline": baseline_by_question.get(question),
            })
        print(f"         {results[-1]['status']} via {results[-1]['model']} in {results[-1]['wall_seconds']}s", flush=True)

    for row in results:
        if row["status"] != "answered" or not row["answer_complete"]:
            row["quality_verdict"] = "FAIL"
        elif row.get("verification_status") == "FAILED":
            row["quality_verdict"] = "SAFE_BLOCK"
        elif row.get("verification_status") == "PARTIAL":
            row["quality_verdict"] = "LIMITED_DISCLOSED"
        elif row.get("final_answer_source") == "deterministic":
            row["quality_verdict"] = "PASS_WITH_FALLBACK"
        else:
            row["quality_verdict"] = "PASS"

    output_dir = ROOT / "artifacts"
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / "ask-15-local-gemini-evaluation.json"
    md_path = output_dir / "ask-15-local-gemini-evaluation.md"
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_portfolio_id": source["id"],
        "source_portfolio_name": source["name"],
        "source_rows": len(source["holdings"]),
        "eligible_rows": len(portfolio["holdings"]),
        "excluded": excluded,
        "largest_context_ticker_for_question_10": largest,
        "gemini_model": main.os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        "diagnostic_gemini_timeout_seconds": DIAGNOSTIC_GEMINI_TIMEOUT_SECONDS,
        "preparation": preparation,
        "results": results,
    }
    json_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    excluded_summary = ", ".join(
        f"{row['ticker']} ({row['reason']})" for row in excluded
    )
    lines = [
        "# Ask EagleEyes: 15-question local Gemini evaluation",
        "",
        f"Generated: {metadata['generated_at']}",
        f"Portfolio: `{source['name']}` (`{source['id']}`)",
        f"Universe: {len(source['holdings'])} saved rows → {len(portfolio['holdings'])} eligible stock/ETF positions",
        f"Excluded for this in-memory test: {excluded_summary}",
        f"Configured Gemini model: `{metadata['gemini_model']}`",
        f"Question 10 page context: `{largest}`",
        f"Scenario parser output: `{json.dumps(preparation['scenario_input'], sort_keys=True)}`",
        "",
        "This test calls the local FastAPI chat handler and the configured Gemini API. It does not save a portfolio, conversation, message, simulation, or metric.",
        f"Gemini diagnostic read timeout: {DIAGNOSTIC_GEMINI_TIMEOUT_SECONDS}s. The saved app baseline used the production timeout and is shown beside each answer.",
        "",
        "## Summary",
        "",
        "| # | Intent | Verification | Quality | Gemini diagnostic | Source | Complete | Tools | Coverage | Seconds |",
        "|---:|---|---|---|---|---|---|---|---|---:|",
    ]
    for row in results:
        lines.append(
            f"| {row['number']} | {row['intent']} | "
            f"{row.get('verification_status')} | {row.get('quality_verdict')} | {row['model'] or 'error'} | {row.get('final_answer_source')} | {row['answer_complete']} | "
            f"{', '.join(row['tool_names']) or 'none'} | {row['evidence_coverage']} | {row['wall_seconds']} |"
        )
    for row in results:
        lines.extend([
            "",
            f"## {row['number']}. {row['question']}",
            "",
            f"- Intent: `{row['intent']}`",
            f"- Model: `{row['model'] or 'error'}`",
            f"- Tools: `{', '.join(row['tool_names']) or 'none'}`",
            f"- Complete: `{row['answer_complete']}`",
            f"- Verification: `{row.get('verification_status')}`",
            f"- Quality verdict: `{row.get('quality_verdict')}`",
            f"- Final answer source: `{row.get('final_answer_source')}`",
            f"- Warnings: `{'; '.join(row.get('warnings') or []) or 'none'}`",
            f"- Failures: `{'; '.join(row.get('failures') or []) or 'none'}`",
            f"- Wall time: `{row['wall_seconds']}s`",
        ])
        if row.get("page_ticker"):
            lines.append(f"- Page-context ticker: `{row['page_ticker']}`")
        baseline = row.get("app_baseline") or {}
        lines.extend([
            "",
            "### App result at its production timeout",
            "",
            baseline.get("answer") or "No saved production-timeout baseline was available.",
            "",
            f"### Gemini answer with the {DIAGNOSTIC_GEMINI_TIMEOUT_SECONDS}-second local diagnostic timeout",
            "",
            row["answer"] or "No answer returned.",
        ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"REPORT_MD={md_path}", flush=True)
    print(f"REPORT_JSON={json_path}", flush=True)


if __name__ == "__main__":
    main_run()
