from datetime import datetime, timedelta, timezone

import pytest

from backend import attention, earnings_intelligence as earnings, portfolio_intelligence as portfolio

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def periods(ticker="MSFT"):
    return [
        {"ticker": ticker, "period_end": "2026-06-30", "fiscal_period": "Q2", "fiscal_year": 2026, "fetched_at": NOW.isoformat(), "provider": "verified-provider", "source_url": "https://example.test/filing", "data_quality_score": .9,
         "metrics": {"revenue": 120, "eps_diluted": 3, "gross_profit": 72, "operating_income": 48, "free_cash_flow": 30,
                     "consensus": {"revenue": 100, "eps": 2.5},
                     "previous_guidance": {"revenue": {"low": 100, "high": 102}}, "guidance": {"revenue": {"low": 103, "high": 105}},
                     "estimate_revisions": {"fy27_eps": {"before": 12.1, "after": 12.58, "window_hours": 48, "up": 18, "down": 3, "provider": "verified-provider"}}}},
        {"ticker": ticker, "period_end": "2026-03-31", "fiscal_period": "Q1", "fiscal_year": 2026, "fetched_at": "2026-05-01T00:00:00+00:00", "metrics": {"revenue": 110, "eps_diluted": 2.7, "gross_profit": 70, "operating_income": 45, "free_cash_flow": 25}},
        {"ticker": ticker, "period_end": "2025-06-30", "fiscal_period": "Q2", "fiscal_year": 2025, "fetched_at": "2025-08-01T00:00:00+00:00", "metrics": {"revenue": 100, "eps_diluted": 2, "gross_profit": 65, "operating_income": 40, "free_cash_flow": 20}},
    ]


def test_actual_vs_consensus_is_deterministic():
    result = earnings.build_earnings_intelligence("MSFT", periods(), now=NOW)
    assert result["actual_vs_expectations"]["revenue"]["surprise_percent"] == pytest.approx(.2)
    assert result["actual_vs_expectations"]["eps"]["surprise_percent"] == pytest.approx(.2)


def test_guidance_midpoint_and_margin_basis_points():
    result = earnings.build_earnings_intelligence("MSFT", periods(), now=NOW)
    assert round(result["guidance_changes"][0]["midpoint_change_percent"], 6) == round(104 / 101 - 1, 6)
    gross = next(row for row in result["changes"] if row["label"] == "Gross margin")
    assert round(gross["change_basis_points"], 2) == round((72 / 120 - 70 / 110) * 10000, 2)


def test_post_earnings_revision_window_is_preserved():
    revision = earnings.build_earnings_intelligence("MSFT", periods(), now=NOW)["estimate_revisions"][0]
    assert round(revision["change_percent"], 6) == round(12.58 / 12.1 - 1, 6)
    assert revision["window_hours"] == 48 and revision["up"] == 18 and revision["down"] == 3


def test_fiscal_period_alignment_uses_matching_prior_year():
    revenue = next(row for row in earnings.build_earnings_intelligence("MSFT", periods(), now=NOW)["changes"] if row["label"] == "Revenue")
    assert revenue["prior_year_period"] == 100
    assert revenue["period_alignment"] == "same fiscal period"


def test_missing_consensus_guidance_and_transcript_are_explicit():
    rows = periods(); rows[0]["metrics"] = {"revenue": 120}
    result = earnings.build_earnings_intelligence("MSFT", rows, now=NOW)
    assert result["coverage"]["consensus"] == "UNAVAILABLE"
    assert result["coverage"]["guidance"] == "UNAVAILABLE"
    assert result["coverage"]["transcript"] == "UNAVAILABLE"


def test_thesis_assumption_mapping_reuses_monitor_output():
    monitor = {"overall_status": "WEAKENING", "assumption_results": [{"assumption_id": "a1", "description": "Margin above 70%", "state": "CONTRADICTS", "importance": "HIGH", "explanation": "Below threshold", "evidence": [{"evidence_type": "FUNDAMENTAL"}]}]}
    result = earnings.build_earnings_intelligence("MSFT", periods(), thesis={"id": "t1"}, monitor=monitor, now=NOW)
    assert result["thesis_impact"]["assumptions"][0]["state"] == "CONTRADICTS"


def test_transcript_evidence_is_selective_and_bounded():
    chunks = [{"content": f"Relevant margin discussion {index}", "chunk_index": index} for index in range(12)]
    result = earnings.build_earnings_intelligence("MSFT", periods(), transcript_chunks=chunks, now=NOW)
    assert result["coverage"]["transcript"] == "AVAILABLE"
    assert len(result["transcript_evidence"]) == 8


def test_concentration_and_weighted_fundamental_coverage():
    diagnostics = {"performance_label": "Hypothetical one-year return using current holdings and weights", "sector_exposure": [], "industry_exposure": [], "marginal_risk": {"status": "ready", "positions": []}}
    result = portfolio.build_portfolio_intelligence(holdings=[{"ticker": "MSFT", "weight": .8}, {"ticker": "XOM", "weight": .2}], security_data={"securities": [{"ticker": "MSFT", "sector": "Technology"}], "fundamentals": periods(), "prices": []}, diagnostics=diagnostics, theses=[], monitor_results=[], forecasting={"markets": []}, events=[])
    assert round(result["concentration"]["effective_holdings"], 6) == round(1 / (.8**2 + .2**2), 6)
    assert result["fundamental_health"]["coverage"] == .8
    assert result["performance_methodology"]["type"] == "CURRENT_WEIGHT_HYPOTHETICAL"


def test_common_factor_and_prediction_market_exposure_are_reused():
    market = {"event_key": "INTEREST_RATES", "affected_holdings": ["MSFT"], "title": "Rates", "probability": {"probability": .7}}
    result = portfolio.build_portfolio_intelligence(holdings=[{"ticker": "MSFT", "weight": 1}], security_data={"securities": [{"ticker": "MSFT", "sector": "Technology", "industry": "Software"}], "fundamentals": periods(), "prices": []}, diagnostics={"performance_label": "Hypothetical", "sector_exposure": [], "industry_exposure": [], "marginal_risk": {}}, theses=[], monitor_results=[], forecasting={"markets": [market]}, events=[])
    assert any(row["factor"] == "INTEREST_RATES" for row in result["economic_dependencies"])
    assert any(row["factor"] == "AI_INFRASTRUCTURE_DEMAND" for row in result["economic_dependencies"])
    assert result["prediction_market_exposure"] == [market]


def test_upcoming_event_concentration_uses_saved_weights():
    event = {"id": "e1", "title": "MSFT earnings", "starts_at": (NOW + timedelta(days=5)).isoformat(), "tickers": ["MSFT"]}
    result = portfolio.build_portfolio_intelligence(holdings=[{"ticker": "MSFT", "weight": .6}, {"ticker": "XOM", "weight": .4}], security_data={"securities": [], "fundamentals": [], "prices": []}, diagnostics={"performance_label": "Hypothetical", "sector_exposure": [], "industry_exposure": [], "marginal_risk": {}}, theses=[], monitor_results=[], forecasting={"markets": []}, events=[event])
    assert result["upcoming_events"][0]["portfolio_weight"] == .6


def test_recent_earnings_feeds_today_and_groups_with_thesis():
    report = earnings.build_earnings_intelligence("MSFT", periods(), thesis={"id": "t1"}, monitor={"overall_status": "WEAKENING", "assumption_results": []}, now=NOW)
    result = attention.compose_attention(holdings=[{"ticker": "MSFT", "weight": 1}], thesis_workspace={"active_theses": [{"id": "t1", "ticker": "MSFT"}]}, monitoring_results=[], forecasting_payload={"markets": []}, events=[], diagnostics={}, research=[], watchlist=[], movements=[], states={}, earnings=[report], now=NOW)
    assert result["items"][0]["type"] == "MATERIAL_EARNINGS_CHANGE"
    assert result["items"][0]["linked_thesis_id"] == "t1"
