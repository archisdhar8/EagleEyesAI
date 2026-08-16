from fastapi.testclient import TestClient

from backend.main import _company_research_chat_tools, _conversation_summary, _portfolio_chat_tools, app


def test_health_reports_storage_and_disables_trading() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/health").json()
    assert payload == {"status": "ok", "mode": "sqlite", "storage": "sqlite", "trading_enabled": False}


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
    monkeypatch.setattr("backend.main.security_research", lambda tickers: [{"ticker": ticker} for ticker in tickers])
    with TestClient(app) as client:
        home = client.get("/api/home/briefing")
        securities = client.get("/api/explore/securities?tickers=AAPL,MSFT")
        markets = client.get("/api/explore/prediction-markets")
    assert home.status_code == 200
    assert len(home.json()["briefing"]["attention"]) <= 3
    relevance = home.json()["briefing"]["portfolio_relevance"]
    assert [row["factor"] for row in relevance] == ["Higher rates", "Inflation", "Recession", "Oil shock"]
    assert all(row["relevance"] in {"low", "moderate", "high"} for row in relevance)
    assert "allocation change is justified" in home.json()["briefing"]["summary"]
    assert [row["ticker"] for row in securities.json()] == ["AAPL", "MSFT"]
    assert markets.json()["contracts"] == []


def test_csv_import_validation() -> None:
    with TestClient(app) as client:
        response = client.post("/api/portfolios/import", json={"name": "Test", "csv_text": "ticker,weight,account_type\nSPY,0.6,taxable\nBND,0.4,traditional_ira\n"})
    assert response.status_code == 200
    assert response.json()["validated_rows"] == 2


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
        portfolio = client.get("/api/portfolios").json()[0]
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


def test_portfolio_chat_runs_simulation_as_visible_tool(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.database.list_portfolios", lambda user_id: [{"id": "portfolio-1", "holdings": [{"ticker": "SPY", "weight": 1.0}]}])
    monkeypatch.setattr("backend.main.database.load_profile", lambda user_id: {"horizon_years": 10})
    monkeypatch.setattr("backend.main.database.list_goals", lambda user_id: [])
    monkeypatch.setattr("backend.main.database.save_simulation_run", lambda user_id, result: result["id"])
    monkeypatch.setattr("backend.main.run_simulation", lambda payload: {
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


def test_company_chat_refreshes_approved_research_and_returns_article_lineage(monkeypatch) -> None:
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

    assert refreshed == [(["MU"], 90)]
    assert tools[0]["tool_name"] == "company_research_refresh"
    assert tools[0]["status"] == "complete"
    assert tools[0]["summary"]["news"]["article_count"] == 1
    assert tools[0]["summary"]["revenue_growth"] == .18
    assert evidence[0]["label"] == "MU refreshed company research"
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
