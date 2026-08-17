from __future__ import annotations

from backend import product_preferences


def _item(identifier: str, *, materiality: str = "HIGH", group: str = "thesis:nvda") -> dict:
    return {
        "id": identifier, "group_key": group, "type": "THESIS_WEAKENED", "materiality": materiality,
        "title": "NVDA thesis weakened", "summary": "A saved assumption needs review.",
        "occurred_at": "2026-08-16T12:00:00+00:00", "entity_type": "THESIS", "entity_key": "NVDA",
        "action_label": "Review thesis", "action_target": "/decisions", "affected": ["NVDA"],
        "ranking_inputs": {"thesis_relevance": "HIGH"},
    }


def test_alerts_reuse_attention_and_deduplicate_by_attention_id() -> None:
    first=product_preferences.materialize_alerts("user-a",[_item("a"*32)])
    second=product_preferences.materialize_alerts("user-a",[_item("a"*32)])
    assert len(first)==1
    assert len(second)==1
    assert second[0]["attention_item_id"]=="a"*32


def test_new_grouped_alert_supersedes_older_history() -> None:
    product_preferences.materialize_alerts("user-a",[_item("a"*32,materiality="MEDIUM")])
    active=product_preferences.materialize_alerts("user-a",[_item("b"*32,materiality="CRITICAL")])
    history=product_preferences.alerts("user-a",include_history=True)
    assert len(active)==1 and active[0]["materiality"]=="CRITICAL"
    assert {row["status"] for row in history}=={"ACTIVE","SUPERSEDED"}


def test_quiet_and_disabled_categories_do_not_create_alerts() -> None:
    assert product_preferences.materialize_alerts("user-a",[])==[]
    preferences=product_preferences.alert_preferences("user-a")
    preferences["categories"]["thesis_weakening"]=False
    product_preferences.save_alert_preferences("user-a",preferences)
    assert product_preferences.materialize_alerts("user-a",[_item("c"*32)])==[]


def test_alerts_and_preferences_are_owner_scoped() -> None:
    product_preferences.materialize_alerts("user-a",[_item("a"*32)])
    assert product_preferences.alerts("user-b")==[]
    changed=product_preferences.save_alert_preferences("user-b",{"threshold":"CRITICAL_ONLY","categories":{}})
    assert changed["threshold"]=="CRITICAL_ONLY"
    assert product_preferences.alert_preferences("user-a")["threshold"]=="MATERIAL"


def test_personalization_requires_established_patterns(monkeypatch) -> None:
    monkeypatch.setattr(product_preferences.decision_journal,"patterns",lambda _:{"status":"INSUFFICIENT_SAMPLE","patterns":[],"minimum_sample":5,"reviewed_decisions":2})
    value=product_preferences.personalization("user-a")
    assert value["inferred"]==[]
    assert value["reviewed_decisions"]==2


def test_only_accepted_preferences_change_attention_order() -> None:
    items=[_item("a"*32),{**_item("b"*32),"title":"Margin evidence changed","summary":"Margin discipline review"}]
    unchanged=product_preferences.prioritize_attention(items,{"accepted":{}})
    changed=product_preferences.prioritize_attention(items,{"accepted":{"p":{"label":"margin discipline"}}})
    assert unchanged[0]["id"]=="a"*32
    assert changed[0]["id"]=="b"*32
    assert "Accepted decision preference" in changed[0]["ranking_inputs"]["personalization"]


def test_research_personalization_is_disclosed_tie_breaker_not_score_rewrite() -> None:
    payload={"results":[
        {"ticker":"XOM","relative_rank":1,"final_score":81,"sector":"Energy","industry":"Oil","strengths":[],"thesis_risks":[]},
        {"ticker":"MSFT","relative_rank":2,"final_score":70,"sector":"Technology","industry":"Software","strengths":[],"thesis_risks":[]},
    ]}
    result=product_preferences.personalize_research(payload,{"accepted":{"p":{"label":"technology exposure"}}})
    assert result["results"][0]["ticker"]=="MSFT"
    assert result["results"][0]["final_score"]==70
    assert result["personalization"]["applied"] is True
