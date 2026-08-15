from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.dashboard_workspace import calculate_macro_sensitivity
from backend.planning import build_guidance
from backend.portfolio_diagnostics import build_portfolio_diagnostics
from backend.quant import portfolio_path_metrics
from backend.research_workspace import evidence_bucket, search
from backend.scenarios import build_condition_dimensions, build_scenarios


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_quantitative_v1.json").read_text()
)


def test_golden_returns_drawdown_and_correlation() -> None:
    returns = pd.Series(FIXTURE["daily_returns"], dtype=float)
    path = portfolio_path_metrics(returns)
    assert path["observations"] == FIXTURE["expected_path"]["observations"]
    assert path["max_drawdown"] == pytest.approx(FIXTURE["expected_path"]["max_drawdown"])

    frame = pd.DataFrame(FIXTURE["correlation_returns"], dtype=float)
    assert frame.corr().loc["AAPL", "BND"] == pytest.approx(FIXTURE["expected_correlation"])


def test_golden_sector_exposure() -> None:
    result = build_portfolio_diagnostics(
        FIXTURE["holdings"],
        {"securities": FIXTURE["securities"], "prices": []},
        {"funds": [], "holdings": []},
    )
    actual = {row["sector"]: row["weight"] for row in result["sector_exposure"]}
    assert actual == pytest.approx(FIXTURE["expected_sector_exposure"])
    assert result["performance_label"] == "Hypothetical one-year return using current holdings and weights"


def test_golden_candidate_filters_and_research_buckets() -> None:
    result = search(FIXTURE["research"], fundamentals="strong", valuation="reasonable")
    assert [row["ticker"] for row in result["results"]] == FIXTURE["expected_candidate_tickers"]
    by_ticker = {row["ticker"]: row for row in FIXTURE["research"]}
    for ticker, expected in FIXTURE["expected_buckets"].items():
        assert evidence_bucket(by_ticker[ticker])[0] == expected
    assert result["universe"]["total"] == len(FIXTURE["expected_candidate_tickers"])
    assert "not buy recommendations" in result["disclaimer"]


def test_golden_next_dollar_allocation() -> None:
    policy = {
        "status": "approved",
        "max_single_stock_weight": 0.70,
        "target_allocation": {"cash": 0.10, "fixed_income": 0.30},
    }
    result = build_guidance(
        FIXTURE["holdings"], [], policy, FIXTURE["research"], {"providers": []}, [],
        profile={"account_type": "taxable", "tax_rate": 0.25},
    )
    assert result["next_dollar"]["illustrative_symbol"] == FIXTURE["expected_next_dollar"]["illustrative_symbol"]
    assert result["next_dollar"]["amount"] == FIXTURE["expected_next_dollar"]["amount"]
    assert result["next_dollar"]["tax_assumptions"]
    assert result["next_dollar"]["alternatives"]


def test_golden_factor_sensitivity() -> None:
    dates = pd.date_range("2019-01-31", periods=72, freq="ME")
    monthly_growth = 0.002 + np.sin(np.arange(72) / 4) * 0.001
    cpi = pd.Series(250 * np.cumprod(1 + monthly_growth), index=dates)
    signal = cpi.pct_change(12, fill_method=None).mul(100).diff().fillna(0)
    prices = []
    for ticker, coefficient in (("HIGH", 0.02), ("LOW", 0.005)):
        levels = [100.0]
        for value in signal.iloc[1:]:
            levels.append(levels[-1] * (1 + coefficient * value))
        prices.extend(
            {"ticker": ticker, "date": date.isoformat(), "close": close, "provider": "golden-v1"}
            for date, close in zip(dates, levels)
        )
    macro = [
        {"series_id": "CPIAUCSL", "date": date.date().isoformat(), "vintage_date": date.date().isoformat(), "value": value}
        for date, value in cpi.items()
    ]
    rows = calculate_macro_sensitivity(prices, macro, "inflation")["rows"]
    assert [row["ticker"] for row in rows] == ["HIGH", "LOW"]
    assert rows[0]["beta"] == pytest.approx(2.0, abs=0.02)
    assert rows[0]["observations"] >= 48


def test_golden_combined_scenario_dimensions_are_independent() -> None:
    conditions = build_condition_dimensions(build_scenarios([]))
    dimensions: dict[str, list[dict]] = {}
    for condition in conditions:
        dimensions.setdefault(condition["dimension"], []).append(condition)
    assert sum(item["probability"] for item in dimensions["Economic state"]) == pytest.approx(1, abs=0.001)
    assert sum(item["probability"] for item in dimensions["Inflation state"]) == pytest.approx(1, abs=0.001)
    assert sum(item["probability"] for item in dimensions["Rate state"]) == pytest.approx(1, abs=0.001)
    assert {item["key"] for item in dimensions["Independent shocks"]} == {"shock_oil"}
    assert {"economic_recession", "inflation_accelerating", "shock_oil"}.issubset(
        {item["key"] for item in conditions}
    )
