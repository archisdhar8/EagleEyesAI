import numpy as np
import pytest

from backend.analysis import _optimize, _projection, _tax_estimate
from backend.models import InvestorProfile


def test_projection_is_reproducible_and_ordered() -> None:
    profile = InvestorProfile(horizon_years=10, annual_contribution=10000, target_value=250000)
    first = _projection(100000, .06, .15, profile, 123)
    second = _projection(100000, .06, .15, profile, 123)
    assert first == second
    assert first["nominal_p10"] < first["nominal_p50"] < first["nominal_p90"]
    assert 0 <= first["goal_probability"] <= 1


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
