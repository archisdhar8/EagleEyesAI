import time

import pytest
from fastapi.testclient import TestClient

from backend import ask_portfolio, database
from backend.main import (
    _benchmark_outlook_chat_tools, _chat_narration_fallback, _company_research_chat_tools, _conversation_summary, _deterministic_chat_answer,
    _cors_allowed_origins, _decision_workspace_inputs, _execute_chat_plan_tools, _portfolio_chat_tools, _portfolio_risk_chat_tools,
    _security_ranking_chat_tools, app,
)


def test_health_reports_storage_and_disables_trading() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/health").json()
    assert payload == {
        "status": "ok",
        "mode": "sqlite",
        "storage": "sqlite",
        "storage_readiness": "ready",
        "trading_enabled": False,
    }


def test_remote_storage_failure_does_not_block_health(monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://configured")
    monkeypatch.setattr(database, "initialize", lambda: (_ for _ in ()).throw(TimeoutError()))
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_production_guard_adds_request_id_security_headers_and_metrics() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        metrics = client.get("/api/operations/metrics")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-request-id"]
    assert metrics.status_code == 200
    assert metrics.json()["version"] == "operational-monitoring-v1"
    assert metrics.json()["sample_count"] >= 1


def test_production_guard_rejects_oversized_request(monkeypatch) -> None:
    monkeypatch.setenv("MAX_REQUEST_BYTES", "32")
    with TestClient(app) as client:
        response = client.post("/api/chat", content="x" * 64, headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large"


def test_local_dev_cors_accepts_dynamic_frontend_port() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/overview",
            headers={
                "Origin": "http://localhost:3001",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"


def test_production_cors_accepts_only_exact_configured_origins() -> None:
    assert _cors_allowed_origins(
        "https://eagleeyes-ai.vercel.app/, https://preview.example.com,https://eagleeyes-ai.vercel.app"
    ) == ["https://eagleeyes-ai.vercel.app", "https://preview.example.com"]
    with pytest.raises(RuntimeError, match="exact http"):
        _cors_allowed_origins("*")
    with pytest.raises(RuntimeError, match="exact http"):
        _cors_allowed_origins("eagleeyes-ai.vercel.app")


def test_provider_status_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/providers/status")
    assert response.status_code == 200
    assert response.json() == {"storage": "sqlite", "counts": {}, "freshness": {}, "providers": []}


def test_provider_health_never_requires_live_network_for_status() -> None:
    with TestClient(app) as client:
        response = client.get("/api/providers/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "provider-health-v1"
    assert {row["key"] for row in payload["providers"]} == {"supabase", "fred", "prices", "market_snapshots", "events", "kalshi", "polymarket", "sec", "gemini"}


def test_decision_workspace_uses_only_selected_portfolio(monkeypatch) -> None:
    monkeypatch.setattr(database, "get_portfolio", lambda portfolio_id, user_id: {
        "id": portfolio_id, "holdings": [{"ticker": "AAPL"}], "user_id": user_id,
    })
    monkeypatch.setattr(database, "list_portfolios", lambda user_id: [
        {"id": "wrong", "holdings": [{"ticker": "MSFT"}]},
    ])
    monkeypatch.setattr(database, "load_profile", lambda user_id: {"watchlist": ["spy"]})

    holdings, watchlist = _decision_workspace_inputs("user-1", "selected")

    assert holdings == [{"ticker": "AAPL"}]
    assert watchlist == ["SPY"]


def test_balanced_rebalance_answer_uses_latest_saved_allocations(monkeypatch) -> None:
    analysis = {
        "id": "analysis-1",
        "created_at": "2026-08-17T18:00:00+00:00",
        "current_portfolio": {"holdings": [{"ticker": "AAPL"}, {"ticker": "SPY"}]},
        "alternatives": [{
            "name": "Balanced",
            "turnover": 0.15,
            "tradeoff": "Balances modeled return, risk, taxes, and diversification.",
            "allocations": [
                {"ticker": "AAPL", "current_weight": 0.60, "target_weight": 0.45, "delta": -0.15,
                 "reason": "Reduce concentration in a single company."},
                {"ticker": "SPY", "current_weight": 0.40, "target_weight": 0.55, "delta": 0.15,
                 "reason": "Increase broad-market diversification."},
            ],
        }],
        "implementation_paths": [],
        "warnings": [],
        "model_diagnostics": {},
    }
    monkeypatch.setattr("backend.main.database.latest_analysis", lambda user_id, portfolio_id=None: analysis)

    tools, evidence = _portfolio_chat_tools(
        "user-1", "Why does the Balanced alternative rebalance these holdings?"
    )
    answer = _deterministic_chat_answer("PORTFOLIO_ANALYSIS", tools)

    assert tools[0]["tool_name"] == "latest_portfolio_analysis"
    assert tools[0]["summary"]["selected_alternative"]["name"] == "Balanced"
    assert evidence[0]["data"]["selected_alternative"]["name"] == "Balanced"
    assert answer is not None
    assert "AAPL" in answer and "60.0%" in answer and "45.0%" in answer
    assert "SPY" in answer and "15.0%" in answer


def test_move_out_ten_stocks_returns_long_rebalance_review_with_saved_context(monkeypatch) -> None:
    holdings = [{"ticker": f"S{index}", "weight": .05} for index in range(12)]
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{
        "id": "portfolio-1", "name": "Main", "updated_at": "2026-08-17", "holdings": holdings,
    }])
    monkeypatch.setattr("backend.main.database.latest_analysis", lambda user_id, portfolio_id=None: None)
    monkeypatch.setattr("backend.main.security_research", lambda tickers, price_limit=756: [])
    monkeypatch.setattr("backend.main.research_search_payload", lambda rows, **kwargs: {"results": [{
        "ticker": f"S{index}", "company": f"Stock {index}", "relative_rank": index + 1,
        "evidence_bucket": "Limited evidence" if index >= 8 else "Mixed evidence",
        "weaknesses": [{"label": "Valuation"}], "field_coverage": {"missing": ["Industry position"]},
        "freshness": {"status": "current", "coverage": "medium"}, "expected_return": .04,
        "risk_flags": [], "prediction_markets": [], "fundamentals_as_of": "2026-06-30",
    } for index in range(12)]})
    monkeypatch.setattr("backend.main.theses.decision_contexts", lambda user_id, tickers: {
        ticker: {"has_open_thesis": ticker == "S11", "thesis_status": "ACTIVE" if ticker == "S11" else None,
                 "latest_decision": "WATCH" if ticker == "S10" else None, "latest_decision_date": "2026-08-01"}
        for ticker in tickers
    })

    tools, evidence = _portfolio_chat_tools(
        "user-1", "Rebalance the portfolio by identifying the 10 stocks to move out"
    )
    review = next(item for item in tools if item["tool_name"] == "portfolio_rebalance_review")
    assert len(review["summary"]["candidates"]) == 10
    assert review["summary"]["candidates"][0]["ticker"] == "S11"
    assert evidence[-1]["claim_type"] == "MODEL_OUTPUT"
    answer = _deterministic_chat_answer("PORTFOLIO_ANALYSIS", tools)
    assert answer is not None
    assert "10 holdings" in answer
    assert "S11" in answer and "S2" in answer
    assert "exit-or-replacement review" in answer
    assert "tax" in answer.lower() and "thesis" in answer.lower()


def test_benchmark_outlook_compares_saved_holdings_with_spy_without_promising_returns(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"holdings": [
        {"ticker": "AAPL", "weight": .6}, {"ticker": "MU", "weight": .4},
    ]}])
    rows = [
        {"ticker": "AAPL", "company": "Apple", "expected_return": .12, "confidence": 80, "data_quality": "high",
         "fundamentals_as_of": "2026-06-30", "price_as_of": "2026-08-14", "risk_flags": [], "prediction_markets": []},
        {"ticker": "MU", "company": "Micron", "expected_return": .03, "confidence": 55, "data_quality": "medium",
         "fundamentals_as_of": "2026-06-30", "price_as_of": "2026-08-14", "risk_flags": [], "prediction_markets": []},
        {"ticker": "SPY", "company": "SPDR S&P 500 ETF", "expected_return": .07, "confidence": 85, "data_quality": "high"},
    ]
    monkeypatch.setattr("backend.main.security_research", lambda tickers, price_limit=756: rows)
    monkeypatch.setattr("backend.main.theses.decision_contexts", lambda user_id, tickers: {ticker: {} for ticker in tickers})
    tools, _ = _benchmark_outlook_chat_tools("user-1")
    summary = tools[0]["summary"]
    assert summary["outperform_candidates"][0]["ticker"] == "AAPL"
    assert summary["underperform_candidates"][0]["ticker"] == "MU"
    answer = _deterministic_chat_answer("BENCHMARK_OUTLOOK", tools)
    assert answer is not None
    assert "No system can know" in answer
    assert "AAPL" in answer and "+5.0%" in answer
    assert "MU" in answer and "-4.0%" in answer
    assert "guaranteed forecast" in answer


def test_saved_portfolio_risk_answer_never_needs_provider_calls(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{
        "id": "portfolio-61", "name": "61 holdings", "updated_at": "2026-08-17T18:00:00+00:00",
        "holdings": [
            {"ticker": "AAPL", "weight": .30, "account_type": "taxable"},
            {"ticker": "MSFT", "weight": .25, "account_type": "taxable"},
            {"ticker": "SPY", "weight": .20, "account_type": "roth_ira"},
            {"ticker": "BND", "weight": .15, "account_type": "traditional_ira"},
            {"ticker": "CASH", "weight": .10, "account_type": "taxable"},
        ],
    }])
    monkeypatch.setattr("backend.main.database.latest_portfolio_health", lambda user_id, portfolio_id: {"result": {
        "ask_cache": {"portfolio_intelligence": {
            "concentration": {"sector": [{"sector": "Technology", "weight": .55}]},
            "correlation": {"status": "available", "clusters": [{"holdings": ["AAPL", "MSFT"], "portfolio_weight": .55}]},
            "economic_dependencies": [{"factor": "Enterprise technology spending", "mapped_portfolio_weight": .55}],
            "coverage": {"classification_weight": .9},
        }}
    }})
    tools, evidence = _portfolio_risk_chat_tools("user-1")
    answer = _deterministic_chat_answer("PORTFOLIO_RISK", tools)
    assert tools[0]["status"] == "complete"
    assert tools[0]["summary"]["largest_position"] == {"ticker": "AAPL", "weight": .30, "account_type": "taxable"}
    assert tools[0]["summary"]["sector_and_industry"]["sector"][0]["sector"] == "Technology"
    assert tools[0]["summary"]["correlation"]["clusters"][0]["holdings"] == ["AAPL", "MSFT"]
    assert evidence[0]["claim_type"] == "MODEL_OUTPUT"
    assert answer is not None and "AAPL" in answer and "30.0%" in answer


def test_hidden_risk_cached_answer_synthesizes_all_concentration_dimensions() -> None:
    tools = [{
        "tool_name": "portfolio_intelligence", "status": "complete", "summary": {
            "concentration": {
                "positions": [{"ticker": "SPY", "weight": .25}, {"ticker": "MSFT", "weight": .18}],
                "effective_holdings": 9.4,
                "sector": [{"sector": "Technology", "weight": .48}],
                "industry": [{"industry": "Software", "weight": .29}],
            },
            "correlation": {"status": "AVAILABLE", "clusters": [{
                "holdings": ["MSFT", "GOOGL"], "portfolio_weight": .31,
                "strongest_pair": {"correlation": .79},
            }]},
            "economic_dependencies": [{
                "factor": "AI_INFRASTRUCTURE_DEMAND", "mapped_portfolio_weight": .42,
                "holdings": ["MSFT", "GOOGL", "AVGO"], "mechanism": "AI and data-center spending",
            }],
            "highest_risk_holdings": [{
                "ticker": "MSFT", "risk_contribution": .21, "weight": .18, "health_score": 73,
            }],
            "coverage": {"classification_weight": .91},
        },
    }]

    answer = ask_portfolio.compose("HIDDEN_RISK", tools)

    assert answer is not None
    assert "SPY at 25.0%" in answer
    assert "9.4 equally sized holdings" in answer
    assert "Technology" in answer and "Software" in answer
    assert "MSFT, GOOGL" in answer and "0.79" in answer
    assert "AI Infrastructure Demand" in answer and "42.0%" in answer
    assert "ETF holdings are shown at the fund level" in answer


def test_research_coverage_returns_explicit_missing_history_in_sqlite_mode() -> None:
    with TestClient(app) as client:
        response = client.get("/api/research/coverage?tickers=SPY")
    assert response.status_code == 200
    payload = response.json()
    assert payload["calculation_version"] == "historical-coverage-v1"
    assert payload["symbols"][0]["ticker"] == "SPY"
    assert payload["symbols"][0]["full_cycle_available"] is False
    assert payload["symbols"][0]["warnings"]


def test_research_scope_explains_local_or_unsupported_coverage() -> None:
    with TestClient(app) as client:
        response = client.get("/api/research/universe-support?q=UNKNOWN")
    assert response.status_code == 200
    assert "scope" in response.json()
    assert response.json()["unsupported_reason"]


def test_transaction_import_preview_does_not_mutate_holdings() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolio/transactions/import", json={
            "account_id": "Taxable", "save": False,
            "csv_text": "Date,Type,Symbol,Quantity,Price,Amount\n2025-01-01,Deposit,,,,1000\n2025-01-02,Buy,AAPL,5,100,\n",
        })
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["reconstruction"]["positions"] == {"AAPL": 5.0}
    assert payload["saved"] is None


def test_account_performance_is_labeled_actual_only_with_valuations() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolio/performance", json={
            "account_id": "Taxable", "transactions": [],
            "valuations": [{"date": "2025-01-01", "value": 100}, {"date": "2026-01-01", "value": 110}],
        })
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["label"].startswith("Actual account performance")
    assert payload["hypothetical_label"].startswith("Hypothetical one-year")


def test_regime_history_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/regimes")
    assert response.status_code == 200
    assert response.json() == {"model_version": "macro-regime-rules-v1", "history": []}


def test_model_validation_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/model-validation")
    assert response.status_code == 200
    assert response.json() == {"runs": []}


def test_model_monitoring_has_safe_sqlite_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/model-monitoring")
    assert response.status_code == 200
    assert response.json() == {"latest": None, "promotion_decisions": []}


def test_manual_terminal_layout_is_validated_and_saved() -> None:
    payload = {
        "overview_widgets": [], "macro_widgets": [], "research_widgets": [],
        "focused_tickers": [], "density": "comfortable",
        "terminal_widgets": [
            {"id": "return-1", "type": "portfolio_return", "size": "wide"},
            {"id": "markets-1", "type": "prediction_market_search", "size": "full"},
        ],
    }
    with TestClient(app) as client:
        saved = client.put("/api/preferences", json=payload)
        invalid = client.put("/api/preferences", json={**payload, "terminal_widgets": [{"id":"bad","type":"arbitrary_code","size":"wide"}]})
    assert saved.status_code == 200
    assert saved.json()["terminal_widgets"] == payload["terminal_widgets"]
    assert invalid.status_code == 422


def test_manual_terminal_portfolio_performance_uses_verified_calculation(monkeypatch) -> None:
    expected = {"status":"READY", "data":{"total_return":.12}, "verification":{"status":"passed"}}
    monkeypatch.setattr("backend.main.portfolio_performance_widget", lambda portfolio, years: {**expected, "years":years})
    with TestClient(app) as client:
        created = client.post("/api/portfolios", json={
            "name": "Test portfolio",
            "holdings": [{"ticker": "SPY", "weight": 1, "account_type": "taxable"}],
        })
        assert created.status_code == 200
        response = client.get("/api/terminal/portfolio-performance?years=3")
    assert response.status_code == 200
    assert response.json()["data"]["total_return"] == .12
    assert response.json()["years"] == 3


def test_manual_terminal_market_indicators_have_safe_empty_fallback() -> None:
    with TestClient(app) as client:
        response = client.get("/api/terminal/market-indicators")
    assert response.status_code == 200
    assert response.json() == []


def test_plan_goal_crud_projection_and_allocation_guard() -> None:
    first = {
        "name": "Retirement", "goal_type": "retirement", "target_amount": 1_000_000,
        "target_date": "2046-12-31", "current_value": 100_000, "annual_contribution": 18_000,
        "priority": 1, "inflation_adjusted": True, "account_allocations": {"taxable": .7},
    }
    conflict = {
        "name": "Home", "goal_type": "home_purchase", "target_amount": 200_000,
        "target_date": "2032-12-31", "current_value": 20_000, "annual_contribution": 12_000,
        "priority": 2, "inflation_adjusted": True, "account_allocations": {"taxable": .4},
    }
    with TestClient(app) as client:
        created = client.post("/api/plan/goals", json=first)
        listed = client.get("/api/plan/goals")
        rejected = client.post("/api/plan/goals", json=conflict)
        projection = client.post("/api/plan/projections", json={"goal": created.json(), "risk_tolerance": 6})
        removed = client.delete(f"/api/plan/goals/{created.json()['id']}")
    assert created.status_code == 200
    assert listed.json()[0]["account_allocations"] == {"taxable": .7}
    assert rejected.status_code == 422
    assert "exceeds 100%" in rejected.json()["detail"]
    assert projection.status_code == 200
    assert projection.json()["calculation"]["version"] == "goal-projection-v2"
    assert 0 <= projection.json()["goal_probability"] <= 1
    assert projection.json()["on_track_range"] in {"strong", "moderate", "needs attention"}
    assert projection.json()["contribution_comparison"]["additional_monthly"] == 300
    assert projection.json()["earliest_plausible_goal_date"]
    assert removed.status_code == 204


def test_manual_terminal_layout_crud() -> None:
    payload = {"name": "Macro board", "widgets": [{"id": "macro-1", "type": "macro_indicators", "size": "wide"}]}
    with TestClient(app) as client:
        created = client.post("/api/terminal/layouts", json=payload)
        listed = client.get("/api/terminal/layouts")
        updated = client.put(f"/api/terminal/layouts/{created.json()['id']}", json={**payload, "name": "Rates board"})
        removed = client.delete(f"/api/terminal/layouts/{created.json()['id']}")
    assert created.status_code == 200
    assert listed.json()[0]["widgets"] == payload["widgets"]
    assert updated.json()["name"] == "Rates board"
    assert removed.status_code == 204


def test_market_workspace_aliases_return_existing_evidence(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.refresh_scenarios", lambda force=False: {"scenarios": [], "contracts": [], "warnings": [], "fetched_at": None})
    monkeypatch.setattr("backend.main.security_research", lambda tickers, **kwargs: [{"ticker": ticker} for ticker in tickers])
    with TestClient(app) as client:
        home = client.get("/api/home/briefing")
        securities = client.get("/api/explore/securities?tickers=AAPL,MSFT")
        markets = client.get("/api/explore/prediction-markets")
    assert home.status_code == 200
    assert len(home.json()["briefing"]["attention"]) <= 3
    relevance = home.json()["briefing"]["portfolio_relevance"]
    assert [row["factor"] for row in relevance] == ["Higher rates", "Inflation", "Recession", "Oil shock"]
    assert all(row["relevance"] in {"low", "moderate", "high"} for row in relevance)
    summary = home.json()["briefing"]["summary"]
    assert "No material changes were detected" in summary
    assert home.json()["briefing"]["attention_summary"]["no_material_change"] is True
    assert [row["ticker"] for row in securities.json()] == ["AAPL", "MSFT"]
    assert markets.json()["contracts"] == []


def test_csv_import_validation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Test", "csv_text": "ticker,weight,account_type\nSPY,0.6,taxable\nBND,0.4,traditional_ira\n"})
    assert response.status_code == 200
    assert response.json()["validated_rows"] == 2


def test_users_can_keep_and_reopen_multiple_saved_portfolios() -> None:
    with TestClient(app) as client:
        first = client.post("/api/portfolios", json={
            "name": "Long-term account", "holdings": [{"ticker": "SPY", "weight": 1, "account_type": "taxable"}],
        }).json()
        second = client.post("/api/portfolios", json={
            "name": "Retirement account", "holdings": [{"ticker": "BND", "weight": 1, "account_type": "traditional_ira"}],
        }).json()
        saved = client.get("/api/portfolios").json()
        reopened = client.post(f"/api/portfolios/{first['id']}/activate")
        active = client.get("/api/portfolios").json()
    assert {first["id"], second["id"]}.issubset({item["id"] for item in saved})
    assert reopened.status_code == 200
    assert reopened.json()["holdings"] == first["holdings"]
    assert active[0]["id"] == first["id"]


def test_csv_import_assigns_reviewable_placeholder_weight_without_size() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"csv_text": "ticker,account_type\nSPY,taxable\n"})
    assert response.status_code == 200
    assert response.json()["portfolio"]["holdings"][0]["weight"] == 1
    assert "placeholder weights" in response.json()["warnings"][0]


def test_csv_import_accepts_explicit_weight_percent() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios/import",
            json={"name": "Percent weights", "csv_text": "ticker,weight_percent\nSPY,60\nBND,40\n"},
        )
    assert response.status_code == 200
    assert [row["weight"] for row in response.json()["portfolio"]["holdings"]] == [.6, .4]


def test_csv_import_prefers_explicit_percent_column() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios/import",
            json={"csv_text": "ticker,weight,weight_percent\nSPY,0.6,60\n"},
        )
    assert response.status_code == 200
    assert response.json()["portfolio"]["holdings"][0]["weight"] == .6
    assert "explicit percentage" in response.json()["warnings"][0]


def test_csv_import_combines_duplicate_tickers_cleanly() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios/import",
            json={"csv_text": "ticker,weight_percent\nAAPL,50\naapl,50\n"},
        )
    assert response.status_code == 200
    assert response.json()["validated_rows"] == 1
    assert response.json()["portfolio"]["holdings"][0]["weight"] == 1
    assert any("duplicate ticker" in warning for warning in response.json()["warnings"])


def test_csv_import_accepts_symbol_alias_extra_columns_and_broker_numbers() -> None:
    text = "Symbol;Description;Quantity;Last Price;Current Value;Account Name;Day Change\nAAPL;Apple Inc;10;$200;$2,000;Roth IRA;1.2%\n"
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Broker export", "csv_text": text})
    assert response.status_code == 200
    holding = response.json()["portfolio"]["holdings"][0]
    assert holding["ticker"] == "AAPL"
    assert holding["shares"] == 10
    assert holding["market_value"] == 2000
    assert holding["account_type"] == "roth_ira"
    assert "Description" in response.json()["ignored_columns"]


def test_csv_import_keeps_valid_rows_and_reports_fixed_income_for_review() -> None:
    text = "\n".join([
        "Symbol,Last Price $,Quantity,Price Paid $,Value $",
        "AAPL,200,10,150,2000",
        "JPMORGAN CHASE BK N A FID 4.25% 03/31/2028,99.39,40000,100,39756",
        "CASH,,,,5000",
    ])
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Mixed brokerage export", "csv_text": text})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [row["ticker"] for row in payload["portfolio"]["holdings"]] == ["AAPL", "CASH"]
    assert payload["portfolio"]["holdings"][0]["cost_basis"] == 1500
    assert payload["review_rows"] == [{
        "line": 3,
        "identifier": "JPMORGAN CHASE BK N A FID 4.25% 03/31/2028",
        "classification": "fixed_income",
        "market_value": 39756.0,
        "reason": "This row does not contain a supported stock, ETF, or mutual-fund ticker.",
    }]
    assert payload["excluded_market_value"] == 39756
    assert any("never truncated" in warning for warning in payload["warnings"])


def test_investment_policy_approval_and_guidance() -> None:
    policy = {
        "name": "Test policy", "status": "draft",
        "target_allocation": {"equities": .7, "fixed_income": .2, "cash": .1},
        "acceptable_ranges": {"equities": [.6, .8], "fixed_income": [.1, .3], "cash": [.05, .15]},
        "minimum_cash_reserve": 10000, "max_single_stock_weight": .2, "max_sector_weight": .35,
        "rebalance_threshold": .05, "rebalance_frequency": "quarterly", "exclusions": [],
        "change_triggers": ["Allocation breach"], "ignore_conditions": ["Ordinary volatility"],
        "research_preferences": {"fundamentals": .25, "growth": .2, "valuation": .2, "dividend_income": .1, "macro_resilience": .15, "price_behavior": .1},
    }
    with TestClient(app) as client:
        saved = client.put("/api/plan/policy", json=policy)
        approved = client.post("/api/plan/policy/approve", json=saved.json())
        guidance = client.get("/api/plan/guidance")
    assert saved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"]
    assert guidance.status_code == 200
    assert guidance.json()["next_dollar"]["amount"] == 1000
    assert guidance.json()["model_customization"]["production_model_changed"] is False


def test_portfolio_rejects_duplicate_tickers() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolios",
            json={
                "name": "Duplicates",
                "holdings": [
                    {"ticker": "AAPL", "weight": .5},
                    {"ticker": "aapl", "weight": .5},
                ],
            },
        )
    assert response.status_code == 422
    assert "Duplicate tickers" in str(response.json()["detail"])


def test_research_refresh_updates_saved_universe(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.main.refresh_security_evidence",
        lambda tickers: {"tickers": tickers, "providers": {"tiingo": 252}, "warnings": []},
    )
    monkeypatch.setattr(
        "backend.main.refresh_company_markets",
        lambda companies: {"markets": [{"id": "market-1"}], "warnings": [], "searched": len(companies)},
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/research/refresh",
            json={"tickers": ["AAPL", "NVDA", "CASH"], "ingest_tickers": ["NVDA", "CASH"]},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["searched"] == 2
    assert payload["markets_found"] == 1
    assert payload["evidence_refresh"] == {"tickers": ["NVDA"], "providers": {"tiingo": 252}, "warnings": []}
    assert {row["ticker"] for row in payload["research"]} == {"AAPL", "NVDA"}


def test_portfolio_update_and_research_include_new_holding() -> None:
    with TestClient(app) as client:
        portfolio = client.post(
            "/api/portfolios",
            json={
                "name": "Initial portfolio",
                "holdings": [{"ticker": "AAPL", "weight": 1, "account_type": "taxable"}],
            },
        ).json()
        saved = client.put(
            f"/api/portfolios/{portfolio['id']}",
            json={
                "name": "Updated portfolio",
                "holdings": [
                    {"ticker": "AAPL", "weight": .8, "account_type": "taxable"},
                    {"ticker": "NVDA", "weight": .2, "account_type": "taxable"},
                ],
            },
        )
        research = client.get("/api/research?tickers=AAPL,NVDA")
    assert saved.status_code == 200
    assert {row["ticker"] for row in saved.json()["holdings"]} == {"AAPL", "NVDA"}
    assert {row["ticker"] for row in research.json()} == {"AAPL", "NVDA"}


def test_new_workspace_starts_without_a_portfolio() -> None:
    with TestClient(app) as client:
        response = client.get("/api/portfolios")
    assert response.status_code == 200
    assert response.json() == []


def test_chat_returns_grounded_reply(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.DATABASE_URL", "postgresql://test")
    monkeypatch.setattr("backend.main.database.initialize", lambda: None)
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"id": "portfolio-1"}])
    monkeypatch.setattr("backend.main.database.create_conversation", lambda user_id, title, portfolio_id, workspace="research": {"id": "conversation-1", "workspace": workspace})
    monkeypatch.setattr("backend.main.database.get_conversation", lambda user_id, conversation_id: {"id": conversation_id, "title": "Existing research", "workspace": "research", "summary": "", "summary_message_count": 0})
    monkeypatch.setattr("backend.main.database.conversation_messages", lambda user_id, conversation_id: [])
    monkeypatch.setattr("backend.main.database.save_chat_message", lambda user_id, conversation_id, role, content, structured=None, model=None: {"id": "message-1", "role": role, "content": content, "structured_content": structured or {}})
    monkeypatch.setattr("backend.main.retrieve_evidence", lambda user_id, question: [{"label": "Portfolio", "url": None, "as_of": "2026-08-09", "data": {}}])
    monkeypatch.setattr("backend.main.ask_gemini", lambda question, evidence, history, summary="": ("Grounded answer [S1]", "gemini-test"))
    with TestClient(app) as client:
        response = client.post("/api/chat/messages", json={"question": "What changed?"})
    assert response.status_code == 200
    assert response.json()["message"]["content"] == "Grounded answer [S1]"
    assert response.json()["sources"][0]["id"] == "S1"


def test_chat_returns_tool_fallback_instead_of_502_when_gemini_times_out(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.DATABASE_URL", "postgresql://test")
    monkeypatch.setattr("backend.main.database.initialize", lambda: None)
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"id": "portfolio-1"}])
    monkeypatch.setattr("backend.main.database.create_conversation", lambda user_id, title, portfolio_id, workspace="research": {"id": "conversation-1", "workspace": workspace})
    monkeypatch.setattr("backend.main.database.get_conversation", lambda user_id, conversation_id: {"id": conversation_id, "title": "Existing research", "workspace": "research", "summary": "", "summary_message_count": 0})
    monkeypatch.setattr("backend.main.database.conversation_messages", lambda user_id, conversation_id: [])
    monkeypatch.setattr("backend.main.database.save_chat_message", lambda user_id, conversation_id, role, content, structured=None, model=None: {"id": "message-1", "role": role, "content": content, "model": model, "structured_content": structured or {}})
    monkeypatch.setattr("backend.main.retrieve_evidence", lambda user_id, question: [{"label": "Portfolio", "url": None, "as_of": "2026-08-09", "data": {}}])
    monkeypatch.setattr("backend.main.ask_gemini", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))
    with TestClient(app) as client:
        response = client.post("/api/chat/messages", json={"question": "Explain the available stored evidence."})
    assert response.status_code == 200
    assert response.json()["message"]["model"] == "deterministic-timeout-fallback-v1"
    assert "did not respond within the interactive deadline" in response.json()["message"]["content"]


def test_chat_analysis_tools_execute_sequentially_without_background_futures(monkeypatch) -> None:
    order = []

    def fake_tool(tool, user_id, question):
        order.extend([f"start:{tool}", f"finish:{tool}"])
        return ([{"tool_name": tool, "status": "complete", "title": tool}], [
            {"label": tool, "as_of": "2026-08-18", "data": {}}
        ])

    monkeypatch.setattr("backend.main._instrumented_ask_tool", fake_tool)
    results, evidence, steps = _execute_chat_plan_tools(
        ("first", "second"), "user-1", "question", time.monotonic(),
    )

    assert order == ["start:first", "finish:first", "start:second", "finish:second"]
    assert [item["tool_name"] for item in results] == ["first", "second"]
    assert [item["label"] for item in evidence] == ["first", "second"]
    assert steps == [
        {"tool_name": "first", "state": "SUCCESS"},
        {"tool_name": "second", "state": "SUCCESS"},
    ]


def test_portfolio_chat_runs_simulation_as_visible_tool(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"id": "portfolio-1", "holdings": [{"ticker": "SPY", "weight": 1.0}]}])
    monkeypatch.setattr("backend.main.database.load_profile", lambda user_id: {"horizon_years": 10})
    monkeypatch.setattr("backend.main.database.list_goals", lambda user_id: [])
    monkeypatch.setattr("backend.main.database.save_simulation_run", lambda user_id, result: result["id"])
    simulation_calls = []
    monkeypatch.setattr("backend.main.run_simulation", lambda payload, **kwargs: simulation_calls.append(kwargs) or {
        "id": "simulation-1", "created_at": "2026-08-15T12:00:00Z", "model_version": "simulation-v-test",
        "warnings": [], "assumptions": ["Shared paths"], "lineage": [{"provider": "fixture"}],
        "outcomes": [{
            "strategy_key": "current", "label": "Current / do nothing",
            "wealth_percentiles": {"p50": 125000.0}, "probability_of_loss": .12,
            "drawdown_percentiles": {"p10": -.28}, "robustness": "Moderate",
        }],
    })
    tools, evidence = _portfolio_chat_tools("user-1", "Simulate a recession with accelerating inflation and an oil shock")
    assert tools[0]["tool_name"] == "portfolio_decision_lab"
    assert tools[0]["status"] == "complete"
    assert tools[0]["input_summary"]["scenario"] == {
        "economic_state": "recession", "inflation_state": "accelerating",
        "rate_state": "unconditioned", "shocks": ["oil"],
    }
    assert tools[0]["summary"]["strategies"][0]["median_wealth"] == 125000.0
    assert evidence[0]["label"] == "Portfolio Decision Lab tool result"
    assert simulation_calls == [{"price_limit_per_ticker": 1260}]


def test_scenario_fast_answer_compares_paths_without_claiming_a_twenty_year_recession() -> None:
    tools = [{
        "tool_name": "portfolio_decision_lab", "status": "complete", "title": "Portfolio simulation",
        "input_summary": {"paths": 1000, "horizon_years": 20, "scenario": {
            "economic_state": "recession", "inflation_state": "accelerating",
            "rate_state": "unconditioned", "shocks": [],
        }},
        "summary": {"warnings": [], "strategies": [
            {"key": "current", "label": "Current / do nothing", "median_wealth": 7_040_314,
             "probability_of_loss": .24, "modeled_drawdown": -.79, "robustness": "Moderate"},
            {"key": "immediate", "label": "Immediate transition", "median_wealth": 8_109_062,
             "probability_of_loss": .20, "modeled_drawdown": -.78, "robustness": "Moderate"},
        ]},
    }]
    answer = _deterministic_chat_answer("SCENARIO", tools)
    assert answer is not None
    assert "Immediate transition" in answer
    assert "$1,068,748" in answer
    assert "does **not** assume the recession lasts 20 years" in answer
    assert "AXP" not in answer


def test_security_ranking_is_limited_to_saved_holdings(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"holdings": [
        {"ticker": "AAPL", "weight": .6}, {"ticker": "MU", "weight": .3}, {"ticker": "CASH", "weight": .1},
    ]}])
    rows = [
        {"ticker": "AAPL", "company": "Apple", "sector": "Technology", "industry": "Hardware",
         "final_score": 75, "confidence": 80, "data_quality": "high", "growth_rating": 70,
         "valuation_score": 62, "fundamental_score": 78, "industry_score": 65, "technical_score": 60,
         "component_coverage": {"growth": True, "valuation": True, "business_quality": True, "industry_position": True, "price_behavior": True}},
        {"ticker": "MU", "company": "Micron", "sector": "Technology", "industry": "Semiconductors",
         "final_score": 48, "confidence": 60, "data_quality": "medium", "growth_rating": 55,
         "valuation_score": 52, "fundamental_score": 40, "industry_score": 42, "technical_score": 45,
         "component_coverage": {"growth": True, "valuation": True, "business_quality": True, "industry_position": True, "price_behavior": True}},
    ]
    requested: list[tuple[list[str], int]] = []
    monkeypatch.setattr(
        "backend.main.security_research",
        lambda tickers, price_limit=756: requested.append((list(tickers), price_limit)) or rows,
    )
    tools, evidence = _security_ranking_chat_tools("user-1", "Which holdings have the strongest and weakest research evidence?")
    assert requested == [(["AAPL", "MU"], 260)]
    assert tools[0]["summary"]["universe"]["tickers"] == ["AAPL", "MU"]
    assert [row["ticker"] for row in tools[0]["summary"]["ranked"]] == ["AAPL", "MU"]
    answer = _deterministic_chat_answer("RESEARCH_RANKING", tools)
    assert answer is not None and "AAPL" in answer and "MU" in answer
    assert "expected return" in answer


def test_worst_holding_answer_focuses_on_weakest_evidence_not_a_sell_call(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"holdings": [
        {"ticker": "AAPL", "weight": .6}, {"ticker": "MU", "weight": .4},
    ]}])
    rows = [
        {"ticker": "AAPL", "company": "Apple", "final_score": 75, "confidence": 80, "data_quality": "high",
         "growth_rating": 70, "valuation_score": 62, "fundamental_score": 78, "industry_score": 65,
         "technical_score": 60, "component_coverage": {"growth": True, "valuation": True,
         "business_quality": True, "industry_position": True, "price_behavior": True}},
        {"ticker": "MU", "company": "Micron", "final_score": 35, "confidence": 40, "data_quality": "low",
         "growth_rating": 45, "valuation_score": 40, "fundamental_score": 35, "industry_score": 38,
         "technical_score": 42, "component_coverage": {"growth": True, "valuation": True,
         "business_quality": True, "industry_position": False, "price_behavior": False}},
    ]
    monkeypatch.setattr("backend.main.security_research", lambda tickers, price_limit=756: rows)
    tools, _ = _security_ranking_chat_tools("user-1", "what is my worst stock holding")
    assert tools[0]["summary"]["focus"] == "weakest"
    answer = _deterministic_chat_answer("RESEARCH_RANKING", tools)
    assert answer is not None
    assert "**MU**" in answer
    assert "weakest evidence-ranked" in answer
    assert "does **not** mean it will have the worst future return" in answer
    assert "sell" in answer


def test_slow_narrator_fallback_preserves_company_tool_evidence() -> None:
    answer = _chat_narration_fallback([{
        "tool_name": "company_research_refresh", "status": "partial", "title": "MU company evidence", "ticker": "MU",
        "summary": {"price": 142.5, "price_as_of": "2026-08-14", "revenue_growth": .18,
                    "net_margin": .12, "news": {"article_count": 3}, "warnings": ["Fundamentals are delayed."]},
    }])
    assert "MU" in answer and "$142.50" in answer and "18.0%" in answer
    assert "did not respond within the interactive deadline" in answer
    assert "invent" in answer


def test_earnings_fallback_formats_period_values_and_thesis_status() -> None:
    answer = _deterministic_chat_answer("EARNINGS", [{
        "tool_name": "earnings_intelligence", "status": "complete", "ticker": "MSFT",
        "summary": {
            "period": {"fiscal_period": "FY", "fiscal_year": 2026, "period_end": "2026-06-30"},
            "actual_vs_expectations": {
                "revenue": {"actual": 331_839_000_000, "consensus": None, "surprise_percent": None},
                "eps": {"actual": 17.95, "consensus": None, "surprise_percent": None},
            },
            "thesis_impact": {"overall_status": "WEAKENING", "assumptions": [{
                "description": "Cloud growth remains durable", "state": "WEAKENS",
            }]},
            "warnings": ["Consensus not available; it is not interpreted as unchanged."],
        },
    }])
    assert answer is not None
    assert "FY 2026, ended June 30, 2026" in answer
    assert "$331.8B" in answer
    assert "$17.95 per share" in answer
    assert "Cloud growth remains durable: weakens" in answer
    assert "{'fiscal_period'" not in answer


def test_company_chat_uses_cached_research_and_returns_article_lineage(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.DATABASE_URL", "postgresql://test")
    monkeypatch.setattr("backend.main.database.search_security_master", lambda query, limit=5: {
        "results": [{"ticker": "MU", "name": "Micron Technology, Inc."}] if query.upper() == "MU" else [],
    })
    research_rows = [{
        "ticker": "MU", "company": "Micron Technology", "sector": "Information Technology",
        "industry": "Semiconductors", "price": 142.5, "price_as_of": "2026-08-14",
        "fundamentals_as_of": "2026-06-30", "revenue_growth": .18, "net_margin": .12,
        "valuation_evidence": {"label": "Near peer range"}, "market_statistics": {"rsi_14": 58.0},
        "fundamental_statistics": {"source": "https://data.sec.gov/"},
        "news_sentiment": {}, "component_coverage": {"fundamentals": True, "news": True},
        "risk_flags": [], "data_quality": "medium",
    }]
    monkeypatch.setattr("backend.main.security_research", lambda tickers: research_rows)
    refreshed: list[tuple[list[str], int]] = []
    monkeypatch.setattr(
        "backend.main.refresh_security_evidence",
        lambda tickers, news_lookback_days=7: refreshed.append((list(tickers), news_lookback_days)) or {"providers": {"polygon_news": 1}, "warnings": []},
    )
    monkeypatch.setattr("backend.main.database.security_data", lambda tickers, price_limit=10: {"news": [{
        "ticker": "MU", "title": "Micron updates its data-center outlook",
        "published_at": "2026-08-14T15:00:00Z", "source_url": "https://example.com/mu-outlook",
        "metadata": {"source": "Example Wire", "summary": "Management discussed demand."},
    }]})

    tools, evidence = _company_research_chat_tools("What is the latest outlook for MU and memory pricing?")

    assert refreshed == []
    assert tools[0]["tool_name"] == "company_research_refresh"
    assert tools[0]["status"] == "complete"
    assert tools[0]["summary"]["news"]["article_count"] == 1
    assert tools[0]["summary"]["revenue_growth"] == .18
    assert tools[0]["input_summary"]["cache_only"] is True
    assert evidence[0]["label"] == "MU cached company research"
    assert evidence[1]["url"] == "https://example.com/mu-outlook"


def test_conversation_memory_summary_is_bounded_and_tracks_tools() -> None:
    messages = [
        {"role": "user", "content": f"Question {index} about MU memory demand"}
        for index in range(12)
    ]
    messages.append({
        "role": "assistant", "content": "Validated response",
        "structured_content": {"tool_results": [{
            "tool_name": "company_research_refresh", "title": "MU company evidence", "ticker": "MU",
        }]},
    })
    summary = _conversation_summary(messages, "Earlier portfolio context")
    assert "Question 11 about MU memory demand" in summary
    assert "MU company evidence (MU)" in summary
    assert len(summary) <= 4000


def test_conversation_crud_routes_keep_workspaces_and_artifacts_separate(monkeypatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr("backend.main.database.list_conversations", lambda user_id, workspace=None: [{
        "id": "research-1", "title": "MU outlook", "workspace": workspace or "research",
        "message_count": 2, "artifact_count": 1, "created_at": "2026-08-15", "updated_at": "2026-08-15",
    }])
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id=None: [])
    monkeypatch.setattr("backend.main.database.create_conversation", lambda user_id, title, portfolio_id, workspace="research": {
        "id": f"{workspace}-new", "title": title, "workspace": workspace,
    })
    monkeypatch.setattr("backend.main.database.get_conversation", lambda user_id, conversation_id: {
        "id": conversation_id, "title": "MU outlook", "workspace": "research", "summary": "Memory demand",
    })
    monkeypatch.setattr("backend.main.database.conversation_messages", lambda user_id, conversation_id: [{"role": "user", "content": "MU outlook"}])
    monkeypatch.setattr("backend.main.database.conversation_artifacts", lambda user_id, conversation_id: [{
        "id": "artifact-1", "artifact_type": "research_snapshot", "artifact_id": "MU:2026-08-15", "label": "MU evidence",
    }])
    monkeypatch.setattr("backend.main.database.rename_conversation", lambda user_id, conversation_id, title: {"id": conversation_id, "title": title, "workspace": "research"})
    monkeypatch.setattr("backend.main.database.delete_conversation", lambda user_id, conversation_id: deleted.append(conversation_id))
    with TestClient(app) as client:
        listed = client.get("/api/chat/conversations?workspace=research")
        created = client.post("/api/chat/conversations", json={"workspace": "portfolio", "title": "New risk review"})
        opened = client.get("/api/chat/conversations/research-1")
        renamed = client.patch("/api/chat/conversations/research-1", json={"title": "Renamed research"})
        removed = client.delete("/api/chat/conversations/research-1")
    assert listed.json()[0]["workspace"] == "research"
    assert created.json()["workspace"] == "portfolio"
    assert opened.json()["artifacts"][0]["artifact_id"] == "MU:2026-08-15"
    assert renamed.json()["title"] == "Renamed research"
    assert removed.status_code == 204
    assert deleted == ["research-1"]


def test_combined_macro_conditions_intersect_independent_dimensions(monkeypatch) -> None:
    labels = []
    prices = []
    for month in range(1, 7):
        labels.append({
            "as_of_date": f"2025-{month:02d}-28", "inputs": {
                "industrial_growth_yoy": -1.0, "unemployment_change_3m": .25,
                "inflation_yoy": 3.5, "policy_rate_change_3m": -.25,
                "oil_change_3m": .20, "credit_spread": 4.0,
            },
        })
        prices.extend([
            {"ticker": "SPY", "date": f"2025-{month:02d}-28", "close": 100 + month * 2},
            {"ticker": "XLE", "date": f"2025-{month:02d}-28", "close": 80 + month * 3},
        ])
    monkeypatch.setattr("backend.main.database.regime_history", lambda limit=1000: list(reversed(labels)))
    monkeypatch.setattr("backend.main.database.price_history", lambda tickers, limit_per_ticker=5000: prices)
    with TestClient(app) as client:
        response = client.get(
            "/api/research/macro-combination?economic=recession&inflation=accelerating&rates=easing&shock=oil&tickers=SPY,XLE"
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["analog_count"] == 6
    assert payload["selected_conditions"] == {
        "economic": "recession", "inflation": "accelerating", "rates": "easing", "shock": "oil",
    }
    assert {row["ticker"] for row in payload["results"]} == {"SPY", "XLE"}
    assert payload["calculation"]["version"] == "macro-combination-v1"
