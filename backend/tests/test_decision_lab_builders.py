from __future__ import annotations

import math
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend import database
from backend.allocation_builders import optimize_etfs, optimize_stocks
from backend.main import app
from backend.models import ETFAllocationRequest, Holding, SimulationRunInput, StockBasketRequest
from backend.security_snapshot import technicals
from backend.simulation_engine import run_simulation


def price_fixture(tickers: list[str], sessions: int = 3200) -> list[dict]:
    start = date(2005, 1, 1)
    rows = []
    for index in range(sessions):
        for offset, ticker in enumerate(tickers):
            close = 100 * math.exp((.00018 + offset * .000015) * index + .04 * math.sin(index / 45 + offset))
            rows.append({"ticker": ticker, "date": (start + timedelta(days=index)).isoformat(), "close": close, "volume": 1_000_000 + index, "provider": "golden"})
    return rows


def test_simulation_is_reproducible_and_uses_common_paths():
    payload = SimulationRunInput(
        holdings=[Holding(ticker="AAA", weight=.65), Holding(ticker="BBB", weight=.35)],
        paths=300, horizon_years=3, seed=42,
    )
    rows = price_fixture(["AAA", "BBB", "VTI"])
    first = run_simulation(payload, rows)
    second = run_simulation(payload, rows)
    assert first["shared_path_fingerprint"] == second["shared_path_fingerprint"]
    assert first["outcomes"] == second["outcomes"]
    assert len(first["outcomes"]) == 6
    assert all(row["scenario_summary"]["eligible_months"] == first["coverage"]["monthly_observations"] for row in first["outcomes"])
    assert all(row["real_wealth_percentiles"]["p50"] < row["wealth_percentiles"]["p50"] for row in first["outcomes"])
    assert all(sum(row["histograms"]["terminal_wealth"]["counts"]) == payload.paths for row in first["outcomes"])
    current = next(row for row in first["outcomes"] if row["strategy_key"] == "current")
    contributions = next(row for row in first["outcomes"] if row["strategy_key"] == "contributions_only")
    assert current["wealth_percentiles"] != contributions["wealth_percentiles"]


def test_combined_macro_states_remain_independent_dimensions():
    payload = SimulationRunInput.model_validate({
        "holdings": [{"ticker": "AAA", "weight": .5}, {"ticker": "BBB", "weight": .5}],
        "paths": 250, "horizon_years": 2, "seed": 9,
        "scenario": {"economic_state": "recession", "inflation_state": "accelerating", "rate_state": "tightening", "shocks": ["oil", "credit"]},
    })
    result = run_simulation(payload, price_fixture(["AAA", "BBB", "VTI"]))
    selected = result["outcomes"][0]["scenario_summary"]["selected_conditions"]
    assert selected == ["economic:recession", "inflation:accelerating", "rates:tightening", "shock:oil", "shock:credit"]
    assert result["outcomes"][0]["scenario_summary"]["shrinkage_to_unconditional"] > 0
    assert result["outcomes"][0]["scenario_summary"]["unsupported_conditions"] == selected


def test_technical_evidence_never_emits_trade_labels():
    payload = {"prices": price_fixture(["AAA", "SPY"], 800), "news": [], "fundamentals": [], "securities": []}
    result = technicals("AAA", payload)
    serialized = str(result).upper()
    assert result["status"] == "ready"
    assert result["rsi_14"] is not None
    assert all(label not in serialized for label in ("BUY", "HOLD", "SELL"))
    assert result["calculation"]["version"]


def test_etf_builder_reconciles_cost_history_and_ranges(monkeypatch):
    rows = price_fixture(["AAA", "BBB"])
    monkeypatch.setattr(database, "price_history", lambda tickers, limit=10000: [row for row in rows if row["ticker"] in tickers])
    entries = {
        "AAA": {"ticker": "AAA", "name": "Alpha ETF", "issuer": "One", "category": "US Equity", "expense_ratio": .001},
        "BBB": {"ticker": "BBB", "name": "Beta ETF", "issuer": "Two", "category": "Bonds", "expense_ratio": .002},
    }
    monkeypatch.setattr(database, "etf_catalog_entry", lambda ticker: entries.get(ticker))
    monkeypatch.setattr(database, "etf_research_detail", lambda ticker, portfolio_tickers=None: {"snapshot_coverage": {"coverage_percentage": .98}, "concentration": {"effective_holdings": 100, "top_10_weight": .20}, "holdings": []})
    result = optimize_etfs(ETFAllocationRequest(candidate_tickers=["AAA", "BBB"], max_fund_weight=.60, minimum_history_years=2))
    assert result["constraints"]["status"] == "satisfied"
    assert len(result["allocations"]) == 2
    assert result["expected_expense_dollars_year_one"] > 0
    assert all(row["target_range"][0] <= row["reference_weight"] <= row["target_range"][1] for row in result["allocations"])


def test_stock_builder_discloses_universe_and_requested_benchmark(monkeypatch):
    rows = price_fixture(["AAA", "BBB", "SPY"])
    monkeypatch.setattr(database, "price_history", lambda tickers, limit=10000: [row for row in rows if row["ticker"] in tickers])
    monkeypatch.setattr("backend.allocation_builders.security_research", lambda tickers: [
        {"ticker": ticker, "company": ticker, "sector": "Technology", "industry": "Software", "strengths": ["quality"], "risks": []}
        for ticker in tickers if ticker != "SPY"
    ])
    result = optimize_stocks(StockBasketRequest(candidate_tickers=["AAA", "BBB"], benchmark="SPY", max_security_weight=.60, minimum_history_years=2))
    assert result["universe"]["requested"] == ["AAA", "BBB"]
    assert any(row["name"] == "SPY" for row in result["benchmarks"])
    assert "BUY" not in str(result).upper()


def test_simulation_api_persists_queued_job_before_work(monkeypatch):
    rows = price_fixture(["AAA", "BBB", "VTI"])
    monkeypatch.setattr(database, "price_history", lambda tickers, limit=10000: [row for row in rows if row["ticker"] in tickers])
    with TestClient(app) as client:
        response = client.post("/api/simulations/runs", json={
            "holdings": [{"ticker": "AAA", "weight": .6}, {"ticker": "BBB", "weight": .4}],
            "paths": 250, "horizon_years": 2, "seed": 7,
        })
        assert response.status_code == 202, response.text
        created = response.json()
        assert created["status"] == "PENDING"
        job = client.get(f"/api/analytics/jobs/{created['job']['id']}")
        assert job.status_code == 200
        assert job.json()["status"] == "QUEUED"
