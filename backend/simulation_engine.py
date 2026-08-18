from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from . import database
from .models import SimulationRunInput, SimulationStrategy


MODEL_VERSION = "decision-lab-block-bootstrap-v1.0.0"
SECTOR_PROXIES = {
    "Information Technology": "XLK", "Financials": "XLF", "Energy": "XLE",
    "Health Care": "XLV", "Consumer Discretionary": "XLY", "Industrials": "XLI",
    "Utilities": "XLU", "Real Estate": "XLRE", "Communication Services": "XLC",
    "Consumer Staples": "XLP", "Materials": "XLB",
}


def _current_weights(payload: SimulationRunInput) -> tuple[dict[str, float], float]:
    values: dict[str, float] = {}
    total_value = sum(float(row.market_value or 0) for row in payload.holdings)
    if total_value > 0:
        values = {row.ticker: float(row.market_value or 0) / total_value for row in payload.holdings}
    else:
        values = {row.ticker: float(row.weight or 0) for row in payload.holdings}
        total = sum(values.values())
        if total <= 0:
            values = {row.ticker: 1 / len(payload.holdings) for row in payload.holdings}
        else:
            values = {key: value / total for key, value in values.items()}
        total_value = sum(float(row.market_value or 0) for row in payload.holdings) or 100_000
    return values, total_value


def default_strategies(payload: SimulationRunInput) -> list[SimulationStrategy]:
    current, _ = _current_weights(payload)
    tickers = list(current)
    cash = current.get("CASH", 0)
    investable = [ticker for ticker in tickers if ticker != "CASH"]
    equal = {ticker: (1 - cash) / max(1, len(investable)) for ticker in investable}
    if cash:
        equal["CASH"] = cash
    cap = min(.25, max(.10, 1 / max(1, len(investable))))
    controlled = {ticker: min(value, cap) for ticker, value in current.items() if ticker != "CASH"}
    controlled["CASH"] = max(.10, cash)
    controlled_total = sum(controlled.values())
    controlled = {key: value / controlled_total for key, value in controlled.items()}
    underweights = {ticker: max(0, equal.get(ticker, 0) - current.get(ticker, 0)) for ticker in investable}
    contribution_total = sum(underweights.values())
    contributions = ({key: value / contribution_total for key, value in underweights.items()}
                     if contribution_total else equal)
    return [
        SimulationStrategy(key="current", label="Current / do nothing", weights=current),
        SimulationStrategy(key="contributions_only", label="Contributions only", weights=current, contribution_weights=contributions),
        SimulationStrategy(key="gradual", label="Gradual transition", weights=equal, transition_months=24),
        SimulationStrategy(key="immediate", label="Immediate transition", weights=equal),
        SimulationStrategy(key="risk_controlled", label="Risk-Controlled", weights=controlled),
        SimulationStrategy(key="balanced", label="Balanced", weights=equal),
    ]


def _monthly_matrix(tickers: list[str], rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    providers: dict[str, str] = {}
    warnings: list[str] = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(), providers, ["No validated adjusted-price history is available."]
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"])
    providers.update(frame.groupby("ticker")["provider"].last().to_dict())
    prices = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    monthly = prices.resample("ME").last().pct_change(fill_method=None)
    for ticker in tickers:
        if ticker == "CASH":
            monthly[ticker] = 0.0
        elif ticker not in monthly:
            warnings.append(f"{ticker} has no adjusted-price history and is excluded from empirical sampling.")
    available = [ticker for ticker in tickers if ticker in monthly]
    monthly = monthly[available].replace([np.inf, -np.inf], np.nan)
    # Common-period sampling preserves cross-security correlation. A broad-market
    # fill is disclosed when isolated gaps would otherwise discard the full month.
    if "VTI" in monthly:
        for ticker in available:
            if ticker not in {"CASH", "VTI"} and monthly[ticker].isna().any():
                missing = int(monthly[ticker].isna().sum())
                if missing:
                    monthly[ticker] = monthly[ticker].fillna(monthly["VTI"])
                    warnings.append(f"{ticker}: {missing} missing monthly returns use disclosed VTI proxy observations.")
    monthly = monthly.dropna(how="any")
    return monthly, providers, warnings


def _condition_weights(
    index: pd.DatetimeIndex,
    payload: SimulationRunInput,
    macro_rows: list[dict[str, Any]] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Condition sampling on point-in-time macro observations.

    Each requested dimension is classified independently. Months satisfying all
    supported conditions receive extra sampling weight; sparse evidence is
    automatically shrunk toward unconditional history. Unsupported dimensions do
    not receive invented seasonal proxies.
    """
    n = len(index)
    selected: list[str] = []
    masks: list[np.ndarray] = []
    unsupported: list[str] = []
    frame = pd.DataFrame(macro_rows or [])
    monthly = pd.DataFrame(index=index)
    if not frame.empty and {"series_id", "date", "value"}.issubset(frame.columns):
        frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce").dt.tz_localize(None)
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        pivot = frame.pivot_table(index="date", columns="series_id", values="value", aggfunc="last")
        monthly = pivot.resample("ME").last().reindex(index, method="ffill")

    def add_condition(label: str, mask: pd.Series | np.ndarray | None) -> None:
        selected.append(label)
        if mask is None:
            unsupported.append(label)
            return
        values = np.asarray(mask, dtype=bool)
        if values.size != n or not values.any():
            unsupported.append(label)
            return
        masks.append(values)

    if payload.scenario.economic_state != "unconditioned":
        growth = monthly.get("INDPRO")
        growth_change = growth.pct_change(6) if growth is not None else None
        state = payload.scenario.economic_state
        mask = None if growth_change is None else (
            growth_change > .005 if state == "expansion" else
            growth_change < -.005 if state == "recession" else
            growth_change.between(-.005, .005)
        )
        add_condition(f"economic:{state}", mask)
    if payload.scenario.inflation_state != "unconditioned":
        cpi = monthly.get("CPIAUCSL")
        inflation = cpi.pct_change(12) if cpi is not None else None
        acceleration = inflation.diff(6) if inflation is not None else None
        state = payload.scenario.inflation_state
        mask = None if acceleration is None else (
            acceleration > .0025 if state == "accelerating" else
            acceleration < -.0025 if state == "cooling" else
            acceleration.between(-.0025, .0025)
        )
        add_condition(f"inflation:{state}", mask)
    if payload.scenario.rate_state != "unconditioned":
        rate = monthly.get("FEDFUNDS")
        rate_change = rate.diff(6) if rate is not None else None
        state = payload.scenario.rate_state
        mask = None if rate_change is None else (
            rate_change > .25 if state == "tightening" else
            rate_change < -.25 if state == "easing" else
            rate_change.between(-.25, .25)
        )
        add_condition(f"rates:{state}", mask)
    for shock in payload.scenario.shocks:
        if shock == "oil":
            oil = monthly.get("DCOILWTICO")
            add_condition("shock:oil", None if oil is None else oil.pct_change(3) > .20)
        elif shock == "credit":
            credit = monthly.get("BAMLH0A0HYM2")
            add_condition("shock:credit", None if credit is None else credit.diff(3) > .75)
        else:
            add_condition(f"shock:{shock}", None)

    matched = np.logical_and.reduce(masks) if masks else np.zeros(n, dtype=bool)
    matched_months = int(matched.sum())
    evidence_ratio = min(1.0, matched_months / 36) if matched_months else 0.0
    dimension_coverage = len(masks) / max(1, len(selected)) if selected else 1.0
    empirical_strength = min(.75, evidence_ratio * dimension_coverage)
    empirical = np.where(matched, 1 / max(1, matched_months), 0.0)
    unconditional = np.repeat(1 / n, n)
    score = (1 - empirical_strength) * unconditional + empirical_strength * empirical
    score /= score.sum()
    return score, {
        "selected_conditions": selected or ["unconditioned"],
        "conditioning_strength": round(empirical_strength, 4),
        "shrinkage_to_unconditional": round(1 - empirical_strength, 4),
        "eligible_months": n,
        "matched_months": matched_months,
        "unsupported_conditions": unsupported,
        "classification": {
            "economic": "6-month point-in-time industrial-production change",
            "inflation": "6-month change in point-in-time 12-month CPI inflation",
            "rates": "6-month point-in-time federal-funds-rate change",
            "oil_shock": "3-month WTI increase above 20%",
            "credit_shock": "3-month high-yield spread increase above 0.75 percentage points",
        },
    }


def _bootstrap_indices(rng: np.random.Generator, months: int, history: int, block: int, probabilities: np.ndarray) -> np.ndarray:
    starts = rng.choice(history, size=math.ceil(months / block), replace=True, p=probabilities)
    indices: list[int] = []
    for start in starts:
        indices.extend((int(start) + offset) % history for offset in range(block))
    return np.asarray(indices[:months], dtype=int)


def _transition_weights(strategy: SimulationStrategy, current: np.ndarray, target: np.ndarray, month: int) -> np.ndarray:
    if strategy.transition_months <= 0:
        return target
    progress = min(1, (month + 1) / strategy.transition_months)
    weights = current + progress * (target - current)
    return weights / weights.sum()


def _drawdown_and_recovery(path: np.ndarray) -> tuple[float, int | None]:
    peaks = np.maximum.accumulate(path)
    drawdowns = path / np.maximum(peaks, 1e-12) - 1
    trough = int(np.argmin(drawdowns))
    peak_value = peaks[trough]
    recovered = np.where(path[trough + 1:] >= peak_value)[0]
    return float(drawdowns[trough]), (int(recovered[0] + 1) if len(recovered) else None)


def _histogram(values: np.ndarray, bins: int = 16) -> dict[str, list[float | int]]:
    counts, edges = np.histogram(values, bins=bins)
    return {
        "edges": [round(float(value), 4) for value in edges],
        "counts": [int(value) for value in counts],
    }


def _robust_weights(sampled: np.ndarray, current: np.ndarray, mode: str) -> tuple[np.ndarray, list[str]]:
    n = sampled.shape[2]
    max_weight = .35
    if max_weight * n < 1:
        return current, [f"A {max_weight:.0%} position cap is infeasible with only {n} simulated assets."]
    # Each path supplies a different compounded asset outcome. Optimizing this
    # distribution avoids treating one point expected-return estimate as truth.
    path_asset_returns = np.prod(1 + sampled, axis=1) - 1
    downside_weight = 1.6 if mode == "risk_controlled" else .8
    return_weight = .35 if mode == "risk_controlled" else .75
    concentration_weight = .8 if mode == "risk_controlled" else .4
    turnover_weight = .25
    def loss(weights: np.ndarray) -> float:
        outcomes = path_asset_returns @ weights
        worst = np.sort(outcomes)[:max(1, int(.10 * len(outcomes)))]
        cvar_loss = -float(worst.mean())
        variance = float(np.var(outcomes))
        return (
            -return_weight * float(np.mean(outcomes)) + downside_weight * cvar_loss
            + .35 * variance + concentration_weight * float(np.sum(weights ** 2))
            + turnover_weight * float(np.abs(weights - current).sum() / 2)
        )
    result = minimize(
        loss, current, method="SLSQP", bounds=[(0, max_weight)] * n,
        constraints=[{"type": "eq", "fun": lambda weights: weights.sum() - 1}],
        options={"maxiter": 400, "ftol": 1e-9},
    )
    if not result.success:
        return current, [f"Robust optimizer infeasible: {result.message}"]
    return result.x, []


def run_simulation(
    payload: SimulationRunInput,
    price_rows: list[dict[str, Any]] | None = None,
    *,
    price_limit_per_ticker: int = 10000,
) -> dict[str, Any]:
    strategies = payload.strategies or default_strategies(payload)
    current_map, initial_value = _current_weights(payload)
    tickers = sorted(set(current_map) | {ticker for strategy in strategies for ticker in strategy.weights})
    query_tickers = sorted(set(tickers) | {"VTI"})
    rows = price_rows if price_rows is not None else database.price_history(
        query_tickers, max(504, min(price_limit_per_ticker, 10000))
    )
    monthly, providers, warnings = _monthly_matrix(query_tickers, rows)
    if len(monthly) < 24:
        raise ValueError("At least 24 common monthly adjusted-price observations are required for simulation")
    asset_tickers = [ticker for ticker in tickers if ticker in monthly]
    if not asset_tickers:
        raise ValueError("No requested holdings have usable adjusted-price history")
    returns = monthly[asset_tickers].to_numpy(dtype=float)
    macro_rows = [] if price_rows is not None else database.macro_point_in_time_history(
        ["INDPRO", "CPIAUCSL", "FEDFUNDS", "DCOILWTICO", "BAMLH0A0HYM2"],
        limit_per_series=1000,
    )
    probabilities, conditioning = _condition_weights(monthly.index, payload, macro_rows)
    horizon_years = payload.horizon_years or payload.profile.horizon_years
    months = horizon_years * 12
    rng = np.random.default_rng(payload.seed)
    sampled = np.stack([
        returns[_bootstrap_indices(rng, months, len(monthly), payload.block_months, probabilities)]
        for _ in range(payload.paths)
    ])
    fingerprint = hashlib.sha256(sampled[:, :, :].tobytes()).hexdigest()[:24]
    annual_contribution = payload.profile.annual_contribution
    annual_withdrawal = payload.profile.annual_withdrawal
    monthly_flow = (annual_contribution - annual_withdrawal) / 12
    fund_data = database.fund_reference_data(asset_tickers) if price_rows is None else {"funds": [], "holdings": []}
    expense = {row["ticker"]: float(row.get("expense_ratio") or 0) for row in fund_data.get("funds", [])}
    current_vector = np.asarray([current_map.get(ticker, 0) for ticker in asset_tickers], dtype=float)
    if current_vector.sum() <= 0:
        current_vector = np.repeat(1 / len(asset_tickers), len(asset_tickers))
    else:
        current_vector /= current_vector.sum()
    optimizer_diagnostics: list[str] = []
    if not payload.strategies:
        robust_by_key = {}
        for key in ("risk_controlled", "balanced"):
            robust, conflicts = _robust_weights(sampled, current_vector, key)
            optimizer_diagnostics.extend(conflicts)
            robust_by_key[key] = {ticker: float(robust[index]) for index, ticker in enumerate(asset_tickers)}
        strategies = [
            SimulationStrategy(
                key=strategy.key, label=strategy.label,
                weights=robust_by_key.get(strategy.key, strategy.weights),
                transition_months=strategy.transition_months,
                contribution_weights=strategy.contribution_weights,
            )
            for strategy in strategies
        ]
    outcomes: list[dict[str, Any]] = []
    terminal_by_strategy: dict[str, np.ndarray] = {}
    for strategy in strategies:
        target = np.asarray([strategy.weights.get(ticker, 0) for ticker in asset_tickers], dtype=float)
        target = target / target.sum() if target.sum() else current_vector.copy()
        contribution_weights = np.asarray([strategy.contribution_weights.get(ticker, 0) for ticker in asset_tickers], dtype=float)
        if contribution_weights.sum() <= 0:
            contribution_weights = target
        else:
            contribution_weights /= contribution_weights.sum()
        values = np.full(payload.paths, initial_value, dtype=float)
        paths = np.empty((payload.paths, months + 1), dtype=float)
        paths[:, 0] = values
        total_fees = np.zeros(payload.paths)
        for month in range(months):
            if strategy.key == "contributions_only" and monthly_flow > 0:
                contributed = monthly_flow * month
                weights = current_vector * initial_value + contribution_weights * contributed
                weights = weights / weights.sum()
            else:
                weights = _transition_weights(strategy, current_vector, target, month)
            gross = sampled[:, month, :] @ weights
            fee_rate = sum(weights[index] * expense.get(ticker, 0) for index, ticker in enumerate(asset_tickers)) / 12
            fee = values * fee_rate
            total_fees += fee
            values = np.maximum(0, values * (1 + gross) - fee + monthly_flow)
            paths[:, month + 1] = values
        drawdowns, recoveries = zip(*(_drawdown_and_recovery(path) for path in paths))
        terminal_by_strategy[strategy.key] = values
        turnover = float(np.abs(target - current_vector).sum() / 2)
        taxable_gain = max(0, initial_value * turnover * .20) if payload.profile.account_type == "taxable" else 0
        estimated_tax = taxable_gain * payload.profile.tax_rate
        goal_results = []
        for goal in payload.goals:
            goal_month = min(months, max(1, math.ceil((goal.target_date - datetime.now().date()).days / 30.4375)))
            goal_values = paths[:, goal_month]
            goal_results.append({
                "goal_id": goal.id, "name": goal.name, "target": goal.target_amount,
                "probability": round(float(np.mean(goal_values >= goal.target_amount)), 4),
                "median": round(float(np.percentile(goal_values, 50)), 2),
                "median_shortfall": round(float(max(0, goal.target_amount - np.percentile(goal_values, 50))), 2),
            })
        terminal = values
        inflation_factor = (1 + payload.profile.inflation_rate) ** horizon_years
        real_terminal = terminal / inflation_factor
        outcome = {
            "strategy_key": strategy.key,
            "label": strategy.label,
            "wealth_percentiles": {key: round(float(np.percentile(terminal, value)), 2) for key, value in (("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90))},
            "real_wealth_percentiles": {key: round(float(np.percentile(real_terminal, value)), 2) for key, value in (("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90))},
            "probability_of_loss": round(float(np.mean(terminal < initial_value)), 4),
            "drawdown_percentiles": {key: round(float(np.percentile(drawdowns, value)), 4) for key, value in (("p10", 10), ("p50", 50), ("p90", 90))},
            "recovery_months": {
                "median": round(float(np.median([value for value in recoveries if value is not None])), 1) if any(value is not None for value in recoveries) else None,
                "unrecovered_share": round(sum(value is None for value in recoveries) / len(recoveries), 4),
            },
            "goal_results": goal_results,
            "turnover": round(turnover, 4),
            "estimated_taxes": round(estimated_tax, 2),
            "estimated_fees": round(float(np.mean(total_fees)), 2),
            "concentration": {"largest_weight": round(float(target.max()), 4), "effective_holdings": round(float(1 / max(np.sum(target ** 2), 1e-9)), 2)},
            "scenario_summary": conditioning,
            "regret": 0.0,
            "robustness": "Pending cross-strategy comparison",
            "representative_paths": [[round(float(value), 2) for value in paths[index, ::max(1, months // 24)]] for index in (0, payload.paths // 2, payload.paths - 1)],
            "histograms": {
                "terminal_wealth": _histogram(terminal),
                "real_terminal_wealth": _histogram(real_terminal),
                "maximum_drawdown": _histogram(np.asarray(drawdowns)),
            },
        }
        outcomes.append(outcome)
    best_per_path = np.max(np.stack(list(terminal_by_strategy.values())), axis=0)
    for outcome in outcomes:
        terminal = terminal_by_strategy[outcome["strategy_key"]]
        regret = np.median(best_per_path - terminal)
        outcome["regret"] = round(float(regret), 2)
        outcome["robustness"] = "High" if outcome["probability_of_loss"] < .15 and outcome["drawdown_percentiles"]["p10"] > -.35 else "Moderate" if outcome["probability_of_loss"] < .30 else "Low"
    effective = monthly.index.max().date().isoformat()
    return {
        "id": str(uuid.uuid4()), "input": payload.model_dump(mode="json"), "outcomes": outcomes,
        "shared_path_fingerprint": fingerprint, "model_version": MODEL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lineage": [{
            "provider": "+".join(sorted(set(providers.values()))) or "fixture",
            "dataset": "monthly corporate-action-adjusted returns", "effective_through": effective,
            "symbols": asset_tickers, "calculation_version": MODEL_VERSION,
        }],
        "assumptions": [
            f"{payload.paths:,} reproducible {payload.block_months}-month block-bootstrap paths.",
            "All strategies use identical sampled market periods so comparisons are paired.",
            "Common historical periods preserve observed cross-security correlations.",
            "Sparse scenario conditioning is explicitly shrunk toward unconditional history.",
            f"Inflation-adjusted wealth uses the saved {payload.profile.inflation_rate:.2%} annual inflation assumption.",
            "Taxes are aggregate approximations; tax lots, wash sales, and execution are excluded.",
        ],
        "warnings": [*warnings, *optimizer_diagnostics],
        "optimizer": {
            "method": "paired-path robust objective with expected real return, 10% conditional downside, variance, concentration, and turnover",
            "version": "robust-path-optimizer-v1.0.0",
            "constraint_status": "infeasible" if optimizer_diagnostics else "satisfied",
            "diagnostics": optimizer_diagnostics,
        },
        "coverage": {
            "start": monthly.index.min().date().isoformat(), "end": effective,
            "monthly_observations": len(monthly), "symbols_requested": tickers,
            "symbols_simulated": asset_tickers,
        },
    }


def goal_projection(payload: Any) -> dict[str, Any]:
    """Compatibility adapter so Plan and Decision Lab share one path model."""
    goal = payload.goal
    years = max(1, math.ceil((goal.target_date - datetime.now().date()).days / 365.25))
    rng = np.random.default_rng(sum(ord(char) for char in f"{goal.name}|{goal.target_date}|{payload.risk_tolerance}"))
    proxy_rows = database.price_history(["VTI", "BND"], 10000)
    proxy_monthly, _, _ = _monthly_matrix(["VTI", "BND"], proxy_rows)
    if not proxy_monthly.empty and len(proxy_monthly) >= 24:
        equity_weight = min(.90, max(.25, .30 + payload.risk_tolerance * .06))
        if "VTI" in proxy_monthly and "BND" in proxy_monthly:
            history = (proxy_monthly["VTI"] * equity_weight + proxy_monthly["BND"] * (1 - equity_weight)).to_numpy()
        else:
            history = proxy_monthly.iloc[:, 0].to_numpy()
        history_source = "VTI/BND adjusted monthly history"
    else:
        # Deterministic local/test fallback; production disclosures make the absence explicit.
        history = rng.normal((.03 + payload.risk_tolerance * .006) / 12, (.05 + payload.risk_tolerance * .012) / math.sqrt(12), 240)
        history_source = "seeded balanced proxy because stored VTI/BND history is unavailable"
    indices = np.stack([_bootstrap_indices(rng, years * 12, len(history), 6, np.repeat(1 / len(history), len(history))) for _ in range(5000)])
    sampled = history[indices]
    contribution = (goal.annual_contribution + payload.additional_annual_contribution) / 12
    paths = np.full(5000, goal.current_value, dtype=float)
    extra_paths = paths.copy()
    lower_risk_paths = paths.copy()
    for month in range(years * 12):
        paths = np.maximum(0, paths * (1 + sampled[:, month]) + contribution)
        extra_paths = np.maximum(0, extra_paths * (1 + sampled[:, month]) + contribution + 300)
        lower_month = sampled[:, month] * .70 + .025 / 12
        lower_risk_paths = np.maximum(0, lower_risk_paths * (1 + lower_month) + contribution)
    probability = float(np.mean(paths >= goal.target_amount))
    median = float(np.percentile(paths, 50))
    return {
        "goal_id": goal.id, "as_of": datetime.now().date().isoformat(), "years": years,
        "nominal_p10": round(float(np.percentile(paths, 10)), 2), "nominal_p50": round(median, 2),
        "nominal_p90": round(float(np.percentile(paths, 90)), 2),
        "real_p50": round(median / ((1.025) ** years) if goal.inflation_adjusted else median, 2),
        "goal_probability": round(probability, 4),
        "required_annual_contribution": round(max(0, goal.target_amount - median) / max(1, years), 2),
        "on_track_range": "strong" if probability >= .75 else "moderate" if probability >= .45 else "needs attention",
        "earliest_plausible_goal_date": goal.target_date.isoformat(),
        "monthly_contribution_adjustment": round(max(0, goal.target_amount - median) / max(1, years * 12), 2),
        "contribution_comparison": {
            "additional_monthly": 300, "projected_median": round(float(np.median(extra_paths)), 2),
            "median_improvement": round(float(np.median(extra_paths) - median), 2),
            "goal_probability": round(float(np.mean(extra_paths >= goal.target_amount)), 4),
        },
        "lower_risk_comparison": {
            "projected_median": round(float(np.median(lower_risk_paths)), 2),
            "median_difference": round(float(np.median(lower_risk_paths) - median), 2),
            "goal_probability": round(float(np.mean(lower_risk_paths >= goal.target_amount)), 4),
            "return_assumption": .025,
        },
        "most_influential_assumptions": [f"{years}-year horizon", f"${goal.annual_contribution:,.0f} annual contribution", "2.5% inflation"],
        "assumptions": ["5,000 seeded monthly block-bootstrap paths", history_source],
        "limitations": ["Planning range, not a guarantee.", "Attach a portfolio in Decision Lab for security-level history, fees, and tax estimates."],
        "model_version": MODEL_VERSION,
        "calculation": {"method": "monthly_historical_block_bootstrap", "version": "goal-projection-v2", "engine_version": MODEL_VERSION},
    }
