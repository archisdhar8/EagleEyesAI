from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import database, main, phase6_domains, read_models
from backend.analytical_contract import AnalysisStatus


NOW = datetime.now(timezone.utc)


def company_fixture(ticker: str = "MSFT", *, news: bool = True, asset_type: str = "equity",
                    score: float = 78.0) -> tuple[dict, dict]:
    prices = [{"ticker": ticker, "date": (NOW - timedelta(days=260-index)).isoformat(),
               "close": 100 + index, "provider": "test"} for index in range(261)]
    fundamentals = [
        {"ticker": ticker, "period_end": "2026-06-30", "fiscal_period": "Q2", "fiscal_year": 2026,
         "metrics": {"revenue": 120, "net_income": 30, "free_cash_flow": 25, "total_assets": 300,
                     "total_debt": 60, "eps_diluted": 3}, "provider": "sec"},
        {"ticker": ticker, "period_end": "2025-06-30", "fiscal_period": "Q2", "fiscal_year": 2025,
         "metrics": {"revenue": 100, "net_income": 20, "free_cash_flow": 18, "total_assets": 280,
                     "total_debt": 65, "eps_diluted": 2.4}, "provider": "sec"},
        {"ticker": ticker, "period_end": "2024-06-30", "fiscal_period": "Q2", "fiscal_year": 2024,
         "metrics": {"revenue": 90, "net_income": 16, "free_cash_flow": 14, "total_assets": 260,
                     "total_debt": 70, "eps_diluted": 2.0}, "provider": "sec"},
    ]
    news_rows = ([{"ticker": ticker, "published_at": NOW.isoformat(), "title": "Stored update",
                   "metadata": {"sentiment_score": .2}, "provider": "test"}] if news else [])
    stored = {"securities": [{"ticker": ticker, "company_name": ticker, "asset_type": asset_type,
                               "sector": "Technology", "industry": "Software", "updated_at": NOW.isoformat()}],
              "fundamentals": fundamentals, "prices": prices, "news": news_rows, "company_markets": []}
    research = {
        "ticker": ticker, "company": ticker, "sector": "Technology", "industry": "Software",
        "price": 360, "price_as_of": NOW.isoformat(), "price_change_1y": .35,
        "fundamentals_as_of": "2026-06-30", "revenue_growth": .2, "net_margin": .25,
        "final_score": score, "growth_rating": 80, "fundamental_score": 82, "valuation_score": 55,
        "industry_score": 75, "technical_score": 72, "news_score": 60,
        "valuation_evidence": {"score": 55, "method": "stored multiples"},
        "market_statistics": {"return_1m": .04, "return_3m": .12, "return_1y": .35,
                              "annualized_return": .3, "max_drawdown": -.18, "rsi_14": 58},
        "fundamental_statistics": {"revenue": 120, "net_income": 30, "free_cash_flow": 25,
                                   "total_assets": 300, "total_debt": 60, "debt_to_assets": .2},
        "news_sentiment": {"label": "positive", "article_count": len(news_rows)},
        "latest_news": news_rows[0] if news_rows else None,
    }
    return stored, research


def macro_rows(*, include_labor: bool = True) -> list[dict]:
    values = {
        "FEDFUNDS": [5.25, 5.0], "DGS10": [4.4, 4.1], "T10Y2Y": [-.2, .1],
        "CPIAUCSL": [310, 311], "PCEPI": [124, 124.3], "INDPRO": [102, 101],
        "RSAFS": [700, 705], "PCE": [19000, 19100], "BAMLH0A0HYM2": [3.5, 4.1],
    }
    if include_labor:
        values.update({"UNRATE": [4.1, 4.4], "PAYEMS": [160000, 160080], "ICSA": [220, 230]})
    rows = []
    for series, pair in values.items():
        rows.extend([{"series_id": series, "date": (NOW - timedelta(days=30-index * 30)).isoformat(),
                      "value": value, "provider": "FRED"} for index, value in enumerate(pair)])
    return rows


def market_rows(*, breadth: bool = True) -> list[dict]:
    symbols = list(phase6_domains.MARKET_INDEXES)
    if breadth:
        symbols += list(phase6_domains.MARKET_SECTORS)
    rows = []
    for offset, ticker in enumerate(symbols):
        for index in range(90):
            rows.append({"ticker": ticker, "date": (NOW - timedelta(days=90-index)).isoformat(),
                         "close": 100 + index * (1 + offset / 40), "provider": "test"})
    return rows


def prediction_payload(*, stale: bool = False, mapping: bool = True) -> dict:
    observed = NOW - timedelta(days=5 if stale else 0)
    return {"markets": [{"provider": "Polymarket", "market_id": "ai-reg", "event_key": "ai-reg",
                         "title": "Will AI regulation pass?", "category": "POLICY",
                         "probability": {"source_type": "MARKET_IMPLIED", "probability": .62,
                                         "as_of": observed.isoformat(), "source": "Polymarket"},
                         "quality": {"level": "LOW" if stale else "HIGH"},
                         "change": {"previous_probability": .54, "percentage_point_change": 8.0},
                         "affected_holdings": ["MSFT"] if mapping else [], "linked_companies": ["MSFT"]}],
            "disagreements": []}


def test_company_analysis_is_typed_and_drops_raw_observation_payloads():
    stored, research = company_fixture()
    result = phase6_domains.build_company_analysis("MSFT", stored, research)
    assert result.ticker == "MSFT" and result.eagleeyes_score == 78
    assert result.fundamental_trend["direction"] in {"IMPROVING", "STABLE", "DECLINING", "UNAVAILABLE"}
    assert "prices" not in result.model_dump() and "fundamentals" in result.model_dump()


def test_company_analysis_degrades_when_news_is_missing():
    stored, research = company_fixture(news=False)
    result = phase6_domains.build_company_analysis("MSFT", stored, research)
    assert "news" in result.evidence_quality.missing_domains
    assert result.eagleeyes_score == 78


def test_company_fund_methodology_is_inappropriate():
    stored, research = company_fixture("SPY", asset_type="etf")
    result = phase6_domains.build_company_analysis("SPY", stored, research)
    assert result.identity["methodology_eligible"] is False
    assert "not applied to funds" in result.identity["methodology_note"]


def test_company_missing_required_fundamentals_is_unavailable():
    stored, research = company_fixture()
    stored["fundamentals"] = []
    model = phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    assert model.metadata.analysis_status == AnalysisStatus.UNAVAILABLE


def test_stale_company_price_is_labeled():
    stored, research = company_fixture()
    research["price_as_of"] = (NOW - timedelta(days=12)).isoformat()
    assert phase6_domains.build_company_analysis("MSFT", stored, research).price_state["data_status"] == "STALE"


def test_company_comparison_preserves_full_fields_and_optional_portfolio_fit():
    left = phase6_domains.build_company_analysis("MSFT", *company_fixture("MSFT"))
    right = phase6_domains.build_company_analysis("AMZN", *company_fixture("AMZN", score=72))
    result = phase6_domains.build_company_comparison([left, right], None)
    assert len(result.valuation_comparison) == 2 and len(result.balance_sheet_comparison) == 2
    assert result.portfolio_context_available is False and result.companies[0]["ticker"] == "MSFT"


def test_company_comparison_portfolio_fit_is_weight_mapping_not_impact_forecast():
    left = phase6_domains.build_company_analysis("MSFT", *company_fixture("MSFT"))
    right = phase6_domains.build_company_analysis("AMZN", *company_fixture("AMZN"))
    result = phase6_domains.build_company_comparison([left, right], [{"ticker": "MSFT", "weight": .23}])
    assert result.portfolio_fit[0]["current_portfolio_weight"] == 23
    assert "no return forecast" in result.portfolio_fit[0]["methodology"]


def test_macro_complete_state_keeps_forecast_separate():
    result = phase6_domains.build_macro_state(macro_rows(), [{"dominant_regime": "mixed", "model_version": "v1"}])
    assert result.observed_state["type"] == "OBSERVED" and result.forecast is None
    assert result.evidence_quality.level == "HIGH"


def test_macro_missing_labor_is_partial_quality():
    result = phase6_domains.build_macro_state(macro_rows(include_labor=False), [])
    assert result.labor["status"] == "UNAVAILABLE"
    assert result.evidence_quality.level == "MODERATE"


def test_macro_changes_use_domain_thresholds():
    result = phase6_domains.build_macro_state(macro_rows(), [])
    assert any(row.metric == "FEDFUNDS" and row.materiality in {"MEDIUM", "HIGH"} for row in result.changes)


def test_market_state_is_distinct_from_macro_and_has_leadership():
    result = phase6_domains.build_market_state(market_rows())
    assert result.risk_on_off_state["state"] == "RISK_ON"
    assert result.sector_leadership and not hasattr(result, "inflation")


def test_market_state_missing_breadth_does_not_fail_trend():
    result = phase6_domains.build_market_state(market_rows(breadth=False))
    assert result.broad_market_trend["state"] == "UP"
    assert result.evidence_quality.level in {"MODERATE", "LOW"}


def test_market_regime_change_is_material():
    current = phase6_domains.build_market_state(market_rows())
    prior = current.model_copy(deep=True)
    prior.risk_on_off_state["state"] = "RISK_OFF"
    changed = phase6_domains.build_market_state(market_rows(), prior)
    assert any(row.metric == "risk_on_off_state" for row in changed.material_changes)


def test_prediction_probability_semantics_and_percentage_points():
    result = phase6_domains.build_prediction_market_state(prediction_payload(), [{"ticker": "MSFT", "weight": .23}])
    assert result.probability_types == ["MARKET_IMPLIED"]
    assert result.changes[0].delta_pp == 8.0
    assert result.markets[0]["mapped_portfolio_weight"] == 23


def test_prediction_no_mapping_keeps_market_state_usable():
    result = phase6_domains.build_prediction_market_state(prediction_payload(mapping=False), [{"ticker": "AAPL", "weight": 1}])
    assert result.markets and result.markets[0]["mapping_confidence"] == "UNAVAILABLE"
    assert result.markets[0]["mapped_portfolio_weight"] == 0


def test_prediction_stale_and_calibration_unavailable_are_explicit():
    result = phase6_domains.build_prediction_market_state(prediction_payload(stale=True), None)
    assert result.calibration_quality == "UNAVAILABLE"
    assert result.markets[0]["quality"]["level"] == "LOW"


def test_prediction_multiple_providers_are_not_silently_aggregated():
    payload = prediction_payload()
    second = dict(payload["markets"][0])
    second.update({"provider": "Kalshi", "market_id": "ai-reg-kalshi"})
    second["probability"] = {**second["probability"], "probability": .48, "source": "Kalshi"}
    payload["markets"].append(second)
    payload["disagreements"] = [{"event_key": "ai-reg", "agreement": "LOW", "range": [.48, .62]}]
    result = phase6_domains.build_prediction_market_state(payload, None)
    assert len(result.markets) == 2 and result.provider_disagreements[0]["agreement"] == "LOW"


def test_prediction_closed_market_status_survives():
    payload = prediction_payload()
    payload["markets"][0]["status"] = "CLOSED"
    result = phase6_domains.build_prediction_market_state(payload, None)
    assert result.markets[0]["status"] == "CLOSED"


def test_prediction_disappeared_market_is_not_treated_as_zero_probability():
    result = phase6_domains.build_prediction_market_state({"markets": [], "disagreements": []}, None)
    assert result.markets == [] and result.evidence_quality.level == "INSUFFICIENT_DATA"


def test_portfolio_macro_mapping_does_not_claim_loss_magnitude():
    macro = phase6_domains.build_macro_state(macro_rows(), [])
    result = phase6_domains.portfolio_macro_exposures(macro, [{"ticker": "MSFT", "weight": .4}],
                                                      [{"ticker": "MSFT", "sector": "Technology"}])
    rates = next(row for row in result if row.macro_factor == "rates")
    assert rates.portfolio_weight == 40 and rates.historical_or_model_sensitivity is None


def test_persist_and_load_company_read_model_without_live_rebuild(monkeypatch):
    stored, research = company_fixture()
    model = phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    monkeypatch.setattr(database, "security_data", lambda *_args, **_kwargs: pytest.fail("Ask rebuilt company data"))
    loaded = phase6_domains.company_analysis_result("user-a", "MSFT")
    assert loaded.status in {AnalysisStatus.SUCCESS, AnalysisStatus.PARTIAL}
    assert loaded.data["ticker"] == "MSFT" and model.id


def test_company_pair_loads_concurrently_and_never_calls_security_research(monkeypatch):
    for ticker in ("MSFT", "AMZN"):
        phase6_domains.materialize_company("user-a", ticker, stored=company_fixture(ticker)[0], research_row=company_fixture(ticker)[1])
    monkeypatch.setattr("backend.analysis.security_research", lambda *_args, **_kwargs: pytest.fail("sync research called"))
    result = phase6_domains.company_comparison_result("user-a", ["MSFT", "AMZN"], None)
    assert result.status == AnalysisStatus.PARTIAL and len(result.data["companies"]) == 2


def test_targeted_company_invalidation_does_not_stale_other_tickers():
    for ticker in ("MSFT", "AMZN"):
        stored, research = company_fixture(ticker)
        phase6_domains.materialize_company("user-a", ticker, stored=stored, research_row=research)
    phase6_domains.invalidate_domain("user-a", "fundamentals", "new-msft", tickers=["MSFT"])
    assert phase6_domains.load_company("user-a", "MSFT").state == read_models.CompatibilityState.STALE
    assert phase6_domains.load_company("user-a", "AMZN").state == read_models.CompatibilityState.CURRENT


def test_historical_no_baseline_is_not_no_material_change():
    stored, research = company_fixture()
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    result = phase6_domains.historical_comparison("user-a", "company_analysis", "company:MSFT")
    assert result.status == phase6_domains.HistoricalStatus.NO_BASELINE


def test_historical_no_material_change():
    stored, research = company_fixture()
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    result = phase6_domains.historical_comparison("user-a", "company_analysis", "company:MSFT")
    assert result.status == phase6_domains.HistoricalStatus.NO_MATERIAL_CHANGE


def test_historical_material_change():
    stored, research = company_fixture(score=70)
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    changed = dict(research); changed["final_score"] = 80
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=changed)
    result = phase6_domains.historical_comparison("user-a", "company_analysis", "company:MSFT")
    assert result.status == phase6_domains.HistoricalStatus.MATERIAL_CHANGE


def test_historical_incompatible_calculation_version_is_explicit():
    stored, research = company_fixture()
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    latest = database.capability_read_model_history("user-a", "company:MSFT", "company_analysis", 1)[0]
    metadata = dict(latest["metadata"]); metadata["calculation_version"] = "old-company-v0"
    database.save_capability_read_model("user-a", "company:MSFT", metadata, latest["data"])
    result = phase6_domains.historical_comparison("user-a", "company_analysis", "company:MSFT")
    assert result.status == phase6_domains.HistoricalStatus.INCOMPATIBLE_BASELINE
    assert result.methodology_changed is True


def test_last_review_never_falls_back_to_snapshot():
    stored, research = company_fixture()
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    result = phase6_domains.historical_comparison("user-a", "company_analysis", "company:MSFT", selection="last_review")
    assert result.status == phase6_domains.HistoricalStatus.NO_BASELINE
    assert "not substituted" in result.baseline.reason_if_incompatible


def test_company_comparison_ask_regression_uses_canonical_data(monkeypatch):
    for ticker in ("MSFT", "AMZN"):
        stored, research = company_fixture(ticker)
        phase6_domains.materialize_company("user-a", ticker, stored=stored, research_row=research)
    monkeypatch.setattr(main, "security_research", lambda *_args, **_kwargs: pytest.fail("legacy comparison path"))
    tools, evidence = main._comparison_chat_tools("user-a", "Compare MSFT and AMZN")
    assert tools[0]["analysis_result"]["data"]["balance_sheet_comparison"]
    assert evidence[0]["data"]["valuation_comparison"]


def test_company_comparison_materializes_missing_read_models_from_stored_evidence(monkeypatch):
    fixtures = [company_fixture(ticker) for ticker in ("MSFT", "AMZN")]
    stored = {
        key: [row for fixture, _ in fixtures for row in fixture.get(key, [])]
        for key in ("securities", "fundamentals", "prices", "news", "company_markets")
    }
    research = [row for _, row in fixtures]
    monkeypatch.setattr(main.database, "security_data", lambda *_args, **_kwargs: stored)
    monkeypatch.setattr(main, "security_research", lambda *_args, **_kwargs: research)
    monkeypatch.setattr(main.database, "list_portfolios", lambda *_args, **_kwargs: [{"holdings": [
        {"ticker": "MSFT", "weight": .18}, {"ticker": "AMZN", "weight": .07},
    ]}])

    tools, _ = main._comparison_chat_tools("user-on-demand", "Compare MSFT and AMZN, including portfolio fit.")

    result = tools[0]["analysis_result"]
    assert result["status"] in {"SUCCESS", "PARTIAL"}
    assert result["coverage"]["evaluated_entities"] == ["MSFT", "AMZN"]
    rendered = phase6_domains.render_comparison(phase6_domains.CompanyComparisonResult.model_validate(result["data"]))
    assert "MSFT vs AMZN" in rendered
    assert "Bottom line" in rendered
    assert "ranks ahead overall" in rendered
    assert "MSFT: 18.0%" in rendered
    assert "AMZN: 7.0%" in rendered


def test_deep_job_running_does_not_hide_fast_company_model():
    stored, research = company_fixture()
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    from backend import analytics_jobs
    analytics_jobs.submit_job(job_type=analytics_jobs.JobType.COMPANY_RESEARCH_BUILD, user_id="user-a",
                              payload={"tickers": ["MSFT"]})
    assert phase6_domains.company_analysis_result("user-a", "MSFT").data["ticker"] == "MSFT"


def test_renderers_are_useful_without_gemini():
    company = phase6_domains.build_company_analysis("MSFT", *company_fixture())
    macro = phase6_domains.build_macro_state(macro_rows(), [])
    market = phase6_domains.build_market_state(market_rows())
    prediction = phase6_domains.build_prediction_market_state(prediction_payload(), None)
    assert "EagleEyes score" in phase6_domains.render_company(company)
    assert "Forecasts are separate" in phase6_domains.render_macro(macro)
    assert "Risk state" in phase6_domains.render_market(market)
    assert "market-implied evidence" in phase6_domains.render_prediction(prediction)


def test_normal_phase6_ask_loaders_never_rebuild_domains(monkeypatch):
    stored, research = company_fixture()
    phase6_domains.materialize_company("user-a", "MSFT", stored=stored, research_row=research)
    phase6_domains.materialize_macro("user-a", rows=macro_rows(), regime_rows=[])
    phase6_domains.materialize_market("user-a", rows=market_rows())
    phase6_domains.materialize_prediction_markets("user-a", intelligence=prediction_payload(), holdings=None)
    monkeypatch.setattr(database, "security_data", lambda *_args, **_kwargs: pytest.fail("company rebuild in Ask"))
    monkeypatch.setattr(database, "macro_observation_history", lambda *_args, **_kwargs: pytest.fail("macro rebuild in Ask"))
    monkeypatch.setattr(database, "price_history", lambda *_args, **_kwargs: pytest.fail("market rebuild in Ask"))
    monkeypatch.setattr("backend.forecasting.build_intelligence", lambda *_args, **_kwargs: pytest.fail("prediction rebuild in Ask"))
    assert main._phase6_chat_tools("company_analysis", "user-a", "MSFT", planned_tickers=("MSFT",))[0][0]["status"] in {"complete", "partial"}
    assert main._phase6_chat_tools("macro_state", "user-a", "macro environment")[0][0]["status"] in {"complete", "partial"}
    assert main._phase6_chat_tools("market_state", "user-a", "market state")[0][0]["status"] in {"complete", "partial"}
    assert main._phase6_chat_tools("prediction_markets", "user-a", "prediction markets")[0][0]["status"] in {"complete", "partial"}
