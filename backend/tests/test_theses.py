from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import chat, theses
from backend.main import app
from backend.models import InvestmentDecisionPayload, InvestmentThesisPayload


USER_A = "00000000-0000-4000-8000-00000000000a"
USER_B = "00000000-0000-4000-8000-00000000000b"


def payload(ticker: str = "AAPL") -> InvestmentThesisPayload:
    return InvestmentThesisPayload.model_validate({
        "ticker": ticker,
        "summary": "Services growth and customer retention support a durable base case.",
        "base_case": "The stored operating evidence persists.",
        "bull_case": "Margins and recurring revenue improve.",
        "bear_case": "Demand and margins weaken.",
        "review_date": "2026-12-15",
        "status": "ACTIVE",
        "assumptions": [{
            "description": "Services growth remains supportive", "category": "GROWTH",
            "importance": "HIGH", "status": "UNTESTED",
            "evidence_mapping": {"source": "stored research"},
        }],
        "factors": [
            {"factor_type": "CATALYST", "description": "Recurring revenue accelerates"},
            {"factor_type": "RISK", "description": "Demand weakens"},
            {"factor_type": "BREAKER", "description": "The recurring revenue base contracts for a sustained period"},
        ],
    })


def test_thesis_versions_only_meaningful_edits_and_is_owner_isolated() -> None:
    created = theses.create_thesis(USER_A, payload())
    assert created["current_version"] == 1
    assert len(created["thesis_breakers"]) == 1
    assert theses.active_thesis(USER_B, "AAPL") is None
    with pytest.raises(KeyError):
        theses.get_thesis(USER_B, created["id"])

    same = payload()
    unchanged = theses.update_thesis(USER_A, created["id"], same)
    assert unchanged["current_version"] == 1
    assert len(theses.thesis_history(USER_A, created["id"])) == 1

    same.summary = "A revised summary based on newly reviewed evidence."
    same.change_note = "Quarterly evidence review"
    revised = theses.update_thesis(USER_A, created["id"], same)
    history = theses.thesis_history(USER_A, created["id"])
    assert revised["current_version"] == 2
    assert [item["version_number"] for item in history] == [2, 1]
    assert history[0]["change_note"] == "Quarterly evidence review"


def test_decision_history_is_append_only_and_captures_missing_price_explicitly() -> None:
    thesis = theses.create_thesis(USER_A, payload("MSFT"))
    watch = theses.record_decision(USER_A, InvestmentDecisionPayload(
        ticker="MSFT", thesis_id=thesis["id"], decision_type="WATCH", notes="Wait for more evidence",
    ))
    buy = theses.record_decision(USER_A, InvestmentDecisionPayload(
        ticker="MSFT", thesis_id=thesis["id"], decision_type="BUY", user_confidence=4,
    ))
    decisions = theses.list_decisions(USER_A, "MSFT")
    assert {item["id"] for item in decisions} == {watch["id"], buy["id"]}
    assert all(item["thesis_version"] == 1 for item in decisions)
    assert all(item["price_at_decision"] is None for item in decisions)
    assert theses.list_decisions(USER_B, "MSFT") == []


def test_holding_or_watchlist_can_exist_without_thesis() -> None:
    result = theses.workspace(USER_A, [{"ticker": "NVDA"}], ["GOOG", "NVDA"])
    assert result["active_theses"] == []
    assert result["recent_decisions"] == []
    assert result["needs_thesis"] == [
        {"ticker": "GOOG", "source": "watchlist"},
        {"ticker": "NVDA", "source": "holding"},
    ]


def test_api_supports_create_edit_close_and_multiple_decisions() -> None:
    with TestClient(app) as client:
        created = client.post("/api/theses", json=payload("COST").model_dump(mode="json"))
        assert created.status_code == 201
        thesis = created.json()
        duplicate = client.post("/api/theses", json=payload("COST").model_dump(mode="json"))
        assert duplicate.status_code == 409

        body = payload("COST").model_dump(mode="json")
        body["status"] = "CLOSED"
        closed = client.put(f"/api/theses/{thesis['id']}", json=body)
        assert closed.status_code == 200
        assert closed.json()["status"] == "CLOSED"
        replacement = client.post("/api/theses", json=payload("COST").model_dump(mode="json"))
        assert replacement.status_code == 201

        for decision in ("WATCH", "HOLD"):
            response = client.post("/api/investment-decisions", json={"ticker": "COST", "decision_type": decision})
            assert response.status_code == 201
        assert len(client.get("/api/investment-decisions?ticker=COST").json()) == 2


def test_monitorable_fields_must_be_complete() -> None:
    with pytest.raises(ValueError, match="metric, operator, and target_value"):
        InvestmentThesisPayload.model_validate({
            "ticker": "AAPL", "summary": "Incomplete monitorable assumption",
            "assumptions": [{"description": "Growth stays high", "metric": "revenue_growth"}],
        })


def test_structured_child_endpoints_version_add_edit_and_remove() -> None:
    base = payload("ADBE")
    base.assumptions = []
    base.factors = []
    with TestClient(app) as client:
        thesis = client.post("/api/theses", json=base.model_dump(mode="json")).json()
        added = client.post(f"/api/theses/{thesis['id']}/assumptions", json={
            "description": "Subscription retention remains durable", "category": "DEMAND",
            "importance": "CRITICAL", "status": "UNTESTED",
        })
        assert added.status_code == 201
        assumption = added.json()
        edited = client.put(f"/api/theses/{thesis['id']}/assumptions/{assumption['id']}", json={
            "description": "Subscription retention remains above the user-defined threshold",
            "category": "DEMAND", "importance": "CRITICAL", "status": "SUPPORTED",
        })
        assert edited.status_code == 200
        removed = client.delete(f"/api/theses/{thesis['id']}/assumptions/{assumption['id']}")
        assert removed.status_code == 200
        assert removed.json()["assumptions"] == []
        assert removed.json()["current_version"] == 4

        factor = client.post(f"/api/theses/{thesis['id']}/factors", json={
            "factor_type": "BREAKER", "description": "Subscription revenue contracts materially",
        })
        assert factor.status_code == 201
        deleted = client.delete(f"/api/theses/{thesis['id']}/factors/{factor.json()['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["factors"] == []
        assert len(client.get(f"/api/theses/{thesis['id']}/history").json()) == 6


def test_evidence_draft_falls_back_without_saving_or_fabricating_missing_data(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = theses.evidence_draft("ZZZZ", {
        "ticker": "ZZZZ", "company": "Example Co", "freshness": {},
        "field_coverage": {"missing": ["revenue_growth", "net_margin"]},
        "fundamental_trend": {"revenue_growth": None, "net_margin": None},
        "catalysts": [], "thesis_risks": [],
    })
    assert result["saved"] is False
    assert result["draft"]["assumptions"] == []
    assert result["draft"]["source_context"]["missing_fields"] == ["revenue_growth", "net_margin"]
    assert "AI synthesis was unavailable" in result["warning"]


def test_evidence_draft_populates_all_cases_from_stored_evidence(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = theses.evidence_draft("AMD", {
        "ticker": "AMD", "company": "Advanced Micro Devices", "freshness": {},
        "field_coverage": {"missing": []},
        "fundamental_trend": {"revenue_growth": 0.12, "net_margin": 0.08},
        "strengths": [{"label": "Revenue growth"}],
        "weaknesses": [{"label": "Margin pressure"}],
        "catalysts": [{"title": "Data-center demand", "source_url": None}],
        "thesis_risks": ["competitive_pressure"],
        "what_would_change_the_view": "Sustained market-share losses",
    })
    draft = result["draft"]
    assert "continues on roughly its current operating path" in draft["base_case"]
    assert "Revenue growth remains supportive" in draft["base_case"]
    assert "performs better than the current operating path" in draft["bull_case"]
    assert "Data-center demand" in draft["bull_case"]
    assert "performs worse than the current operating path" in draft["bear_case"]
    assert "competitive pressure" in draft["bear_case"]
    assert "Sustained market-share losses" in draft["bear_case"]
    assert len({draft["base_case"], draft["bull_case"], draft["bear_case"]}) == 3
    for case in (draft["base_case"], draft["bull_case"], draft["bear_case"]):
        assert len(case.split("\n\n")) == 3


def test_ai_prose_draft_is_restricted_to_typed_editable_fields(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(chat, "_gemini_request", lambda *args, **kwargs: {
        "candidates": [{"content": {"parts": [{"text": '{"summary":"Evidence summary","base_case":"Base evidence","bull_case":"Upside evidence","bear_case":"Downside evidence"}'}]}, "finishReason": "STOP"}],
    })
    result, model = chat.draft_thesis_prose({"ticker": "AAPL", "company": "Apple"}, {
        "summary": "Starter summary", "base_case": "Starter base", "bull_case": "Starter bull", "bear_case": "Starter bear",
    })
    assert set(result) == {"summary", "base_case", "bull_case", "bear_case"}
    assert result["summary"] == "Evidence summary"
    assert model
