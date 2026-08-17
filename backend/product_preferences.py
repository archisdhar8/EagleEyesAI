from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import database, decision_journal


ALERT_CATEGORIES = {
    "thesis_breakers": {"THESIS_BREAKER_TRIGGERED", "THESIS_BREAKER_WARNING"},
    "thesis_weakening": {"THESIS_WEAKENED", "IMPORTANT_ASSUMPTION_CHANGE"},
    "earnings_changes": {"MATERIAL_EARNINGS_CHANGE", "MATERIAL_ESTIMATE_REVISION", "GUIDANCE_CHANGE"},
    "prediction_market_changes": {"PREDICTION_MARKET_CHANGE"},
    "portfolio_risk_changes": {"PORTFOLIO_RISK_CHANGE", "SCENARIO_RISK_CHANGE"},
    "review_reminders": {"UPCOMING_REVIEW"},
}
DEFAULT_ALERT_PREFERENCES = {
    "delivery_mode": "IN_APP_ONLY", "threshold": "MATERIAL",
    "categories": {key: True for key in ALERT_CATEGORIES},
}
SEVERITY = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _json(value: Any, postgres: bool) -> Any:
    return database._jsonb(value) if postgres else json.dumps(value, default=str)  # type: ignore[attr-defined]


def alert_preferences(user_id: str) -> dict[str, Any]:
    postgres = bool(database.DATABASE_URL); p,prefix=("%s","public.") if postgres else ("?","")
    connection=database.postgres_connection if postgres else database.sqlite_connection
    with connection() as conn:
        row=conn.execute(f"SELECT delivery_mode,threshold,categories,updated_at FROM {prefix}alert_preferences WHERE user_id={p}",(user_id,)).fetchone()
    if not row:return {**DEFAULT_ALERT_PREFERENCES,"updated_at":None}
    value=dict(row); categories=value.get("categories")
    if not isinstance(categories,dict): categories=json.loads(categories or "{}")
    return {"delivery_mode":value["delivery_mode"],"threshold":value["threshold"],
            "categories":{**DEFAULT_ALERT_PREFERENCES["categories"],**categories},"updated_at":database._iso(value.get("updated_at"))}  # type: ignore[attr-defined]


def save_alert_preferences(user_id: str, value: dict[str, Any]) -> dict[str, Any]:
    delivery="IN_APP_ONLY"
    threshold=value.get("threshold") if value.get("threshold") in {"MATERIAL","CRITICAL_ONLY"} else "MATERIAL"
    categories={key:bool((value.get("categories") or {}).get(key,True)) for key in ALERT_CATEGORIES}
    postgres=bool(database.DATABASE_URL); p,prefix=("%s","public.") if postgres else ("?",""); now=datetime.now(timezone.utc).isoformat()
    connection=database.postgres_connection if postgres else database.sqlite_connection
    with connection() as conn:
        conn.execute(f"""INSERT INTO {prefix}alert_preferences(user_id,delivery_mode,threshold,categories,created_at,updated_at)
        VALUES ({','.join([p]*6)}) ON CONFLICT(user_id) DO UPDATE SET delivery_mode=excluded.delivery_mode,
        threshold=excluded.threshold,categories=excluded.categories,updated_at=excluded.updated_at""",
        (user_id,delivery,threshold,_json(categories,postgres),now,now))
    return alert_preferences(user_id)


def _category_enabled(item_type: str, preferences: dict[str, Any]) -> bool:
    return any(item_type in types and preferences["categories"].get(category, True) for category,types in ALERT_CATEGORIES.items())


def materialize_alerts(user_id: str, attention_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist only grouped material attention; this is not a second signal engine."""
    preferences=alert_preferences(user_id); postgres=bool(database.DATABASE_URL); p,prefix=("%s","public.") if postgres else ("?","")
    connection=database.postgres_connection if postgres else database.sqlite_connection
    for item in attention_items:
        materiality=str(item.get("materiality") or "UNKNOWN")
        if materiality not in {"CRITICAL","HIGH","MEDIUM"} or not _category_enabled(str(item.get("type")),preferences):continue
        if preferences["threshold"]=="CRITICAL_ONLY" and materiality!="CRITICAL":continue
        attention_id=str(item.get("id") or ""); group_key=str(item.get("group_key") or attention_id)
        if not attention_id:continue
        with connection() as conn:
            existing=conn.execute(f"SELECT id FROM {prefix}alert_events WHERE user_id={p} AND attention_item_id={p}",(user_id,attention_id)).fetchone()
            if existing:continue
            previous=conn.execute(f"SELECT id,materiality FROM {prefix}alert_events WHERE user_id={p} AND group_key={p} AND status='ACTIVE' ORDER BY occurred_at DESC LIMIT 1",(user_id,group_key)).fetchone()
            if previous and SEVERITY.get(materiality,0)<SEVERITY.get(str(previous["materiality"]),0):continue
            event_id=str(uuid.uuid4()); payload={key:item.get(key) for key in ("entity_type","entity_key","action_label","action_target","affected","ranking_inputs")}
            conn.execute(f"""INSERT INTO {prefix}alert_events(id,user_id,attention_item_id,group_key,alert_type,materiality,title,summary,payload,occurred_at,supersedes_id,status,created_at)
            VALUES ({','.join([p]*13)})""",(event_id,user_id,attention_id,group_key,item.get("type"),materiality,item.get("title"),item.get("summary"),_json(payload,postgres),item.get("occurred_at"),str(previous["id"]) if previous else None,"ACTIVE",datetime.now(timezone.utc).isoformat()))
            if previous:conn.execute(f"UPDATE {prefix}alert_events SET status='SUPERSEDED' WHERE id={p} AND user_id={p}",(str(previous["id"]),user_id))
    return alerts(user_id)


def alerts(user_id: str, include_history: bool = False) -> list[dict[str, Any]]:
    postgres=bool(database.DATABASE_URL); p,prefix=("%s","public.") if postgres else ("?",""); connection=database.postgres_connection if postgres else database.sqlite_connection
    clause="" if include_history else " AND status='ACTIVE'"
    with connection() as conn:rows=conn.execute(f"SELECT * FROM {prefix}alert_events WHERE user_id={p}{clause} ORDER BY occurred_at DESC LIMIT 100",(user_id,)).fetchall()
    output=[]
    for row in rows:
        value=dict(row); payload=value.get("payload")
        value["payload"]=payload if isinstance(payload,dict) else json.loads(payload or "{}")
        for key in ("occurred_at","created_at"):value[key]=database._iso(value.get(key))  # type: ignore[attr-defined]
        output.append(value)
    return output


def personalization(user_id: str) -> dict[str, Any]:
    postgres=bool(database.DATABASE_URL); p,prefix=("%s","public.") if postgres else ("?",""); connection=database.postgres_connection if postgres else database.sqlite_connection
    with connection() as conn:row=conn.execute(f"SELECT explicit_preferences,accepted_preferences,dismissed_inferences,updated_at FROM {prefix}decision_preferences WHERE user_id={p}",(user_id,)).fetchone()
    stored={"explicit_preferences":{},"accepted_preferences":{},"dismissed_inferences":[]}
    if row:
        for key in stored:
            raw=row[key];stored[key]=raw if isinstance(raw,(dict,list)) else json.loads(raw or ("[]" if key=="dismissed_inferences" else "{}"))
    profile=database.load_profile(user_id) or {}
    policy=database.load_investment_policy(user_id) or {}
    explicit={"investment_horizon_years":profile.get("horizon_years"),"research_preferences":profile.get("research_preferences",{}),
              "risk_tolerance":profile.get("risk_tolerance"),"loss_capacity":profile.get("loss_capacity"),
              "max_single_stock_weight":policy.get("max_single_stock_weight"),"max_sector_weight":policy.get("max_sector_weight"),
              **stored["explicit_preferences"]}
    patterns=decision_journal.patterns(user_id); dismissed=set(stored["dismissed_inferences"]); inferred=[]
    if patterns["status"]=="ESTABLISHED":
        for index,item in enumerate(patterns["patterns"]):
            if not item.get("established"):continue
            key=f"review_pattern_{index}"
            if key not in dismissed:inferred.append({"key":key,"label":item["pattern"],"value":"prioritize_related_evidence","sample_size":item["sample_size"],"basis":item["message"]})
    return {"version":"decision-preferences-v1","explicit":explicit,"accepted":stored["accepted_preferences"],
            "inferred":inferred,"dismissed":list(dismissed),"minimum_reviewed_decisions":patterns["minimum_sample"],
            "reviewed_decisions":patterns["reviewed_decisions"],"updated_at":database._iso(row["updated_at"]) if row else None}  # type: ignore[attr-defined]


def save_personalization(user_id: str, value: dict[str, Any]) -> dict[str, Any]:
    postgres=bool(database.DATABASE_URL); p,prefix=("%s","public.") if postgres else ("?",""); connection=database.postgres_connection if postgres else database.sqlite_connection
    explicit={str(key)[:80]:item for key,item in (value.get("explicit") or {}).items() if key in {"growth_value_preference","income_preference","preferred_sectors","preferred_themes","valuation_boundary_pe","saved_macro_beliefs"}}
    accepted={str(key)[:120]:item for key,item in (value.get("accepted") or {}).items()}
    dismissed=list(dict.fromkeys(str(item)[:120] for item in value.get("dismissed",[])))[:100];now=datetime.now(timezone.utc).isoformat()
    with connection() as conn:conn.execute(f"""INSERT INTO {prefix}decision_preferences(user_id,explicit_preferences,accepted_preferences,dismissed_inferences,created_at,updated_at)
      VALUES ({','.join([p]*6)}) ON CONFLICT(user_id) DO UPDATE SET explicit_preferences=excluded.explicit_preferences,
      accepted_preferences=excluded.accepted_preferences,dismissed_inferences=excluded.dismissed_inferences,updated_at=excluded.updated_at""",
      (user_id,_json(explicit,postgres),_json(accepted,postgres),_json(dismissed,postgres),now,now))
    return personalization(user_id)


def ask_context(user_id: str) -> dict[str, Any] | None:
    value=personalization(user_id)
    explicit={key:item for key,item in value["explicit"].items() if item not in (None,"",[],{})}
    compact={"explicit":explicit,"accepted":value["accepted"]}
    return compact if any(compact.values()) else None


def prioritize_attention(items: list[dict[str, Any]], preference_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Stable, explainable ordering inside materiality bands using accepted preferences only."""
    accepted=list((preference_payload.get("accepted") or {}).values())
    labels=[str(item.get("label") or item.get("basis") or item).lower() for item in accepted]
    if not labels:
        return items
    enriched=[]
    for index,item in enumerate(items):
        haystack=" ".join(str(item.get(key) or "") for key in ("title","summary","type","entity_key")).lower()
        matched=next((label for label in labels if any(token in haystack for token in label.split() if len(token)>4)),None)
        copied={**item}
        if matched:
            copied["ranking_inputs"]={**(copied.get("ranking_inputs") or {}),
                "personalization":f"Accepted decision preference: {matched[:120]}"}
        enriched.append((index,copied,bool(matched)))
    rank={"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1,"UNKNOWN":0}
    enriched.sort(key=lambda row:(-rank.get(str(row[1].get("materiality")),0),-int(row[2]),row[0]))
    return [row[1] for row in enriched]


def personalize_research(payload: dict[str, Any], preference_payload: dict[str, Any]) -> dict[str, Any]:
    """Use accepted qualitative preferences only as a disclosed tie-breaker, never as a financial score."""
    accepted=list((preference_payload.get("accepted") or {}).values())
    labels=[str(item.get("label") or "").strip() for item in accepted if isinstance(item,dict)]
    rows=list(payload.get("results") or [])
    if not labels or len(rows)<2:
        payload["personalization"]={"applied":False,"reason":"No accepted relevant preference changed this ordering."}
        return payload
    enriched=[]
    for index,row in enumerate(rows):
        haystack=" ".join([str(row.get(key) or "") for key in ("company","sector","industry","evidence_bucket","what_would_change_the_view")]
                           +[str(item.get("label") or "") for item in row.get("strengths",[])]
                           +[str(item) for item in row.get("thesis_risks",[])]).lower()
        matches=[label for label in labels if any(token in haystack for token in label.lower().split() if len(token)>4)]
        copied={**row,"personalization_reasons":[f"Accepted preference match: {label[:120]}" for label in matches]}
        enriched.append((index,copied,bool(matches)))
    enriched.sort(key=lambda item:(-int(item[2]),item[0]))
    ordered=[item[1] for item in enriched]
    for index,row in enumerate(ordered,1):row["relative_rank"]=index
    payload["results"]=ordered
    payload["personalization"]={"applied":any(item[2] for item in enriched),
        "reason":"Accepted qualitative preferences are a stable tie-breaker after deterministic eligibility and evidence calculations. They do not change financial scores."}
    return payload
