from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from . import database
from .models import InvestmentDecisionPayload, InvestmentThesisPayload, ThesisAssumptionPayload, ThesisFactorPayload


OPEN_STATUSES = ("DRAFT", "ACTIVE", "UNDER_REVIEW")
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _json(value: Any, postgres: bool) -> Any:
    return database._jsonb(_plain(value)) if postgres else json.dumps(_plain(value), default=str)


def _read_json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return _plain(value)


def _row(row: Any) -> dict[str, Any]:
    return {key: _plain(value) for key, value in dict(row).items()}


def _connect():
    return database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()


def _ph(postgres: bool) -> str:
    return "%s" if postgres else "?"


def _fetch_detail(conn: Any, user_id: str, thesis_id: str, postgres: bool) -> dict[str, Any]:
    p = _ph(postgres)
    prefix = "public." if postgres else ""
    item = conn.execute(
        f"SELECT * FROM {prefix}investment_theses WHERE id={p} AND user_id={p}",
        (thesis_id, user_id),
    ).fetchone()
    if item is None:
        raise KeyError(thesis_id)
    thesis = _row(item)
    source_key = "source_context" if postgres else "source_context_json"
    thesis["source_context"] = _read_json(thesis.pop(source_key, None))
    assumptions = conn.execute(
        f"SELECT * FROM {prefix}thesis_assumptions WHERE thesis_id={p} AND user_id={p} ORDER BY created_at,id",
        (thesis_id, user_id),
    ).fetchall()
    factors = conn.execute(
        f"SELECT * FROM {prefix}thesis_factors WHERE thesis_id={p} AND user_id={p} ORDER BY created_at,id",
        (thesis_id, user_id),
    ).fetchall()
    thesis["assumptions"] = []
    for raw in assumptions:
        value = _row(raw)
        evidence_key = "evidence_mapping" if postgres else "evidence_mapping_json"
        value["evidence_mapping"] = _read_json(value.pop(evidence_key, None))
        value["operator"] = value.pop("comparison_operator", None)
        thesis["assumptions"].append(value)
    thesis["factors"] = []
    for raw in factors:
        value = _row(raw)
        evidence_key = "evidence_mapping" if postgres else "evidence_mapping_json"
        value["evidence_mapping"] = _read_json(value.pop(evidence_key, None))
        value["operator"] = value.pop("comparison_operator", None)
        thesis["factors"].append(value)
    thesis["catalysts"] = [item for item in thesis["factors"] if item["factor_type"] == "CATALYST"]
    thesis["risks"] = [item for item in thesis["factors"] if item["factor_type"] == "RISK"]
    thesis["thesis_breakers"] = [item for item in thesis["factors"] if item["factor_type"] == "BREAKER"]
    return thesis


def _snapshot(detail: dict[str, Any]) -> dict[str, Any]:
    excluded = {"created_at", "updated_at", "closed_at", "current_version", "catalysts", "risks", "thesis_breakers"}
    snapshot = {key: _plain(value) for key, value in detail.items() if key not in excluded}
    child_excluded = {"id", "thesis_id", "user_id", "created_at", "updated_at"}
    for collection in ("assumptions", "factors"):
        snapshot[collection] = [
            {key: value for key, value in item.items() if key not in child_excluded}
            for item in snapshot.get(collection, [])
        ]
    return snapshot


def _insert_assumption(conn: Any, user_id: str, thesis_id: str, payload: ThesisAssumptionPayload, postgres: bool) -> str:
    p = _ph(postgres)
    prefix = "public." if postgres else ""
    item_id, now = payload.id or str(uuid.uuid4()), _now()
    evidence_col = "evidence_mapping" if postgres else "evidence_mapping_json"
    conn.execute(
        f"""INSERT INTO {prefix}thesis_assumptions
        (id,thesis_id,user_id,description,category,importance,status,metric,comparison_operator,target_value,unit,{evidence_col},created_at,updated_at)
        VALUES ({','.join([p] * 14)})""",
        (item_id, thesis_id, user_id, payload.description, payload.category, payload.importance, payload.status,
         payload.metric, payload.operator, payload.target_value, payload.unit, _json(payload.evidence_mapping, postgres), now, now),
    )
    return item_id


def _insert_factor(conn: Any, user_id: str, thesis_id: str, payload: ThesisFactorPayload, postgres: bool) -> str:
    p = _ph(postgres)
    prefix = "public." if postgres else ""
    item_id, now = payload.id or str(uuid.uuid4()), _now()
    evidence_col = "evidence_mapping" if postgres else "evidence_mapping_json"
    conn.execute(
        f"""INSERT INTO {prefix}thesis_factors
        (id,thesis_id,user_id,factor_type,description,metric,comparison_operator,threshold,period_requirement,unit,{evidence_col},created_at,updated_at)
        VALUES ({','.join([p] * 13)})""",
        (item_id, thesis_id, user_id, payload.factor_type, payload.description, payload.metric, payload.operator,
         payload.threshold, payload.period_requirement, payload.unit, _json(payload.evidence_mapping, postgres), now, now),
    )
    return item_id


def _write_version(conn: Any, user_id: str, detail: dict[str, Any], version: int, change_note: str | None, postgres: bool) -> str:
    p = _ph(postgres)
    prefix = "public." if postgres else ""
    snapshot_col = "snapshot" if postgres else "snapshot_json"
    version_id = str(uuid.uuid4())
    conn.execute(
        f"INSERT INTO {prefix}thesis_versions(id,thesis_id,user_id,version_number,{snapshot_col},change_note,created_at) VALUES ({','.join([p] * 7)})",
        (version_id, detail["id"], user_id, version, _json(_snapshot(detail), postgres), change_note, _now()),
    )
    return version_id


def _capture_boundary(user_id: str, ticker: str, baseline_type: str, reference_id: str, as_of: datetime | None = None) -> dict[str, Any] | None:
    try:
        from .evidence import capture_snapshot
        return capture_snapshot(user_id, ticker, baseline_type, reference_id, as_of)  # type: ignore[arg-type]
    except Exception:
        # Saving a thesis/decision is the primary transaction. A provider or
        # evidence-store outage must not destroy the user's decision record.
        logger.exception("Evidence snapshot capture failed for %s %s", baseline_type, reference_id)
        return None


def create_thesis(user_id: str, payload: InvestmentThesisPayload) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL)
    p, prefix, now = _ph(postgres), "public." if postgres else "", _now()
    thesis_id = str(uuid.uuid4())
    with _connect() as conn:
        existing = conn.execute(
            f"SELECT id FROM {prefix}investment_theses WHERE user_id={p} AND ticker={p} AND status IN ({','.join([p]*3)})",
            (user_id, payload.ticker, *OPEN_STATUSES),
        ).fetchone()
        if existing:
            raise ValueError("An open thesis already exists for this security")
        source_col = "source_context" if postgres else "source_context_json"
        conn.execute(
            f"""INSERT INTO {prefix}investment_theses
            (id,user_id,ticker,summary,base_case,bull_case,bear_case,investment_horizon,horizon_end_date,review_date,status,{source_col},current_version,closed_at,created_at,updated_at)
            VALUES ({','.join([p] * 16)})""",
            (thesis_id, user_id, payload.ticker, payload.summary, payload.base_case, payload.bull_case, payload.bear_case,
             payload.investment_horizon, _plain(payload.horizon_end_date), _plain(payload.review_date), payload.status,
             _json(payload.source_context, postgres), 1, now if payload.status in ("CLOSED", "ARCHIVED") else None, now, now),
        )
        for item in payload.assumptions:
            _insert_assumption(conn, user_id, thesis_id, item, postgres)
        for item in payload.factors:
            _insert_factor(conn, user_id, thesis_id, item, postgres)
        detail = _fetch_detail(conn, user_id, thesis_id, postgres)
        version_id = _write_version(conn, user_id, detail, 1, payload.change_note or "Original thesis", postgres)
    _capture_boundary(user_id, payload.ticker, "LAST_THESIS_REVIEW", version_id, datetime.fromisoformat(now))
    return get_thesis(user_id, thesis_id)


def update_thesis(user_id: str, thesis_id: str, payload: InvestmentThesisPayload) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL)
    p, prefix, now = _ph(postgres), "public." if postgres else "", _now()
    version_id = None
    with _connect() as conn:
        previous = _fetch_detail(conn, user_id, thesis_id, postgres)
        if payload.ticker != previous["ticker"]:
            raise ValueError("A thesis ticker cannot be changed; close it and create a new thesis")
        source_col = "source_context" if postgres else "source_context_json"
        cursor = conn.execute(
            f"""UPDATE {prefix}investment_theses SET summary={p},base_case={p},bull_case={p},bear_case={p},
            investment_horizon={p},horizon_end_date={p},review_date={p},status={p},{source_col}={p},
            closed_at={p},updated_at={p} WHERE id={p} AND user_id={p}""",
            (payload.summary, payload.base_case, payload.bull_case, payload.bear_case, payload.investment_horizon,
             _plain(payload.horizon_end_date), _plain(payload.review_date), payload.status, _json(payload.source_context, postgres),
             now if payload.status in ("CLOSED", "ARCHIVED") else None, now, thesis_id, user_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(thesis_id)
        conn.execute(f"DELETE FROM {prefix}thesis_assumptions WHERE thesis_id={p} AND user_id={p}", (thesis_id, user_id))
        conn.execute(f"DELETE FROM {prefix}thesis_factors WHERE thesis_id={p} AND user_id={p}", (thesis_id, user_id))
        for item in payload.assumptions:
            _insert_assumption(conn, user_id, thesis_id, item, postgres)
        for item in payload.factors:
            _insert_factor(conn, user_id, thesis_id, item, postgres)
        current = _fetch_detail(conn, user_id, thesis_id, postgres)
        if _snapshot(current) != _snapshot(previous):
            next_version = int(previous["current_version"]) + 1
            conn.execute(f"UPDATE {prefix}investment_theses SET current_version={p} WHERE id={p} AND user_id={p}", (next_version, thesis_id, user_id))
            current["current_version"] = next_version
            version_id = _write_version(conn, user_id, current, next_version, payload.change_note or "Thesis revised", postgres)
    # A normal thesis edit creates version history but does not move the
    # evidence baseline. Only the explicit review workflow does that.
    return get_thesis(user_id, thesis_id)


def get_thesis(user_id: str, thesis_id: str) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL)
    with _connect() as conn:
        return _fetch_detail(conn, user_id, thesis_id, postgres)


def list_theses(user_id: str, ticker: str | None = None) -> list[dict[str, Any]]:
    postgres = bool(database.DATABASE_URL)
    p, prefix = _ph(postgres), "public." if postgres else ""
    with _connect() as conn:
        params: list[Any] = [user_id]
        where = f"user_id={p}"
        if ticker:
            where += f" AND ticker={p}"
            params.append(ticker.upper())
        rows = conn.execute(f"SELECT id FROM {prefix}investment_theses WHERE {where} ORDER BY updated_at DESC", tuple(params)).fetchall()
        return [_fetch_detail(conn, user_id, str(row["id"]), postgres) for row in rows]


def active_thesis(user_id: str, ticker: str) -> dict[str, Any] | None:
    return next((item for item in list_theses(user_id, ticker) if item["status"] in OPEN_STATUSES), None)


def thesis_history(user_id: str, thesis_id: str) -> list[dict[str, Any]]:
    get_thesis(user_id, thesis_id)
    postgres = bool(database.DATABASE_URL)
    p, prefix = _ph(postgres), "public." if postgres else ""
    snapshot_col = "snapshot" if postgres else "snapshot_json"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id,version_number,{snapshot_col},change_note,created_at FROM {prefix}thesis_versions WHERE thesis_id={p} AND user_id={p} ORDER BY version_number DESC",
            (thesis_id, user_id),
        ).fetchall()
    return [{**_row(item), "snapshot": _read_json(dict(item)[snapshot_col])} for item in rows]


def _edit_payload(detail: dict[str, Any], change_note: str) -> InvestmentThesisPayload:
    return InvestmentThesisPayload.model_validate({
        "ticker": detail["ticker"], "summary": detail["summary"], "base_case": detail["base_case"],
        "bull_case": detail["bull_case"], "bear_case": detail["bear_case"],
        "investment_horizon": detail["investment_horizon"], "horizon_end_date": detail.get("horizon_end_date"),
        "review_date": detail.get("review_date"), "status": detail["status"],
        "source_context": detail.get("source_context") or {}, "change_note": change_note,
        "assumptions": detail.get("assumptions") or [], "factors": detail.get("factors") or [],
    })


def add_assumption(user_id: str, thesis_id: str, payload: ThesisAssumptionPayload) -> dict[str, Any]:
    detail = get_thesis(user_id, thesis_id)
    item = payload.model_copy(update={"id": payload.id or str(uuid.uuid4())})
    edit = _edit_payload(detail, "Assumption added")
    edit.assumptions.append(item)
    updated = update_thesis(user_id, thesis_id, edit)
    return next(value for value in updated["assumptions"] if value["id"] == item.id)


def update_assumption(user_id: str, thesis_id: str, assumption_id: str, payload: ThesisAssumptionPayload) -> dict[str, Any]:
    detail = get_thesis(user_id, thesis_id)
    if not any(item["id"] == assumption_id for item in detail["assumptions"]):
        raise KeyError(assumption_id)
    item = payload.model_copy(update={"id": assumption_id})
    edit = _edit_payload(detail, "Assumption revised")
    edit.assumptions = [item if value.id == assumption_id else value for value in edit.assumptions]
    updated = update_thesis(user_id, thesis_id, edit)
    return next(value for value in updated["assumptions"] if value["id"] == assumption_id)


def delete_assumption(user_id: str, thesis_id: str, assumption_id: str) -> dict[str, Any]:
    detail = get_thesis(user_id, thesis_id)
    if not any(item["id"] == assumption_id for item in detail["assumptions"]):
        raise KeyError(assumption_id)
    edit = _edit_payload(detail, "Assumption removed")
    edit.assumptions = [item for item in edit.assumptions if item.id != assumption_id]
    return update_thesis(user_id, thesis_id, edit)


def add_factor(user_id: str, thesis_id: str, payload: ThesisFactorPayload) -> dict[str, Any]:
    detail = get_thesis(user_id, thesis_id)
    item = payload.model_copy(update={"id": payload.id or str(uuid.uuid4())})
    edit = _edit_payload(detail, f"{payload.factor_type.title()} added")
    edit.factors.append(item)
    updated = update_thesis(user_id, thesis_id, edit)
    return next(value for value in updated["factors"] if value["id"] == item.id)


def update_factor(user_id: str, thesis_id: str, factor_id: str, payload: ThesisFactorPayload) -> dict[str, Any]:
    detail = get_thesis(user_id, thesis_id)
    if not any(item["id"] == factor_id for item in detail["factors"]):
        raise KeyError(factor_id)
    item = payload.model_copy(update={"id": factor_id})
    edit = _edit_payload(detail, f"{payload.factor_type.title()} revised")
    edit.factors = [item if value.id == factor_id else value for value in edit.factors]
    updated = update_thesis(user_id, thesis_id, edit)
    return next(value for value in updated["factors"] if value["id"] == factor_id)


def delete_factor(user_id: str, thesis_id: str, factor_id: str) -> dict[str, Any]:
    detail = get_thesis(user_id, thesis_id)
    if not any(item["id"] == factor_id for item in detail["factors"]):
        raise KeyError(factor_id)
    edit = _edit_payload(detail, "Thesis factor removed")
    edit.factors = [item for item in edit.factors if item.id != factor_id]
    return update_thesis(user_id, thesis_id, edit)


def latest_price_observation(ticker: str, as_of: datetime | None = None) -> dict[str, Any]:
    prices = database.security_data([ticker], price_limit=2600 if as_of else 1).get("prices", [])
    if as_of:
        boundary = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        def observed_at(row: dict[str, Any]) -> datetime | None:
            if not row.get("date"): return None
            parsed = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        prices = [row for row in prices if observed_at(row) is not None and observed_at(row) <= boundary]
    if not prices:
        return {"price_at_decision": None, "price_as_of": None, "price_source": None}
    row = max(prices, key=lambda item: str(item.get("date") or item.get("ts") or ""))
    return {"price_at_decision": _plain(row.get("close")), "price_as_of": _plain(row.get("date") or row.get("ts")), "price_source": row.get("provider")}


def record_decision(user_id: str, payload: InvestmentDecisionPayload) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL)
    p, prefix, now = _ph(postgres), "public." if postgres else "", _now()
    thesis_version = None
    thesis_snapshot = None
    if payload.thesis_id:
        thesis = get_thesis(user_id, payload.thesis_id)
        if thesis["ticker"] != payload.ticker:
            raise ValueError("The linked thesis belongs to a different security")
        thesis_version = thesis["current_version"]
        version = next((row for row in thesis_history(user_id, payload.thesis_id) if row["version_number"] == thesis_version), None)
        thesis_snapshot = (version or {}).get("snapshot")
    decision_date = payload.decision_date or datetime.now(timezone.utc)
    observed = latest_price_observation(payload.ticker, decision_date)
    item_id = str(uuid.uuid4())
    portfolio_col = "portfolio_context" if postgres else "portfolio_context_json"
    source_col = "source_context" if postgres else "source_context_json"
    source_context = {**payload.source_context, "expected_outcome": payload.expected_outcome,
                      "review_horizon_days": payload.review_horizon_days,
                      "comparison_benchmark": payload.comparison_benchmark}
    evidence_boundary = _capture_boundary(user_id, payload.ticker, "LAST_DECISION", item_id, decision_date)
    decision_record = {
        "id": item_id, "ticker": payload.ticker, "decision_type": payload.decision_type,
        "decision_date": decision_date, "thesis_id": payload.thesis_id, "thesis_version": thesis_version,
        **observed, "portfolio_context": payload.portfolio_context, "user_confidence": payload.user_confidence,
        "investment_horizon": payload.investment_horizon, "notes": payload.notes, "source_context": source_context,
    }
    from . import decision_journal
    context_snapshot = decision_journal.build_snapshot(user_id, item_id, decision_record, thesis_snapshot, evidence_boundary)
    with _connect() as conn:
        conn.execute(
            f"""INSERT INTO {prefix}investment_decisions
            (id,user_id,ticker,thesis_id,thesis_version,decision_type,decision_date,price_at_decision,price_as_of,price_source,
            quantity,{portfolio_col},user_confidence,investment_horizon,notes,{source_col},created_at)
            VALUES ({','.join([p] * 17)})""",
            (item_id, user_id, payload.ticker, payload.thesis_id, thesis_version, payload.decision_type, _plain(decision_date),
             observed["price_at_decision"], observed["price_as_of"], observed["price_source"], payload.quantity,
             _json(payload.portfolio_context, postgres), payload.user_confidence, payload.investment_horizon,
             payload.notes, _json(source_context, postgres), now),
        )
        decision_journal.insert_snapshot(conn, user_id, item_id, payload.ticker, _plain(decision_date), context_snapshot, postgres)
    return next(item for item in list_decisions(user_id) if item["id"] == item_id)


def list_decisions(user_id: str, ticker: str | None = None) -> list[dict[str, Any]]:
    postgres = bool(database.DATABASE_URL)
    p, prefix = _ph(postgres), "public." if postgres else ""
    params: list[Any] = [user_id]
    where = f"user_id={p}"
    if ticker:
        where += f" AND ticker={p}"
        params.append(ticker.upper())
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM {prefix}investment_decisions WHERE {where} ORDER BY decision_date DESC,created_at DESC", tuple(params)).fetchall()
    values = []
    for item in rows:
        value = _row(item)
        for name in ("portfolio_context", "source_context"):
            key = name if postgres else f"{name}_json"
            value[name] = _read_json(value.pop(key, None))
        values.append(value)
    return values


def decision_contexts(user_id: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
    normalized = sorted({ticker.upper() for ticker in tickers if ticker and ticker.upper() != "CASH"})
    theses = list_theses(user_id)
    decisions = list_decisions(user_id)
    result: dict[str, dict[str, Any]] = {}
    for ticker in normalized:
        active = next((item for item in theses if item["ticker"] == ticker and item["status"] in OPEN_STATUSES), None)
        latest = next((item for item in decisions if item["ticker"] == ticker), None)
        result[ticker] = {
            "has_open_thesis": active is not None,
            "thesis_id": active["id"] if active else None,
            "thesis_status": active["status"] if active else None,
            "review_date": active["review_date"] if active else None,
            "latest_decision": latest["decision_type"] if latest else None,
            "latest_decision_date": latest["decision_date"] if latest else None,
        }
    return result


def workspace(user_id: str, holdings: list[dict[str, Any]], watchlist: list[str]) -> dict[str, Any]:
    theses = list_theses(user_id)
    decisions = list_decisions(user_id)
    active = [item for item in theses if item["status"] in OPEN_STATUSES]
    held = sorted({str(item.get("ticker") or "").upper() for item in holdings if item.get("ticker") and item["ticker"].upper() != "CASH"})
    watched = sorted({item.upper() for item in watchlist if item and item.upper() != "CASH"})
    open_tickers = {item["ticker"] for item in active}
    needs = [{"ticker": ticker, "source": "holding" if ticker in held else "watchlist"} for ticker in sorted((set(held) | set(watched)) - open_tickers)]
    reviews = sorted([item for item in active if item.get("review_date")], key=lambda item: item["review_date"])
    from .thesis_monitor import latest_summaries
    monitor_statuses = latest_summaries(user_id, [str(item["id"]) for item in active])
    for item in active:
        item["monitor_status"] = monitor_statuses.get(str(item["id"]))
    return {
        "active_theses": active,
        "recent_decisions": decisions[:30],
        "needs_thesis": needs,
        "review_dates": reviews,
        "contexts": decision_contexts(user_id, held + watched),
        "monitor_statuses": monitor_statuses,
    }


def evidence_draft(ticker: str, research: dict[str, Any] | None) -> dict[str, Any]:
    row = research or {}
    company = row.get("company") or ticker
    risks = [item for item in (row.get("thesis_risks") or row.get("risk_flags") or []) if item]
    catalysts = [item for item in (row.get("catalysts") or []) if item]
    freshness = row.get("freshness") or {}
    missing = (row.get("field_coverage") or {}).get("missing") or []
    assumptions = []
    trend = row.get("fundamental_trend") or {}
    if trend.get("revenue_growth") is not None:
        assumptions.append({
            "description": f"Revenue growth remains supportive of the {company} base case.", "category": "GROWTH",
            "importance": "HIGH", "status": "UNTESTED", "evidence_mapping": {"observed_value": trend["revenue_growth"], "field": "revenue_growth", "source": "stored research"},
        })
    if trend.get("net_margin") is not None:
        assumptions.append({
            "description": f"Net margin remains consistent with the {company} quality case.", "category": "MARGIN",
            "importance": "HIGH", "status": "UNTESTED", "evidence_mapping": {"observed_value": trend["net_margin"], "field": "net_margin", "source": "stored research"},
        })
    factors = [
        {"factor_type": "RISK", "description": str(item).replace("_", " "), "evidence_mapping": {"source": "stored research"}}
        for item in risks[:5]
    ] + [
        {"factor_type": "CATALYST", "description": item.get("title") if isinstance(item, dict) else str(item), "evidence_mapping": {"source_url": item.get("source_url") if isinstance(item, dict) else None, "source": "stored research"}}
        for item in catalysts[:5]
    ]
    factors.append({
        "factor_type": "BREAKER", "description": "The core operating evidence deteriorates enough that the original base case no longer holds.",
        "evidence_mapping": {"source": "user-defined draft; monitoring threshold not yet specified"},
    })
    draft = {
            "ticker": ticker, "summary": f"{company} may merit consideration if the stored business evidence persists; confirm the assumptions before saving.",
            "base_case": "Base-case expectations require investor input. Stored evidence has been attached where available.",
            "bull_case": "Not specified—add the evidence and conditions that would produce upside.",
            "bear_case": "Not specified—add the evidence and conditions that would produce downside.",
            "investment_horizon": "long", "review_date": None, "status": "DRAFT", "assumptions": assumptions, "factors": factors,
            "source_context": {"draft_method": "verified_evidence_starter", "price_as_of": freshness.get("price_as_of"), "fundamentals_as_of": freshness.get("fundamentals_as_of"), "missing_fields": missing},
    }
    ai_warning = None
    if research:
        try:
            from .chat import draft_thesis_prose
            prose, model = draft_thesis_prose(row, {key: draft[key] for key in ("summary", "base_case", "bull_case", "bear_case")})
            draft.update(prose)
            draft["source_context"].update({"draft_method": "ai_synthesis_of_verified_evidence", "model": model})
        except RuntimeError as exc:
            ai_warning = str(exc)
    warning = "This editable starter is not an investment decision and has not been saved. Missing evidence remains explicit."
    if ai_warning:
        warning += f" AI synthesis was unavailable ({ai_warning}); the verified-evidence starter was used."
    return {
        "draft": draft,
        "saved": False,
        "warning": warning,
    }
