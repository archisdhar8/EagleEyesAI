from __future__ import annotations

import json
import math
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from . import database, evidence, thesis_monitor, theses

HORIZON_DAYS = {"30D": 30, "90D": 90, "6M": 183, "1Y": 365}


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime): return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")); return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    try:
        result = float(value); return result if math.isfinite(result) else None
    except (TypeError, ValueError): return None


def _json(value: Any, postgres: bool) -> Any:
    return database._jsonb(value) if postgres else json.dumps(value, default=str)


def _forecast_snapshot(user_id: str, decision_date: datetime, ticker: str) -> list[dict[str, Any]]:
    rows = []
    for item in database.list_user_forecasts(user_id):
        if _utc(item["observed_at"]) > decision_date: continue
        text = f"{item.get('event_key','')} {item.get('title','')} {item.get('reasoning','')}".upper()
        if ticker not in text and len(rows) >= 10: continue
        rows.append({key: item.get(key) for key in ("id", "event_key", "provider", "external_market_id", "title", "probability", "reasoning", "market_probability_at_entry", "model_probability_at_entry", "forecast_horizon", "observed_at")})
    return rows[:20]


def _market_snapshot(ticker: str, decision_date: datetime) -> list[dict[str, Any]]:
    try:
        bundle = evidence.load_history_bundle(ticker, decision_date - timedelta(days=365), decision_date)
        observations = evidence.observations_from_bundle(ticker, bundle, decision_date)
        return [{"metric": item.metric, "title": item.label, "probability": item.value, "provider": item.provider,
                 "as_of": item.effective_date.isoformat() if item.effective_date else None, "source": item.source_reference,
                 "quality": item.evidence_quality, "methodology": item.methodology}
                for item in observations if item.evidence_type == "PREDICTION_MARKET"][:20]
    except Exception:
        return []


def _portfolio_context(user_id: str, ticker: str, decision_date: datetime, supplied: dict[str, Any]) -> dict[str, Any]:
    if abs((datetime.now(timezone.utc) - decision_date).total_seconds()) > 86400:
        return {"status": "UNAVAILABLE", "reason": "A historical portfolio snapshot was not supplied for this backdated decision.", "supplied": supplied}
    portfolios = database.list_portfolios(user_id); portfolio = portfolios[0] if portfolios else None
    holdings = (portfolio or {}).get("holdings", [])
    values = {str(row.get("ticker") or "").upper(): _number(row.get("market_value")) or _number(row.get("weight")) or 0 for row in holdings}
    total = sum(values.values()); weight = values.get(ticker, 0) / total if total else None
    return {"status": "AVAILABLE" if portfolio else "UNAVAILABLE", "portfolio_id": (portfolio or {}).get("id"),
            "portfolio_name": (portfolio or {}).get("name"), "holding": next((row for row in holdings if str(row.get("ticker") or "").upper() == ticker), None),
            "normalized_weight": weight, "holding_count": len(holdings), "as_of_method": "saved portfolio at explicit decision time", "supplied": supplied}


def build_snapshot(user_id: str, decision_id: str, decision: dict[str, Any], thesis_snapshot: dict[str, Any] | None,
                   evidence_boundary: dict[str, Any] | None) -> dict[str, Any]:
    decision_date = _utc(decision["decision_date"]); ticker = str(decision["ticker"]).upper()
    source = decision.get("source_context") or {}
    return {"version": "decision-context-v1", "decision_id": decision_id, "ticker": ticker, "decision_type": decision["decision_type"],
            "decision_date": decision_date.isoformat(), "price": {"value": decision.get("price_at_decision"), "as_of": decision.get("price_as_of"), "provider": decision.get("price_source")},
            "thesis_version": decision.get("thesis_version"), "thesis": thesis_snapshot,
            "expected_outcome": source.get("expected_outcome") or "", "review_horizon_days": source.get("review_horizon_days"),
            "comparison_benchmark": source.get("comparison_benchmark") or "SPY", "user_confidence": decision.get("user_confidence"),
            "investment_horizon": decision.get("investment_horizon"), "user_notes": decision.get("notes") or "",
            "portfolio": _portfolio_context(user_id, ticker, decision_date, decision.get("portfolio_context") or {}),
            "forecasts": _forecast_snapshot(user_id, decision_date, ticker), "prediction_markets": _market_snapshot(ticker, decision_date),
            "evidence_boundary": evidence_boundary or {"id": None, "as_of": decision_date.isoformat(), "status": "UNAVAILABLE"},
            "missing": [label for label, value in (("price at decision", decision.get("price_at_decision")), ("linked thesis", thesis_snapshot)) if value is None],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "methodology": "Bounded immutable decision context; point-in-time values only. Current values are never substituted for missing historical data."}


def insert_snapshot(conn: Any, user_id: str, decision_id: str, ticker: str, decision_date: Any, snapshot: dict[str, Any], postgres: bool) -> str:
    snapshot_id, now = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(); p = "%s" if postgres else "?"; prefix = "public." if postgres else ""
    column = "snapshot" if postgres else "snapshot_json"
    conn.execute(f"INSERT INTO {prefix}decision_context_snapshots(id,decision_id,user_id,ticker,decision_date,{column},methodology_version,captured_at) VALUES ({','.join([p]*8)})",
                 (snapshot_id, decision_id, user_id, ticker, decision_date, _json(snapshot, postgres), "decision-context-v1", now))
    return snapshot_id


def get_snapshot(user_id: str, decision_id: str) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL); p, prefix = ("%s", "public.") if postgres else ("?", ""); column = "snapshot" if postgres else "snapshot_json"
    connection = database.postgres_connection if postgres else database.sqlite_connection
    with connection() as conn:
        row = conn.execute(f"SELECT id,decision_id,ticker,decision_date,{column},methodology_version,captured_at FROM {prefix}decision_context_snapshots WHERE user_id={p} AND decision_id={p}", (user_id, decision_id)).fetchone()
    if not row: raise KeyError(decision_id)
    value = dict(row); raw = value.pop(column); value["snapshot"] = raw if isinstance(raw, dict) else json.loads(raw); return value


def snapshot_decision_ids(user_id: str) -> set[str]:
    postgres = bool(database.DATABASE_URL); p, prefix = ("%s", "public.") if postgres else ("?", "")
    connection = database.postgres_connection if postgres else database.sqlite_connection
    with connection() as conn:
        rows = conn.execute(f"SELECT decision_id FROM {prefix}decision_context_snapshots WHERE user_id={p}", (user_id,)).fetchall()
    return {str(row["decision_id"]) for row in rows}


def _price_outcome(ticker: str, benchmark: str, start: datetime, end: datetime) -> dict[str, Any]:
    rows = database.security_data([ticker, benchmark], price_limit=2600).get("prices", [])
    def point(symbol: str, at: datetime) -> dict[str, Any] | None:
        eligible = [row for row in rows if row.get("ticker") == symbol and _utc(row["date"]) <= at]
        return max(eligible, key=lambda row:_utc(row["date"])) if eligible else None
    asset_start, asset_end, bench_start, bench_end = point(ticker, start), point(ticker, end), point(benchmark, start), point(benchmark, end)
    def change(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float | None:
        av, bv = _number((a or {}).get("close")), _number((b or {}).get("close")); return None if av in (None, 0) or bv is None else bv / av - 1
    asset_return, benchmark_return = change(asset_start, asset_end), change(bench_start, bench_end)
    return {"security": ticker, "security_return": asset_return, "benchmark": benchmark, "benchmark_return": benchmark_return,
            "relative_return": None if asset_return is None or benchmark_return is None else asset_return - benchmark_return,
            "start": asset_start, "end": asset_end, "benchmark_start": bench_start, "benchmark_end": bench_end,
            "status": "AVAILABLE" if asset_return is not None else "UNAVAILABLE", "methodology": "Stored close at or before each boundary; not realized account P&L and not silently mixed with account performance."}


def _outcomes(snapshot: dict[str, Any], changes: list[dict[str, Any]], reviews: list[dict[str, Any]], end: datetime) -> dict[str, Any]:
    thesis = snapshot.get("thesis") or {}; latest_review = next((row for row in reviews if _utc(row["reviewed_at"]) <= end), None)
    monitor = (latest_review or {}).get("monitoring_result") or {}; by_metric = {row.get("metric"): row for row in changes}; by_description = {str(row.get("description")): row for row in monitor.get("assumption_results", [])}
    assumptions = []
    for item in thesis.get("assumptions", []):
        change = by_metric.get(item.get("metric")); current = _number((change or {}).get("current_value")); condition = thesis_monitor.evaluate_condition(current, item.get("operator"), _number(item.get("target_value")))
        monitored = by_description.get(str(item.get("description")))
        if condition is True: status = "CONFIRMED"
        elif condition is False: status = "INVALIDATED" if item.get("importance") in {"HIGH", "CRITICAL"} else "NOT_CONFIRMED"
        elif monitored and monitored.get("state") == "SUPPORTS": status = "CONFIRMED"
        elif monitored and monitored.get("state") == "WEAKENS": status = "PARTIALLY_CONFIRMED"
        elif monitored and monitored.get("state") == "CONTRADICTS": status = "INVALIDATED"
        else: status = "INSUFFICIENT_EVIDENCE"
        assumptions.append({"description": item.get("description"), "category": item.get("category"), "importance": item.get("importance"), "status": status,
                            "observed": current, "rule": f"{item.get('metric')} {item.get('operator')} {item.get('target_value')}" if item.get("metric") else None,
                            "evidence": change, "methodology": "deterministic threshold" if condition is not None else "stored thesis review relationship"})
    factor_results = {kind: [] for kind in ("risks", "catalysts", "breakers")}; monitor_keys = {"RISK": "risk_results", "CATALYST": "catalyst_results", "BREAKER": "thesis_breaker_results"}
    maps = {"RISK": {"DORMANT":"DID_NOT_MATERIALIZE","INCREASING":"INCREASED","MATERIALIZED":"MATERIALIZED","DECREASING":"RESOLVED"},
            "CATALYST": {"REALIZED":"REALIZED","DEVELOPING":"PARTIALLY_REALIZED","FAILED":"FAILED","DELAYED":"DELAYED"},
            "BREAKER": {"TRIGGERED":"TRIGGERED","WARNING":"WARNING","NOT_TRIGGERED":"NOT_TRIGGERED"}}
    target_key = {"RISK":"risks", "CATALYST":"catalysts", "BREAKER":"breakers"}
    for factor in thesis.get("factors", []):
        kind = factor.get("factor_type"); result = next((row for row in monitor.get(monitor_keys.get(kind, ""), []) if row.get("description") == factor.get("description")), None)
        factor_results[target_key[kind]].append({"description": factor.get("description"), "status": maps[kind].get((result or {}).get("state"), "INSUFFICIENT_EVIDENCE"), "evidence": (result or {}).get("evidence", [])})
    return {"assumptions": assumptions, **factor_results}


def build_retrospective(user_id: str, decision_id: str, horizon_key: str = "90D", custom_end: datetime | None = None) -> dict[str, Any]:
    decision = next((row for row in theses.list_decisions(user_id) if row["id"] == decision_id), None)
    if not decision: raise KeyError(decision_id)
    wrapped = get_snapshot(user_id, decision_id); snapshot = wrapped["snapshot"]; start = _utc(decision["decision_date"])
    days = HORIZON_DAYS.get(horizon_key) or snapshot.get("review_horizon_days") or 90
    thesis_end = (snapshot.get("thesis") or {}).get("horizon_end_date")
    if horizon_key == "THESIS" and thesis_end:
        requested_end = _utc(thesis_end)
    else:
        requested_end = _utc(custom_end) if custom_end else start + timedelta(days=int(days))
    if horizon_key == "CUSTOM" and custom_end is None:
        raise ValueError("custom_end is required for a custom review window")
    if requested_end <= start:
        raise ValueError("The retrospective end must be after the original decision")
    end = min(requested_end, datetime.now(timezone.utc))
    change_set = evidence.get_changes(user_id, decision["ticker"], from_date=start, current_as_of=end, include_low=True)
    changes = [row.model_dump(mode="json") for row in change_set.changes]
    reviews = thesis_monitor.review_history(user_id, decision["thesis_id"]) if decision.get("thesis_id") else []
    reviews = sorted(reviews, key=lambda row: row["reviewed_at"], reverse=True)
    outcomes = _outcomes(snapshot, changes, reviews, end)
    market = _price_outcome(decision["ticker"], snapshot.get("comparison_benchmark") or "SPY", start, end)
    later_decisions = [row for row in theses.list_decisions(user_id, decision["ticker"]) if start < _utc(row["decision_date"]) <= end]
    timeline = ([{"type":"DECISION","at":decision["decision_date"],"title":f"{decision['decision_type']} recorded","reference_id":decision_id}]
                + [{"type":"EVIDENCE","at":row.get("current_as_of") or end.isoformat(),"title":row.get("label"),"materiality":row.get("materiality"),"source":row.get("source")} for row in changes if row.get("materiality") in {"HIGH","MEDIUM"}]
                + [{"type":"THESIS_REVIEW","at":row["reviewed_at"],"title":row["overall_status"],"reference_id":row["id"]} for row in reviews if start <= _utc(row["reviewed_at"]) <= end]
                + [{"type":"DECISION","at":row["decision_date"],"title":f"{row['decision_type']} recorded","reference_id":row["id"]} for row in later_decisions])
    timeline.sort(key=lambda row:_utc(row["at"]))
    confirmed = sum(row["status"] == "CONFIRMED" for row in outcomes["assumptions"]); invalidated = sum(row["status"] == "INVALIDATED" for row in outcomes["assumptions"])
    process = {"thesis_support": "MOSTLY_SUPPORTED" if confirmed > invalidated else "MIXED" if confirmed and invalidated else "WEAKENED" if invalidated else "INSUFFICIENT_EVIDENCE",
               "confirmed_assumptions": confirmed, "invalidated_assumptions": invalidated,
               "interpretation": "Process evidence is separate from subsequent market return; neither proves the only reasonable action."}
    return_label = "unavailable" if market["security_return"] is None else f"{market['security_return']:.1%}"
    summary = f"{decision['ticker']} {decision['decision_type']} review: {confirmed} assumptions confirmed and {invalidated} invalidated. Security return is {return_label}; this does not determine process quality."
    return {"version":"decision-retrospective-v1", "decision":decision, "snapshot":snapshot, "horizon":{"key":horizon_key,"start":start.isoformat(),"end":end.isoformat(),"matured":requested_end <= datetime.now(timezone.utc)},
            "thesis_outcomes":outcomes, "market_outcome":market, "process_review":process, "evidence_timeline":timeline[:100],
            "evidence_coverage":[row.model_dump(mode="json") for row in change_set.coverage], "warnings":change_set.warnings,
            "grounded_summary":summary, "methodology":"Point-in-time decision snapshot plus bounded evidence changes and stored reviews; no hindsight recommendation."}


def save_retrospective(user_id: str, decision_id: str, result: dict[str, Any], notes: str = "", ai_summary: str | None = None, ai_model: str | None = None) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL); p,prefix = ("%s","public.") if postgres else ("?",""); column = "structured_result" if postgres else "structured_result_json"; connection = database.postgres_connection if postgres else database.sqlite_connection
    item_id, now = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(); horizon = result["horizon"]
    with connection() as conn:
        conn.execute(f"INSERT INTO {prefix}decision_retrospectives(id,decision_id,user_id,horizon_key,window_start,window_end,{column},user_notes,ai_summary,ai_model,summary_version,reviewed_at,created_at) VALUES ({','.join([p]*13)})",
                     (item_id,decision_id,user_id,horizon["key"],horizon["start"],horizon["end"],_json(result,postgres),notes,ai_summary,ai_model,"retrospective-summary-v1" if ai_summary else None,now,now))
    return get_retrospectives(user_id, decision_id)[0]


def get_retrospectives(user_id: str, decision_id: str | None = None) -> list[dict[str, Any]]:
    postgres = bool(database.DATABASE_URL); p,prefix = ("%s","public.") if postgres else ("?",""); column = "structured_result" if postgres else "structured_result_json"; connection = database.postgres_connection if postgres else database.sqlite_connection
    where, params = f"user_id={p}", [user_id]
    if decision_id: where += f" AND decision_id={p}"; params.append(decision_id)
    with connection() as conn: rows = conn.execute(f"SELECT * FROM {prefix}decision_retrospectives WHERE {where} ORDER BY reviewed_at DESC", tuple(params)).fetchall()
    output=[]
    for row in rows:
        value=dict(row); raw=value.pop(column); value["structured_result"]=raw if isinstance(raw,dict) else json.loads(raw); output.append(value)
    return output


def forecast_calibration(user_id: str) -> dict[str, Any]:
    resolved = [row for row in database.list_user_forecasts(user_id) if row.get("resolved_outcome") is not None]
    scores=[(float(row["probability"])-float(row["resolved_outcome"]))**2 for row in resolved]
    buckets=defaultdict(list)
    for row in resolved: buckets[int(float(row["probability"])*10)*10].append(float(row["resolved_outcome"]))
    return {"sample_size":len(resolved), "brier_score":sum(scores)/len(scores) if scores else None,
            "status":"ESTABLISHED" if len(resolved)>=10 else "INSUFFICIENT_SAMPLE",
            "message":None if len(resolved)>=10 else f"{len(resolved)} resolved forecasts are too few for a calibration claim.",
            "buckets":[{"range":f"{key}-{min(key+10,100)}%","n":len(values),"resolved_yes_rate":sum(values)/len(values)} for key,values in sorted(buckets.items())],
            "methodology":"Mean Brier score for resolved binary forecasts; minimum 10 for interpretive claims."}


def patterns(user_id: str) -> dict[str, Any]:
    reviews=get_retrospectives(user_id); by_decision={row["decision_id"]:row for row in reviews}; unique=list(by_decision.values()); categories=Counter()
    for row in unique:
        for item in row["structured_result"].get("thesis_outcomes",{}).get("assumptions",[]):
            if item.get("status") in {"INVALIDATED","NOT_CONFIRMED"}: categories[str(item.get("category") or "CUSTOM")]+=1
    observations=[{"pattern":f"{category.replace('_',' ').title()} assumptions were not confirmed", "count":count,
                   "sample_size":len(unique), "established":len(unique)>=5 and count>=3,
                   "message":f"Across {len(unique)} reviewed decisions, this occurred {count} times." + (" Sample is too small to establish a recurring pattern." if len(unique)<5 else "")}
                  for category,count in categories.most_common()]
    return {"reviewed_decisions":len(unique),"minimum_sample":5,"status":"ESTABLISHED" if len(unique)>=5 else "INSUFFICIENT_SAMPLE",
            "patterns":observations,"timeframe":{"start":min((row["window_start"] for row in unique),default=None),"end":max((row["window_end"] for row in unique),default=None)}}


def _ready(user_id: str, decisions: list[dict[str, Any]], completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_ids={row["decision_id"] for row in completed}; now=datetime.now(timezone.utc); ready=[]
    for decision in decisions:
        try: snap=get_snapshot(user_id,decision["id"])["snapshot"]
        except KeyError: continue
        days=snap.get("review_horizon_days") or 90; due=_utc(decision["decision_date"])+timedelta(days=int(days))
        if due<=now and decision["id"] not in completed_ids: ready.append({"decision":decision,"due_at":due.isoformat(),"horizon_days":days})
    return ready


def workspace(user_id: str) -> dict[str, Any]:
    decisions=theses.list_decisions(user_id); completed=get_retrospectives(user_id); captured=snapshot_decision_ids(user_id)
    recent=[{**row, "snapshot_available": row["id"] in captured,
             "snapshot_missing_reason": None if row["id"] in captured else "This decision predates immutable context capture; EagleEyes will not reconstruct it with hindsight."}
            for row in decisions[:30]]
    return {"version":"decision-journal-v1","recent_decisions":recent,"ready_for_review":_ready(user_id, decisions, completed),"completed_retrospectives":completed[:30],"patterns":patterns(user_id),"forecast_calibration":forecast_calibration(user_id)}


def ready_for_review(user_id: str) -> list[dict[str, Any]]:
    return _ready(user_id, theses.list_decisions(user_id), get_retrospectives(user_id))
