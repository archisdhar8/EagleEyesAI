from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import evidence, theses, thesis_monitor
from backend import main
from backend.main import app
from backend.models import InvestmentThesisPayload, ThesisAssumptionPayload, ThesisFactorPayload


NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
USER = "00000000-0000-0000-0000-000000000001"


def observation(metric: str, value: float, *, evidence_type: evidence.EvidenceType = "FUNDAMENTAL", quality: evidence.EvidenceQuality = "HIGH", effective: datetime = NOW) -> evidence.EvidenceObservation:
    return evidence._obs(entity="ACME", evidence_type=evidence_type, metric=metric, label=metric, value=value,
        value_kind="NUMERIC", unit="probability" if evidence_type == "PREDICTION_MARKET" else "ratio",
        effective_date=effective, observed_at=effective, provider="verified", source_reference="https://example.test/source",
        quality=quality, as_of=NOW, methodology="fixture-v1")


def change(metric: str, before: float | None, after: float | None, *, evidence_type: evidence.EvidenceType = "FUNDAMENTAL", direction: evidence.Direction = "UP", quality: evidence.EvidenceQuality = "HIGH", source: str = "verified", reference: str = "https://example.test/source") -> evidence.EvidenceChange:
    return evidence.EvidenceChange(evidence_type=evidence_type, metric=metric, label=metric, status="CHANGED",
        previous_value=before, current_value=after, unit="probability" if evidence_type == "PREDICTION_MARKET" else "ratio",
        absolute_change=None if before is None or after is None else after-before,
        percent_change=None if not before or after is None else (after-before)/abs(before)*100,
        percentage_point_change=None if before is None or after is None else (after-before)*100,
        direction=direction, materiality="HIGH", previous_as_of=NOW-timedelta(days=90), current_as_of=NOW,
        source=source, sources=[source], source_references=[reference], freshness="CURRENT", evidence_quality=quality,
        interpretation=None, methodology="fixture-v1", metadata={})


def change_set(*items: evidence.EvidenceChange) -> evidence.EvidenceChangeSet:
    baseline = evidence.BaselineSelection(requested="LAST_THESIS_REVIEW", resolved="LAST_THESIS_REVIEW",
        as_of=NOW-timedelta(days=90), reference_id="baseline", source="fixture")
    return evidence.EvidenceChangeSet(entity="ACME", baseline=baseline, baseline_as_of=baseline.as_of,
        current_as_of=NOW, changes=list(items), coverage=[], summary={}, generated_at=NOW)


def structured_assumption(operator: str = ">=", target: float = .70, importance: str = "HIGH") -> dict:
    return {"id":"a1","description":"Gross margin remains above 70%.","category":"MARGIN","importance":importance,
            "metric":"gross_margin","operator":operator,"target_value":target,"unit":"ratio","evidence_mapping":{}}


@pytest.mark.parametrize(("operator","value","expected"), [(">",3,True),(">=",2,True),("<",1,True),("<=",1,True),("=",2,True),("!=",1,True)])
def test_deterministic_threshold_operators(operator: str, value: float, expected: bool) -> None:
    assert thesis_monitor.evaluate_condition(value, operator, 2) is expected


def test_threshold_warning_is_near_but_not_triggered() -> None:
    assert thesis_monitor.evaluate_condition(.703, "<", .70) is False
    assert thesis_monitor.threshold_warning(.703, "<", .70) is True
    assert thesis_monitor.threshold_warning(.80, "<", .70) is False


def test_structured_assumption_supports_weakens_and_contradicts() -> None:
    item = structured_assumption()
    supported = thesis_monitor._structured_assumption(item, change_set(change("fundamental.gross_margin", .68, .72)), [observation("fundamental.gross_margin", .72)])
    weakened = thesis_monitor._structured_assumption(item, change_set(change("fundamental.gross_margin", .74, .71, direction="DOWN")), [observation("fundamental.gross_margin", .71)])
    contradicted = thesis_monitor._structured_assumption(item, change_set(change("fundamental.gross_margin", .71, .694, direction="DOWN")), [observation("fundamental.gross_margin", .694)])
    assert (supported.state, weakened.state, contradicted.state) == ("SUPPORTS", "WEAKENS", "CONTRADICTS")
    assert contradicted.condition_met is False


def test_qualitative_retrieval_excludes_unrelated_macro_change_and_reports_insufficient() -> None:
    item = {"id":"a2","description":"AI infrastructure demand remains strong.","category":"DEMAND","importance":"HIGH","evidence_mapping":{}}
    result = thesis_monitor._qualitative_item(item, change_set(change("macro.DCOILWTICO", 70, 74, evidence_type="MACRO")), None)
    assert result.state == "INSUFFICIENT_EVIDENCE"
    assert result.evidence == []
    assert result.unrelated_evidence_count == 1


def test_qualitative_classifier_preserves_conflicting_evidence_items() -> None:
    item = {"id":"a2","description":"AI demand remains strong.","category":"DEMAND","importance":"HIGH","evidence_mapping":{}}
    changes = change_set(
        change("fundamental.revenue_yoy", .12, .20, reference="https://example.test/earnings"),
        change("prediction:venue:restrictions", .18, .41, evidence_type="PREDICTION_MARKET", reference="https://example.test/market"),
    )
    classifier = lambda _item, _evidence: ("WEAKENS", "Verified evidence is mixed.", "fixture-model", {"E1":"SUPPORTS","E2":"WEAKENS"})
    result = thesis_monitor._qualitative_item(item, changes, classifier)
    assert result.state == "WEAKENS"
    assert result.evidence_agreement == "CONFLICTING"
    assert {item.relationship for item in result.evidence} == {"SUPPORTS", "WEAKENS"}


def test_duplicate_source_does_not_inflate_agreement() -> None:
    base = thesis_monitor._monitoring_evidence(change("fundamental.revenue_yoy", .1, .2, reference="https://event.test/earnings"), "RELEVANT", "SUPPORTS")
    duplicate = thesis_monitor._monitoring_evidence(change("news:earnings", .1, .2, evidence_type="NEWS", reference="https://event.test/earnings"), "RELEVANT", "WEAKENS")
    assert base.independence_group == duplicate.independence_group
    assert thesis_monitor.evidence_agreement([base, duplicate]) == "CONSISTENT"


def test_multi_period_breaker_requires_every_requested_period(monkeypatch: pytest.MonkeyPatch) -> None:
    breaker = {"id":"b1","factor_type":"BREAKER","description":"Margin below 70% for two quarters","metric":"gross_margin","operator":"<","threshold":.70,"period_requirement":"2 consecutive quarters","evidence_mapping":{}}
    monkeypatch.setattr(thesis_monitor, "_history_for_metric", lambda *_args: [observation("fundamental.gross_margin", .693), observation("fundamental.gross_margin", .698, effective=NOW-timedelta(days=90))])
    result = thesis_monitor._factor_result(breaker,"ACME",change_set(),[],{},None)
    assert result.state == "TRIGGERED"
    assert result.periods_evaluated == 2
    monkeypatch.setattr(thesis_monitor, "_history_for_metric", lambda *_args: [observation("fundamental.gross_margin", .80), observation("fundamental.gross_margin", .698, effective=NOW-timedelta(days=90))])
    assert thesis_monitor._factor_result(breaker,"ACME",change_set(),[],{},None).state == "NOT_TRIGGERED"


def test_breaker_warning_and_low_quality_prediction_market() -> None:
    breaker = {"id":"b1","factor_type":"BREAKER","description":"Restriction probability above 40%","metric":"prediction:venue:restriction","operator":">","threshold":.40,"period_requirement":"1 period","evidence_mapping":{}}
    original = thesis_monitor._history_for_metric
    try:
        thesis_monitor._history_for_metric = lambda *_args: [observation("prediction:venue:restriction", .41, evidence_type="PREDICTION_MARKET", quality="LOW")]
        result = thesis_monitor._factor_result(breaker,"ACME",change_set(change("prediction:venue:restriction",.18,.41,evidence_type="PREDICTION_MARKET",quality="LOW")),[],{},None)
    finally:
        thesis_monitor._history_for_metric = original
    assert result.state == "WARNING"
    assert result.evidence[0].current_value == .41
    assert result.evidence[0].metadata == {}


def test_risk_and_catalyst_states_are_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thesis_monitor, "_history_for_metric", lambda *_args: [observation("fundamental.total_debt", 4.0)])
    risk = {"id":"r1","factor_type":"RISK","description":"Debt exceeds threshold","metric":"total_debt","operator":">","threshold":3.0,"period_requirement":None,"evidence_mapping":{}}
    catalyst = {"id":"c1","factor_type":"CATALYST","description":"Debt falls below target","metric":"total_debt","operator":"<","threshold":5.0,"period_requirement":None,"evidence_mapping":{}}
    assert thesis_monitor._factor_result(risk,"ACME",change_set(),[],{},None).state == "MATERIALIZED"
    assert thesis_monitor._factor_result(catalyst,"ACME",change_set(),[],{},None).state == "REALIZED"


def test_overall_status_respects_importance_and_breakers() -> None:
    base = thesis_monitor._structured_assumption(structured_assumption(importance="HIGH"), change_set(), [observation("fundamental.gross_margin", .69)])
    assert thesis_monitor.overall_status([base], [], [])[0] == "MATERIAL_REVIEW_REQUIRED"
    breaker = thesis_monitor.FactorMonitoringResult(factor_id="b",factor_type="BREAKER",description="breaker",state="TRIGGERED",deterministic=True,evidence_agreement="INSUFFICIENT",explanation="triggered")
    assert thesis_monitor.overall_status([], [breaker], [])[0] == "THESIS_BREAKER_TRIGGERED"


def test_prediction_point_change_and_missing_provider_remain_explicit() -> None:
    trace = thesis_monitor._monitoring_evidence(change("prediction:venue:cuts",.34,.61,evidence_type="PREDICTION_MARKET"),"RELEVANT","SUPPORTS")
    assert trace.previous_value == .34 and trace.current_value == .61
    assert trace.percentage_point_change == pytest.approx(27)
    assert trace.evidence_quality == "HIGH"
    result = thesis_monitor._structured_assumption(structured_assumption(), change_set(), [])
    assert result.state == "INSUFFICIENT_EVIDENCE"
    assert result.data_coverage == "UNAVAILABLE"


def create_monitored_thesis() -> dict:
    return theses.create_thesis(USER, InvestmentThesisPayload(ticker="ACME",summary="A monitored thesis",status="ACTIVE",
        assumptions=[ThesisAssumptionPayload(description="Gross margin remains above 70%",category="MARGIN",importance="HIGH",metric="gross_margin",operator=">=",target_value=.70,unit="ratio")],
        factors=[ThesisFactorPayload(factor_type="BREAKER",description="Gross margin below 70% for two quarters",metric="gross_margin",operator="<",threshold=.70,period_requirement="2 consecutive quarters",unit="ratio")]))


def test_end_to_end_monitor_review_history_and_new_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    thesis = create_monitored_thesis()
    monkeypatch.setattr(evidence,"get_changes",lambda *_args,**_kwargs: change_set(change("fundamental.gross_margin",.724,.694,direction="DOWN")))
    monkeypatch.setattr(evidence,"load_history_bundle",lambda *_args,**_kwargs: {})
    monkeypatch.setattr(evidence,"observations_from_bundle",lambda *_args,**_kwargs: [observation("fundamental.gross_margin",.694)])
    monkeypatch.setattr(thesis_monitor,"_history_for_metric",lambda *_args: [observation("fundamental.gross_margin",.694),observation("fundamental.gross_margin",.698,effective=NOW-timedelta(days=90))])
    captured = []
    monkeypatch.setattr(evidence,"capture_snapshot",lambda *args,**kwargs: captured.append((args,kwargs)) or {"created":True})
    result = thesis_monitor.evaluate_thesis(USER,thesis["id"],current_as_of=NOW,use_cache=False)
    assert result.overall_status == "THESIS_BREAKER_TRIGGERED"
    reviewed = thesis_monitor.mark_reviewed(USER,thesis["id"],result)
    history = thesis_monitor.review_history(USER,thesis["id"])
    assert history[0]["overall_status"] == "THESIS_BREAKER_TRIGGERED"
    assert history[0]["monitoring_result"]["assumption_results"][0]["state"] == "CONTRADICTS"
    assert captured[0][0][2:4] == ("LAST_THESIS_REVIEW", reviewed["id"])
    assert abs(captured[0][0][4] - datetime.fromisoformat(reviewed["reviewed_at"])) < timedelta(seconds=1)
    baseline = evidence.select_baseline(USER,"ACME","LAST_THESIS_REVIEW",current_as_of=NOW+timedelta(days=1))
    assert baseline.reference_id == reviewed["id"]
    assert baseline.source == "latest explicit thesis review"


def test_normal_thesis_edit_preserves_explicit_review_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    thesis = create_monitored_thesis()
    calls = []
    monkeypatch.setattr(theses,"_capture_boundary",lambda *args,**kwargs: calls.append(args))
    payload = InvestmentThesisPayload.model_validate({**thesis,"summary":"Edited reasoning","change_note":"clarified wording"})
    theses.update_thesis(USER,thesis["id"],payload)
    assert calls == []


def test_monitor_api_enforces_user_isolation() -> None:
    thesis = create_monitored_thesis()
    other = theses.create_thesis("00000000-0000-0000-0000-000000000002", InvestmentThesisPayload(ticker="PRIVATE",summary="Other user's thesis",status="ACTIVE"))
    with TestClient(app) as client:
        missing = client.get("/api/theses/00000000-0000-0000-0000-000000000099/monitor?include_ai=false")
        assert missing.status_code == 404
        isolated = client.get(f"/api/theses/{other['id']}/monitor?include_ai=false")
        assert isolated.status_code == 404
        history = client.get(f"/api/theses/{thesis['id']}/reviews")
        assert history.status_code == 200


def test_ask_eagleeyes_uses_structured_monitor_tool_output(monkeypatch: pytest.MonkeyPatch) -> None:
    result = thesis_monitor.ThesisMonitoringResult(thesis_id="t1",thesis_version=1,ticker="ACME",
        baseline_review_at=NOW-timedelta(days=30),evaluated_at=NOW,overall_status="STABLE",requires_review=False,
        assumption_results=[],risk_results=[],catalyst_results=[],thesis_breaker_results=[],evidence_coverage=[],
        freshness="HIGH",evidence_quality="HIGH",counts={"SUPPORTS":1},created_at=NOW)
    monkeypatch.setattr(main,"_resolve_chat_tickers",lambda _question:["ACME"])
    monkeypatch.setattr(theses,"active_thesis",lambda _user,_ticker:{"id":"t1","ticker":"ACME"})
    monkeypatch.setattr(thesis_monitor,"evaluate_thesis",lambda *_args,**_kwargs:result)
    tools, grounded = main._thesis_monitor_chat_tools(USER,"Has anything changed in my ACME thesis?")
    assert tools[0]["tool_name"] == "thesis_monitor"
    assert tools[0]["summary"]["overall_status"] == "STABLE"
    assert grounded[0]["data"]["counts"]["SUPPORTS"] == 1
