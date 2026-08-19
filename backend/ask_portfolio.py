from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import database, theses
from .analysis import security_research


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _selected_portfolio(user_id: str, portfolio_id: str | None) -> dict[str, Any]:
    if not portfolio_id:
        raise ValueError("Select a portfolio before asking a portfolio-specific question.")
    return database.get_portfolio(portfolio_id, user_id)


def _overview(user_id: str, portfolio_id: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        row = database.latest_portfolio_health(user_id, portfolio_id)
    except Exception as exc:
        return None, f"Portfolio health storage is not ready ({type(exc).__name__}). Apply the portfolio-health migration and backfill a snapshot."
    return (dict(row.get("result") or {}) if row else None), None


def _briefing(user_id: str) -> dict[str, Any]:
    try:
        return database.latest_briefing_snapshot(user_id) or {}
    except Exception:
        return {}


def _evidence(tool: str, portfolio: dict[str, Any], summary: dict[str, Any], as_of: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    status = "complete" if summary.get("status") != "unavailable" else "unavailable"
    result = {"tool_name": tool, "status": status, "title": summary.get("title") or tool.replace("_", " ").title(), "summary": summary}
    grounded = [] if status == "unavailable" else [{
        "label": summary.get("title") or result["title"], "as_of": as_of or portfolio.get("updated_at"),
        "url": None, "data": summary, "claim_type": "MODEL_OUTPUT",
    }]
    return [result], grounded


def _snapshot_required(tool: str, portfolio: dict[str, Any], overview: dict[str, Any] | None,
                       storage_error: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    if overview:
        return None
    message = storage_error or "No cached portfolio-health snapshot exists yet. A background portfolio refresh is required."
    return _evidence(tool, portfolio, {"status": "unavailable", "title": "Portfolio intelligence is preparing", "message": message}, portfolio.get("updated_at"))


def _factor_rank(holdings: list[dict[str, Any]], keys: tuple[str, ...], reverse: bool = True) -> list[dict[str, Any]]:
    eligible = [row for row in holdings if all(row.get(key) is not None for key in keys)]
    return sorted(eligible, key=lambda row: sum(_number(row.get(key)) for key in keys) / len(keys), reverse=reverse)


def _stored_watchlist_research(user_id: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    tickers = list(dict.fromkeys(str(value).upper() for value in profile.get("watchlist", []) if value))[:40]
    if not tickers:
        return []
    stored = database.security_data(tickers, price_limit=260)
    return security_research(tickers, price_limit=260, stored=stored)


def run(tool: str, user_id: str, portfolio_id: str | None, question: str,
        tickers: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        portfolio = _selected_portfolio(user_id, portfolio_id)
    except (KeyError, ValueError) as exc:
        empty = {"status": "unavailable", "title": "Portfolio context is required", "message": str(exc)}
        return _evidence(tool, {"updated_at": None}, empty, None)
    overview, storage_error = _overview(user_id, str(portfolio["id"]))
    required = _snapshot_required(tool, portfolio, overview, storage_error)
    if required:
        return required
    assert overview is not None
    holdings = list(overview.get("holdings") or [])
    holding_tickers = {str(row.get("ticker") or "").upper() for row in holdings}
    as_of = overview.get("as_of") or portfolio.get("updated_at")
    health = overview.get("health") or {}
    profile = database.load_profile(user_id) or {}
    ask_cache = overview.get("ask_cache") or {}

    if tool == "portfolio_overview":
        candidates = [row for row in _factor_rank(holdings, ("health_score",)) if row.get("ticker") != "CASH"][:3]
        summary = {"title": "Strongest portfolio opportunities", "health": health, "candidates": candidates,
                   "method": "Highest cached holding-health scores with factor, risk, coverage, and action context; this is a research ranking, not a return forecast."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "portfolio_change":
        summary = {"title": "Material portfolio changes", "health": health, "changes": overview.get("changes") or [],
                   "history": overview.get("history") or [], "warnings": overview.get("warnings") or []}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "valuation_ranking":
        ranked = sorted([row for row in holdings if row.get("valuation_score") is not None],
                        key=lambda row: (_number(row.get("valuation_score")), -_number(row.get("fundamental_score"))))
        summary = {"title": "Valuation relative to stored fundamentals", "positions": ranked[:10],
                   "method": "Lowest valuation score first, with growth/fundamental support shown separately. Missing valuation is excluded and disclosed."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "data_quality":
        confidence_order = {"Low": 0, "Medium": 1, "High": 2}
        ranked = sorted(holdings, key=lambda row: (confidence_order.get(str(row.get("data_confidence")), 0), _number(row.get("health_score"))))
        summary = {"title": "Portfolio data-quality review", "positions": ranked,
                   "coverage": health.get("coverage"), "warnings": overview.get("warnings") or [],
                   "method": "Low-confidence and incomplete factor records appear first; missing data is never treated as neutral."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "multifactor_screen":
        ranked = _factor_rank(holdings, ("fundamental_score", "valuation_score", "momentum_score"))
        summary = {"title": "Fundamentals, valuation, and momentum screen", "positions": ranked[:15],
                   "method": "Equal-weighted ordering of the three cached component scores among holdings with all three components."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "score_attribution":
        selected = None
        if tickers:
            selected = next((row for row in holdings if row.get("ticker") == tickers[0]), None)
        if not selected:
            return _evidence(tool, portfolio, {"status": "unavailable", "title": "Company context is required",
                "message": "Name a holding or open its research page before asking why its score changed."}, as_of)
        summary = {"title": f"{selected['ticker']} score attribution", "holding": selected,
                   "component_changes": selected.get("component_changes") or {},
                   "method": "The cached holding-health calculation combines fundamentals, valuation, momentum, modeled risk, and data confidence. Component changes and the total change compare the current record with the previous nightly snapshot."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool in {"portfolio_intelligence", "recommendation_countercase"}:
        risk_ranked = sorted(holdings, key=lambda row: _number(row.get("risk_contribution")), reverse=True)
        concentration = [row for row in overview.get("actions") or [] if "concentration" in str(row.get("reason", "")).lower()]
        intelligence = ask_cache.get("portfolio_intelligence") or {}
        summary = {"title": "Hidden portfolio risk" if tool == "portfolio_intelligence" else "Countercase to the leading portfolio opportunity",
                   "health": health, "highest_risk_holdings": risk_ranked[:10], "concentration_actions": concentration,
                   "concentration": intelligence.get("concentration") or {},
                   "correlation": intelligence.get("correlation") or {},
                   "economic_dependencies": intelligence.get("economic_dependencies") or [],
                   "coverage": intelligence.get("coverage") or {},
                   "warnings": overview.get("warnings") or [], "top_candidate": _factor_rank(holdings, ("health_score",))[:1],
                   "method": "Cached position, sector and industry concentration; return-correlation clusters; mapped economic dependencies; modeled risk contribution; and evidence warnings."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "portfolio_events":
        summary = {"title": "Upcoming portfolio events", "events": list(ask_cache.get("events") or [])[:20],
                   "method": "Stored portfolio-relevant earnings, economic, regulatory, and company events."}
        return _evidence(tool, portfolio, summary, ask_cache.get("generated_at") or as_of)

    if tool in {"watchlist_comparison", "thesis_replacement", "cash_allocation"}:
        watchlist = list(ask_cache.get("watchlist_research") or [])
        watchlist_rows = sorted(watchlist, key=lambda row: (
            _number(row.get("fundamental_score")) + _number(row.get("valuation_score"))
            + _number(row.get("technical_score")) + _number(row.get("confidence"))
        ), reverse=True)
        weak = sorted(holdings, key=lambda row: _number(row.get("health_score")))[:5]
        active_theses = [row for row in theses.list_theses(user_id)
                         if str(row.get("ticker") or "").upper() in holding_tickers]
        if tool == "thesis_replacement" and not active_theses:
            summary = {"status": "unavailable", "title": "No saved investment theses",
                       "message": "No saved thesis exists for this portfolio, so EagleEyes cannot identify a weakest thesis or claim that a replacement invalidates it.",
                       "watchlist_candidates": watchlist_rows[:5], "weakest_evidence_holdings": weak}
        else:
            summary = {"title": "Watchlist and portfolio comparison" if tool == "watchlist_comparison" else "New-cash research queue" if tool == "cash_allocation" else "Thesis and replacement review",
                       "watchlist_candidates": watchlist_rows[:10], "weakest_holdings": weak,
                       "saved_theses": active_theses[:30],
                       "method": "Stored component evidence and confidence only. Portfolio fit, taxes, overlap, and user constraints can override the ordering."}
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "thesis_monitor":
        active_theses = [row for row in theses.list_theses(user_id)
                         if str(row.get("ticker") or "").upper() in holding_tickers]
        summary = {"title": "Thesis invalidation review", "saved_theses": active_theses[:30],
                   "largest_positions": sorted(holdings, key=lambda row: _number(row.get("weight")), reverse=True)[:10]}
        if not active_theses:
            summary.update({"status": "unavailable", "message": "No saved thesis exists. EagleEyes can show evidence risks, but it cannot invent the user's thesis or its invalidation conditions."})
        return _evidence(tool, portfolio, summary, as_of)

    if tool == "portfolio_scenario":
        simulation = ask_cache.get("latest_simulation")
        summary = {"title": "Cached portfolio scenario matrix", "latest_simulation": simulation,
                   "market_scenarios": ask_cache.get("scenarios") or [],
                   "requested_conditions": question,
                   "method": "Latest cached portfolio simulation and stored scenario probabilities; no simulation or provider refresh runs inside chat."}
        if not simulation:
            summary.update({"status": "unavailable", "message": "No cached portfolio simulation exists yet. Queue the canonical scenario refresh before relying on this comparison."})
        return _evidence(tool, portfolio, summary, as_of)

    return _evidence(tool, portfolio, {"status": "unavailable", "title": tool.replace("_", " ").title(), "message": "No cached portfolio aggregator is registered for this question."}, as_of)


def _rows(items: list[dict[str, Any]], formatter, limit: int = 5) -> str:
    return "\n".join(f"{index}. {formatter(row)}" for index, row in enumerate(items[:limit], 1))


def compose(intent: str, tool_results: list[dict[str, Any]]) -> str | None:
    result = next((row for row in tool_results if row.get("status") == "complete"), None)
    summary = (result or {}).get("summary") or {}
    unavailable = next((row for row in tool_results if row.get("status") == "unavailable"), None)
    if not result:
        message = ((unavailable or {}).get("summary") or {}).get("message")
        return f"{message}\n\n**What to verify:** confirm the selected portfolio and complete the missing saved-data prerequisite." if message else None

    if intent == "OPPORTUNITY_RANKING":
        rows = summary.get("candidates") or []
        body = _rows(rows, lambda row: f"**{row.get('ticker')}** — health **{_number(row.get('health_score')):.0f}/100**; fundamentals {_number(row.get('fundamental_score')):.0f}, valuation {_number(row.get('valuation_score')):.0f}, momentum {_number(row.get('momentum_score')):.0f}; evidence confidence **{row.get('data_confidence')}** [S1]", 3)
        return f"The three strongest current research opportunities inside the selected portfolio are:\n\n{body}\n\n{summary.get('method')}\n\n**What to verify:** review each position's valuation inputs, thesis, size, and active actions before recording a decision."
    if intent == "PORTFOLIO_CHANGE":
        changes = summary.get("changes") or []
        if not changes:
            return "No material change is recorded relative to the previous nightly portfolio snapshot [S1]. This can also mean the baseline has not been established yet.\n\n**What to verify:** confirm that the nightly snapshot and latest evidence refresh completed for the selected portfolio."
        body = _rows(changes, lambda row: f"**{row.get('title')}**" + (f" ({_number(row.get('delta')):+.1f})" if row.get("delta") is not None else ""), 10)
        return f"These material changes are recorded for the selected portfolio:\n\n{body}\n\n**What to verify:** open the change timeline and inspect the evidence date and trigger for each item."
    if intent == "VALUATION_RANKING":
        body = _rows(summary.get("positions") or [], lambda row: f"**{row.get('ticker')}** — valuation {_number(row.get('valuation_score')):.0f}/100, fundamentals {_number(row.get('fundamental_score')):.0f}/100, weight {_number(row.get('weight')):.1%} [S1]", 10)
        return f"These holdings have the weakest stored valuation support relative to their fundamental score:\n\n{body}\n\nA low valuation score is a review signal, not proof that a security is overvalued.\n\n**What to verify:** inspect the underlying multiples, growth period, margins, and evidence freshness."
    if intent == "DATA_QUALITY":
        rows = [row for row in summary.get("positions") or [] if row.get("data_confidence") != "High"]
        body = _rows(rows, lambda row: f"**{row.get('ticker')}** — {row.get('data_confidence')} confidence; fundamentals {row.get('fundamental_score')}, valuation {row.get('valuation_score')}, momentum {row.get('momentum_score')} [S1]", 15)
        return f"The holdings below have the least reliable current ranking inputs:\n\n{body or 'No lower-confidence holdings are recorded.'}\n\nMissing coverage is penalized rather than treated as neutral.\n\n**What to verify:** refresh the largest low-confidence holdings before relying on their relative order."
    if intent == "MULTIFACTOR_SCREEN":
        body = _rows(summary.get("positions") or [], lambda row: f"**{row.get('ticker')}** — fundamentals {_number(row.get('fundamental_score')):.0f}, valuation {_number(row.get('valuation_score')):.0f}, momentum {_number(row.get('momentum_score')):.0f}, confidence {row.get('data_confidence')} [S1]", 10)
        return f"These holdings currently combine the strongest stored fundamentals, valuation, and momentum scores:\n\n{body}\n\n**What to verify:** inspect factor definitions, dates, portfolio overlap, and whether the evidence survives the next earnings update."
    if intent == "SCORE_ATTRIBUTION":
        row = summary.get("holding") or {}
        return f"**{row.get('ticker')}** currently has a holding-health score of **{_number(row.get('health_score')):.0f}/100**, a change of **{_number(row.get('change')):+.1f}** from the previous nightly snapshot [S1]. Its inputs are fundamentals **{_number(row.get('fundamental_score')):.0f}**, valuation **{_number(row.get('valuation_score')):.0f}**, momentum **{_number(row.get('momentum_score')):.0f}**, modeled risk contribution **{_number(row.get('risk_contribution')):.1%}**, and **{row.get('data_confidence')}** evidence confidence [S1].\n\n**What to verify:** compare the current and previous snapshot evidence dates before attributing the move to a business change."
    if intent == "PORTFOLIO_EVENTS":
        body = _rows(summary.get("events") or [], lambda row: f"**{row.get('title') or row.get('name') or row.get('event')}** — {row.get('date') or row.get('starts_at') or row.get('occurred_at') or 'date unavailable'}; affected: {', '.join(row.get('affected_holdings') or row.get('tickers') or []) or 'not mapped'} [S1]", 12)
        return f"The stored event calendar contains these upcoming portfolio-relevant events:\n\n{body or 'No covered upcoming event is stored.'}\n\n**What to verify:** confirm event dates and coverage before assuming silence means no catalyst exists."
    if intent in {"HIDDEN_RISK", "RECOMMENDATION_COUNTERCASE"}:
        risk = summary.get("highest_risk_holdings") or []
        body = _rows(risk, lambda row: f"**{row.get('ticker')}** — modeled risk contribution {_number(row.get('risk_contribution')):.1%}, weight {_number(row.get('weight')):.1%}, health {_number(row.get('health_score')):.0f}/100 [S1]", 8)
        prefix = "The strongest arguments against the current leading opportunity are its weakest factor, modeled risk contribution, concentration role, and any coverage warning." if intent == "RECOMMENDATION_COUNTERCASE" else "The largest cached hidden-risk contributors are:"
        return f"{prefix}\n\n{body}\n\nThis cached view does not invent sector or correlation evidence that is absent from the snapshot.\n\n**What to verify:** inspect sector, theme, correlation, ETF look-through, and covariance diagnostics before changing exposure."
    if intent in {"WATCHLIST_COMPARISON", "THESIS_REPLACEMENT", "CASH_ALLOCATION"}:
        rows = summary.get("watchlist_candidates") or []
        body = _rows(rows, lambda row: f"**{row.get('ticker')}** — fundamentals {_number(row.get('fundamental_score')):.0f}, valuation {_number(row.get('valuation_score')):.0f}, momentum {_number(row.get('technical_score')):.0f}, confidence {_number(row.get('confidence')):.0f}/100 [S1]", 8)
        label = "The strongest stored watchlist research candidates are" if intent != "CASH_ALLOCATION" else "For new cash, these are the first research candidates to compare with holding cash"
        return f"{label}:\n\n{body or 'No eligible watchlist candidate has sufficient stored evidence.'}\n\nThis is a research queue, not a buy instruction. Portfolio overlap, valuation, risk budget, and user constraints can override the order. Rebalancing remains explicitly tax-blind without tax-lot data.\n\n**What to verify:** compare each candidate with the weakest existing holding and with the role of cash before recording an ADD or HOLD decision."
    if intent == "THESIS_INVALIDATION":
        theses_rows = summary.get("saved_theses") or []
        return f"There are **{len(theses_rows)} saved theses** available for invalidation review [S1]. " + ("Open each largest-position thesis to review its explicit assumptions and breakers." if theses_rows else "EagleEyes cannot invent invalidation conditions for positions without a user-saved thesis.") + "\n\n**What to verify:** save the thesis assumptions and breakers you actually intend to monitor."
    if intent == "MULTI_SCENARIO":
        simulation = summary.get("latest_simulation") or {}
        return f"The latest cached portfolio simulation is available under model **{simulation.get('model_version') or 'unknown'}** [S1]. The requested rates, recession, and AI-spending conditions must be compared as separate named cases; no live simulation was run inside chat.\n\n**What to verify:** open the cached scenario run and confirm each scenario's conditioning, date, paths, and assumptions."
    return None
