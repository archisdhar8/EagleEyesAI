from __future__ import annotations

from datetime import date

import pandas as pd

from backend import database, model_portfolios
from backend.models import ModelPortfolioBacktestRequest, ModelPortfolioCompareRequest


def test_compare_discloses_universe_and_builds_named_alternatives(monkeypatch):
    monkeypatch.setattr(database, "etf_catalog_entry", lambda ticker: None)

    def fake_optimizer(request):
        weight = 1 / len(request.candidate_tickers)
        return {
            "model_version": "fixture", "objective": request.objective,
            "allocations": [{"ticker": ticker, "reference_weight": weight} for ticker in request.candidate_tickers],
            "constraints": {"status": "satisfied", "diagnostics": []}, "warnings": [],
        }

    monkeypatch.setattr(model_portfolios, "optimize_stocks", fake_optimizer)
    result = model_portfolios.compare(ModelPortfolioCompareRequest(
        portfolio_type="stocks", candidate_tickers=["AAPL", "MSFT", "AAPL"]
    ))
    assert result["status"] == "ready"
    assert result["universe"]["analyzed"] == ["AAPL", "MSFT"]
    assert "within these 2 analyzed securities" in result["universe"]["disclosure"]
    assert list(result["alternatives"])[0] == "equal_weight"
    assert {"lower_downside", "balanced", "quality_growth", "value", "income", "custom"}.issubset(result["alternatives"])


def test_backtest_uses_common_history_and_disclosed_three_fund(monkeypatch):
    dates = pd.date_range("2020-01-31", periods=48, freq="ME")
    prices = {
        "AAPL": [100 * (1.012 ** index) for index in range(48)],
        "MSFT": [100 * (1.010 ** index) for index in range(48)],
        "SPY": [100 * (1.008 ** index) for index in range(48)],
        "VTI": [100 * (1.008 ** index) for index in range(48)],
        "VXUS": [100 * (1.006 ** index) for index in range(48)],
        "BND": [100 * (1.002 ** index) for index in range(48)],
    }
    rows = [
        {"ticker": ticker, "date": day.isoformat(), "close": values[index], "provider": "fixture"}
        for ticker, values in prices.items() for index, day in enumerate(dates)
    ]
    monkeypatch.setattr(database, "price_history", lambda tickers, limit: [row for row in rows if row["ticker"] in tickers])
    result = model_portfolios.backtest(ModelPortfolioBacktestRequest(
        alternatives={"balanced": {"AAPL": .5, "MSFT": .5}}, benchmark="SPY"
    ))
    assert result["status"] == "ready"
    assert result["period"]["monthly_observations"] == 47
    keys = {row["key"] for row in result["results"]}
    assert keys == {"balanced", "benchmark_spy", "benchmark_three_fund"}
    assert result["lineage"][0]["dataset"].startswith("corporate-action-adjusted")
    assert any("60% VTI" in item for item in result["assumptions"])


def test_backtest_keeps_spy_when_relevant_benchmark_differs(monkeypatch):
    dates = pd.date_range("2022-01-31", periods=30, freq="ME")
    rows = [
        {"ticker": ticker, "date": day.isoformat(), "close": 100 + index, "provider": "fixture"}
        for ticker in ("AAPL", "SPY", "QQQ", "VTI", "VXUS", "BND")
        for index, day in enumerate(dates)
    ]
    monkeypatch.setattr(database, "price_history", lambda tickers, limit: [row for row in rows if row["ticker"] in tickers])
    result = model_portfolios.backtest(ModelPortfolioBacktestRequest(
        alternatives={"balanced": {"AAPL": 1}}, benchmark="QQQ"
    ))
    keys = {row["key"] for row in result["results"]}
    assert {"benchmark_spy", "benchmark_relevant_qqq", "benchmark_three_fund"}.issubset(keys)


def test_model_portfolio_sqlite_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DATABASE_URL", None)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "dashboard.db")
    database.initialize()
    saved = database.save_model_portfolio("user-a", {
        "name": "Draft basket", "portfolio_type": "mixed", "status": "saved",
        "candidate_universe": {"count": 2}, "basket": [{"ticker": "AAPL"}, {"ticker": "VTI"}],
        "configuration": {"benchmark": "SPY"}, "comparison_results": {}, "backtest_results": {},
    })
    assert database.get_model_portfolio("user-a", saved["id"])["basket"][1]["ticker"] == "VTI"
    assert database.list_model_portfolios("user-b") == []
    database.delete_model_portfolio("user-a", saved["id"])
    assert database.list_model_portfolios("user-a") == []
