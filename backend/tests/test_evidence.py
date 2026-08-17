from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import database, evidence
from backend.main import app


NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def observation(
    metric: str, value: float | str, *, evidence_type: evidence.EvidenceType = "FUNDAMENTAL",
    unit: str = "ratio", provider: str = "verified-provider", quality: evidence.EvidenceQuality = "HIGH",
    effective: datetime | None = None,
) -> evidence.EvidenceObservation:
    return evidence._obs(
        entity="ACME", evidence_type=evidence_type, metric=metric, label=metric, value=value,
        value_kind="NUMERIC" if isinstance(value, float) else "CATEGORICAL", unit=unit,
        effective_date=effective or NOW, observed_at=NOW, provider=provider,
        source_reference=f"https://example.test/{provider}", quality=quality, as_of=NOW,
        methodology="test-method-v1",
    )


def test_numeric_change_reports_all_applicable_deltas_without_interpretation() -> None:
    changes, summary = evidence.compare_observations(
        [observation("fundamental.gross_margin", .40)],
        [observation("fundamental.gross_margin", .43)],
    )
    change = changes[0]
    assert change.absolute_change == pytest.approx(.03)
    assert change.percent_change == pytest.approx(7.5)
    assert change.percentage_point_change == pytest.approx(3.0)
    assert change.direction == "UP"
    assert change.materiality == "HIGH"
    assert change.interpretation is None
    assert summary["changed"] == 1


def test_prediction_probability_uses_percentage_points_and_quality_caps_materiality() -> None:
    old = observation("prediction:venue:market", .30, evidence_type="PREDICTION_MARKET", unit="probability")
    new = observation("prediction:venue:market", .48, evidence_type="PREDICTION_MARKET", unit="probability", quality="LOW")
    changes, _ = evidence.compare_observations([old], [new])
    assert changes[0].percentage_point_change == pytest.approx(18)
    assert changes[0].materiality == "MEDIUM"


def test_estimate_and_valuation_thresholds_use_percent_change_when_observations_exist() -> None:
    estimate_changes, _ = evidence.compare_observations(
        [observation("estimate.consensus", 10.0, evidence_type="ESTIMATE", unit="USD")],
        [observation("estimate.consensus", 10.5, evidence_type="ESTIMATE", unit="USD")],
    )
    valuation_changes, _ = evidence.compare_observations(
        [observation("valuation.pe", 20.0, evidence_type="VALUATION", unit="multiple")],
        [observation("valuation.pe", 24.0, evidence_type="VALUATION", unit="multiple")],
    )
    assert estimate_changes[0].materiality == "MEDIUM"
    assert valuation_changes[0].materiality == "HIGH"


def test_missing_baseline_and_missing_current_are_not_neutral_or_unchanged() -> None:
    current_only, _ = evidence.compare_observations([], [observation("fundamental.total_debt", 10.0, unit="USD")])
    baseline_only, _ = evidence.compare_observations([observation("fundamental.cash", 10.0, unit="USD")], [])
    assert current_only[0].status == "MISSING_BASELINE"
    assert current_only[0].materiality == "UNKNOWN"
    assert baseline_only[0].status == "MISSING_CURRENT"
    assert baseline_only[0].materiality == "UNKNOWN"


def test_unchanged_is_counted_but_not_surfaced_by_default() -> None:
    item = observation("fundamental.revenue_yoy", .20)
    changes, summary = evidence.compare_observations([item], [item])
    assert changes == []
    assert summary["unchanged"] == 1


def test_dedup_merges_agreement_and_exposes_disagreement() -> None:
    agreeing = evidence.deduplicate_observations([
        observation("fundamental.cash", 10.0, provider="sec"),
        observation("fundamental.cash", 10.0, provider="filing-xbrl"),
    ])
    assert agreeing[0].availability == "AVAILABLE"
    assert agreeing[0].metadata["supporting_sources"] == ["filing-xbrl", "sec"]
    disagreement = evidence.deduplicate_observations([
        observation("fundamental.cash", 10.0, provider="sec"),
        observation("fundamental.cash", 12.0, provider="filing-xbrl"),
    ])
    assert disagreement[0].availability == "DISAGREEMENT"
    assert disagreement[0].value is None


def test_consensus_and_guidance_are_explicitly_unsupported() -> None:
    coverage = evidence.coverage_for(["ESTIMATE", "GUIDANCE"], [], [], [])
    assert [item.status for item in coverage] == ["UNSUPPORTED", "UNSUPPORTED"]
    assert all("not connected" in item.message for item in coverage)


def test_prediction_market_quality_separates_liquidity_metadata_from_freshness() -> None:
    quality, metadata = evidence.prediction_market_quality(
        {"observed_at": NOW - timedelta(hours=100), "bid": None, "ask": None, "volume": None}, NOW,
    )
    assert quality == "UNAVAILABLE"
    assert metadata["market_quality"] == "UNAVAILABLE"
    assert metadata["freshness_hours"] == 100


def test_news_is_deduplicated_by_content_and_new_items_are_events() -> None:
    rows = [
        {"id": "n1", "provider": "wire", "title": "Acme opens a new plant", "source_url": "https://example.test/n1",
         "published_at": NOW.isoformat(), "fetched_at": NOW.isoformat(), "content_hash": "same", "metadata": {"source": "Wire"}},
        {"id": "n2", "provider": "syndicator", "title": "Acme opens a new plant", "source_url": "https://example.test/n2",
         "published_at": NOW.isoformat(), "fetched_at": NOW.isoformat(), "content_hash": "same", "metadata": {}},
    ]
    current = evidence._news_observations("ACME", rows, NOW)
    assert len(current) == 1
    changes, _ = evidence.compare_observations([], current)
    assert changes[0].status == "ADDED"
    assert changes[0].evidence_type == "NEWS"
    assert changes[0].methodology == "content-hash-news-novelty-v1"


def test_fundamental_growth_aligns_comparable_periods_and_avoids_negative_base_growth() -> None:
    rows = [
        {"period_end": "2026-06-30", "fetched_at": "2026-08-01T00:00:00+00:00", "fiscal_period": "Q2", "fiscal_year": 2026,
         "metrics": {"revenue": 120, "eps_diluted": 2, "free_cash_flow": 20}, "provider": "SEC", "data_quality_score": .9},
        {"period_end": "2026-03-31", "fetched_at": "2026-05-01T00:00:00+00:00", "fiscal_period": "Q1", "fiscal_year": 2026,
         "metrics": {"revenue": 999, "eps_diluted": 999, "free_cash_flow": 999}, "provider": "SEC", "data_quality_score": .9},
        {"period_end": "2025-06-30", "fetched_at": "2025-08-01T00:00:00+00:00", "fiscal_period": "Q2", "fiscal_year": 2025,
         "metrics": {"revenue": 100, "eps_diluted": -1, "free_cash_flow": -5}, "provider": "SEC", "data_quality_score": .9},
    ]
    observations = evidence._fundamental_observations("ACME", rows, NOW)
    by_metric = {item.metric: item for item in observations}
    assert by_metric["fundamental.revenue_yoy"].value == pytest.approx(.20)
    assert "fundamental.eps_yoy" not in by_metric
    assert "fundamental.free_cash_flow_yoy" not in by_metric


def test_sqlite_thesis_version_is_selected_as_default_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(database, "DATABASE_URL", "")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "evidence.sqlite3")
    database.initialize()
    with database.sqlite_connection() as conn:
        conn.execute(
            """INSERT INTO investment_theses(id,user_id,ticker,summary,base_case,bull_case,bear_case,investment_horizon,
            status,source_context_json,current_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("t1", "u1", "ACME", "summary", "base", "bull", "bear", "3 years", "ACTIVE", "{}", 1, NOW.isoformat(), NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO thesis_versions(id,thesis_id,user_id,version_number,snapshot_json,created_at) VALUES (?,?,?,?,?,?)",
            ("v1", "t1", "u1", 1, "{}", NOW.isoformat()),
        )
    baseline = evidence.select_baseline("u1", "ACME", "LAST_THESIS_REVIEW", current_as_of=NOW + timedelta(days=1))
    assert baseline.resolved == "LAST_THESIS_REVIEW"
    assert baseline.reference_id == "v1"
    assert baseline.as_of == NOW


def test_typed_change_api_reports_unsupported_coverage_and_validates_filters() -> None:
    with TestClient(app) as client:
        response = client.get("/api/evidence/securities/ACME/changes?baseline=SEVEN_DAYS&evidence_types=ESTIMATE,GUIDANCE")
        assert response.status_code == 200
        payload = response.json()
        assert payload["calculation_version"] == "evidence-change-v1"
        assert [item["status"] for item in payload["coverage"]] == ["UNSUPPORTED", "UNSUPPORTED"]
        invalid = client.get("/api/evidence/securities/ACME/changes?evidence_types=INVENTED")
        assert invalid.status_code == 422


def test_explicit_research_review_creates_a_user_owned_baseline() -> None:
    with TestClient(app) as client:
        created = client.post("/api/evidence/securities/ACME/reviews", json={})
        assert created.status_code == 201
        assert created.json()["created"] is True
        response = client.get("/api/evidence/securities/ACME/changes?baseline=LAST_RESEARCH_REVIEW")
        assert response.status_code == 200
        assert response.json()["baseline"]["resolved"] == "LAST_RESEARCH_REVIEW"
