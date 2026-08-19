import numpy as np
import pandas as pd
import pytest

from backend.analysis import (
    _optimize, _price_coverage_diagnostics, _projection, _tax_estimate, _walk_forward, market_climate,
)
from backend.models import InvestorProfile
from backend.quant import REGIME_KEYS, dynamic_covariance, empirical_regime_returns


def test_projection_is_reproducible_and_ordered() -> None:
    profile = InvestorProfile(horizon_years=10, annual_contribution=10000, target_value=250000)
    first = _projection(100000, .06, .15, profile, 123)
    second = _projection(100000, .06, .15, profile, 123)
    assert first == second
    assert first["nominal_p10"] < first["nominal_p50"] < first["nominal_p90"]
    assert 0 <= first["goal_probability"] <= 1


@pytest.mark.parametrize(
    ("score", "state"),
    [(0, "economic_stress"), (30, "slowing_growth"), (45, "mixed_conditions"),
     (60, "steady_growth"), (75, "strong_expansion"), (100, "strong_expansion")],
)
def test_market_climate_has_one_deterministic_five_state_bucket(score: float, state: str) -> None:
    result = market_climate(score)
    assert result["climate_state"] == state
    assert len(result["climate_scale"]) == 5


def test_tax_estimate_reports_missing_cost_basis() -> None:
    profile = InvestorProfile(account_type="taxable")
    result = _tax_estimate(
        np.array([0.2, 0.8]), np.array([0.8, 0.2]),
        [{"ticker": "AAA"}, {"ticker": "BBB"}],
        [{"ticker": "AAA", "market_value": 80000}, {"ticker": "BBB", "market_value": 20000}],
        100000, profile,
    )
    assert result["available"] is False


def test_tax_deferred_account_has_zero_estimate() -> None:
    profile = InvestorProfile(account_type="roth_ira")
    result = _tax_estimate(np.array([.5]), np.array([.5]), [{"ticker": "AAA"}], [{"ticker": "AAA"}], 100000, profile)
    assert result["available"] is True
    assert result["estimated_tax"] == 0


def test_optimizer_respects_cash_floor_and_position_caps() -> None:
    research = [
        {"ticker": "CASH", "sector": "Cash", "industry": "Cash", "confidence": 100},
        {"ticker": "SPY", "sector": "Broad Market", "industry": "Large Blend", "confidence": 90},
        {"ticker": "BND", "sector": "Fixed Income", "industry": "Aggregate Bonds", "confidence": 90},
        {"ticker": "XLV", "sector": "Health Care", "industry": "Sector ETF", "confidence": 90},
        {"ticker": "XLE", "sector": "Energy", "industry": "Sector ETF", "confidence": 90},
    ]
    weights, conflicts = _optimize(
        "Risk-Controlled", np.array([.025, .07, .04, .06, .06]), np.diag([.0001, .0225, .0064, .0324, .04]),
        np.array([.10, .45, .25, .10, .10]), research, InvestorProfile(preset="preservation"),
    )
    assert not conflicts
    assert weights.sum() == pytest.approx(1)
    assert weights[0] >= .10
    assert weights[1] <= .45


def test_dynamic_covariance_is_psd_and_improves_conditioning() -> None:
    rng = np.random.default_rng(7)
    common = rng.normal(0, .01, 180)
    returns = pd.DataFrame({
        "AAA": common + rng.normal(0, .0002, 180),
        "BBB": common + rng.normal(0, .0002, 180),
        "CCC": rng.normal(0, .012, 180),
    })
    estimate = dynamic_covariance(returns, ["AAA", "BBB", "CCC"])
    assert np.linalg.eigvalsh(estimate.matrix).min() > 0
    assert 0.02 <= estimate.diagnostics["shrinkage_intensity"] <= .98
    assert estimate.diagnostics["shrunk_condition_number"] < estimate.diagnostics["raw_condition_number"]


def test_dynamic_covariance_shrinks_sparse_samples_more() -> None:
    rng = np.random.default_rng(11)
    full = pd.DataFrame(rng.normal(0, .01, (400, 4)), columns=list("ABCD"))
    sparse = full.tail(45).copy()
    sparse.loc[sparse.index[:20], "D"] = np.nan
    full_estimate = dynamic_covariance(full, list("ABCD"))
    sparse_estimate = dynamic_covariance(sparse, list("ABCD"))
    assert sparse_estimate.diagnostics["shrinkage_intensity"] > full_estimate.diagnostics["shrinkage_intensity"]


def _synthetic_history() -> tuple[pd.DataFrame, list[dict], list[dict]]:
    rng = np.random.default_rng(1234)
    dates = pd.bdate_range("2020-01-02", "2026-06-30")
    daily = pd.DataFrame({
        "SPY": rng.normal(.00025, .009, len(dates)),
        "BND": rng.normal(.00010, .004, len(dates)),
        "XLV": rng.normal(.00020, .008, len(dates)),
        "XLE": rng.normal(.00018, .012, len(dates)),
        "VTI": rng.normal(.00023, .009, len(dates)),
    }, index=dates)
    prices = 100 * (1 + daily).cumprod()
    labels = []
    for index, month_end in enumerate(pd.date_range("2020-01-31", "2026-05-31", freq="ME")):
        regime = REGIME_KEYS[index % len(REGIME_KEYS)]
        probabilities = {key: .05 for key in REGIME_KEYS}
        probabilities[regime] = .80
        labels.append({
            "as_of_date": month_end.date().isoformat(),
            "dominant_regime": regime,
            "probabilities": probabilities,
        })
    research = [
        {"ticker": "SPY", "sector": "Broad Market", "industry": "Large Blend", "confidence": 90, "expected_return": .07},
        {"ticker": "BND", "sector": "Fixed Income", "industry": "Aggregate Bonds", "confidence": 90, "expected_return": .04},
        {"ticker": "XLV", "sector": "Health Care", "industry": "Sector ETF", "confidence": 85, "expected_return": .06},
        {"ticker": "XLE", "sector": "Energy", "industry": "Sector ETF", "confidence": 80, "expected_return": .06},
        {"ticker": "CASH", "sector": "Cash", "industry": "Cash", "confidence": 100, "expected_return": .025},
    ]
    return prices, labels, research


def test_empirical_regime_returns_are_shrunk_and_point_in_time() -> None:
    prices, labels, research = _synthetic_history()
    estimate = empirical_regime_returns(
        prices, labels, research, as_of=pd.Timestamp("2024-12-31"), prior_strength=12
    )
    assert set(estimate.returns) == set(REGIME_KEYS)
    assert all(len(vector) == len(research) for vector in estimate.returns.values())
    assert estimate.diagnostics["as_of"] == "2024-12-31"
    assert estimate.diagnostics["labelled_forward_months"] < len(labels)
    for state in estimate.diagnostics["states"].values():
        assert 0 < state["average_shrinkage"] <= 1


def test_walk_forward_is_reproducible_and_has_no_train_test_overlap() -> None:
    prices, labels, research = _synthetic_history()
    static = np.array([.45, .25, .10, .10, .10])
    profile = InvestorProfile(preset="balanced")
    first = _walk_forward(prices, labels, research, profile, static)
    second = _walk_forward(prices, labels, research, profile, static)
    assert first == second
    assert first["status"] == "complete"
    assert first["period_count"] >= 5
    assert {item["name"] for item in first["benchmarks"]} == {"Equal weight", "Static current allocation"}
    assert all(item["train_end"] < item["test_start"] for item in first["periods"])


def test_price_coverage_discloses_short_history_and_sector_proxy() -> None:
    dates = pd.bdate_range("2022-01-03", "2026-06-30")
    prices = pd.DataFrame({"NEW": np.linspace(10, 20, len(dates)), "XLK": np.linspace(100, 180, len(dates))}, index=dates)
    prices.attrs["providers"] = {"NEW": "polygon", "XLK": "tiingo"}
    result = _price_coverage_diagnostics(
        prices,
        [{"ticker": "NEW", "sector": "Information Technology"}],
        ["XLK"],
    )
    assert result["insufficient_full_cycle"] == ["NEW"]
    assert result["sector_proxy_fallbacks"]["NEW"] == "XLK"
    assert result["assets"]["XLK"]["provider"] == "tiingo"
