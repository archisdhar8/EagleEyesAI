from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


TRADING_DAYS = 252
MONTHS_PER_YEAR = 12
REGIME_KEYS = (
    "soft_landing",
    "sticky_inflation",
    "recession_cuts",
    "growth_reacceleration",
    "oil_shock",
)
SECTOR_PROXIES = {
    "Broad Market": "VTI",
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Financials": "XLF",
    "Industrials": "XLI",
    "Fixed Income": "BND",
}


@dataclass(frozen=True)
class CovarianceEstimate:
    matrix: np.ndarray
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class RegimeEstimate:
    returns: dict[str, np.ndarray]
    diagnostics: dict[str, Any]


def _condition_number(matrix: np.ndarray) -> float:
    if matrix.size == 0:
        return 0.0
    eigenvalues = np.linalg.eigvalsh((matrix + matrix.T) / 2)
    positive = eigenvalues[eigenvalues > 1e-12]
    if len(positive) == 0:
        return float("inf")
    return float(positive.max() / positive.min())


def _effective_rank(matrix: np.ndarray) -> float:
    eigenvalues = np.maximum(np.linalg.eigvalsh((matrix + matrix.T) / 2), 0)
    total = float(eigenvalues.sum())
    if total <= 0:
        return 0.0
    probabilities = eigenvalues[eigenvalues > 0] / total
    return float(math.exp(-float(np.sum(probabilities * np.log(probabilities)))))


def dynamic_covariance(
    returns: pd.DataFrame,
    tickers: list[str],
    fallback_volatility: dict[str, float] | None = None,
) -> CovarianceEstimate:
    """Estimate a PSD covariance matrix with data-dependent shrinkage.

    The target keeps each asset's variance and replaces unstable pairwise
    correlations with the observed cross-sectional average correlation.
    """
    fallback_volatility = fallback_volatility or {}
    frame = returns.reindex(columns=tickers).replace([np.inf, -np.inf], np.nan).copy()
    counts = frame.count().astype(int)
    if len(frame):
        lower = frame.quantile(0.01)
        upper = frame.quantile(0.99)
        frame = frame.clip(lower=lower, upper=upper, axis=1)
    fallback_variances = np.array([
        fallback_volatility.get(ticker, 0.01 if ticker == "CASH" else 0.25) ** 2 / TRADING_DAYS
        for ticker in tickers
    ])
    if frame.empty:
        daily = np.diag(fallback_variances)
        return CovarianceEstimate(
            daily * TRADING_DAYS,
            {
                "method": "constant-correlation shrinkage",
                "target": "fallback diagonal",
                "sample_count": 0,
                "shrinkage_intensity": 1.0,
                "raw_condition_number": None,
                "shrunk_condition_number": round(_condition_number(daily), 3),
                "effective_rank": round(_effective_rank(daily), 3),
                "minimum_eigenvalue": round(float(np.linalg.eigvalsh(daily * TRADING_DAYS).min()), 10),
                "imputed_fraction": 1.0,
                "asset_observations": {ticker: 0 for ticker in tickers},
            },
        )

    sample = frame.cov(min_periods=20).reindex(index=tickers, columns=tickers).to_numpy(dtype=float)
    observed_variances = np.diag(sample).copy()
    for index, ticker in enumerate(tickers):
        if not np.isfinite(observed_variances[index]) or counts.get(ticker, 0) < 20:
            observed_variances[index] = fallback_variances[index]
    standard_deviations = np.sqrt(np.maximum(observed_variances, 1e-12))
    correlations = sample / np.outer(standard_deviations, standard_deviations)
    off_diagonal = correlations[np.triu_indices(len(tickers), 1)]
    finite_correlations = off_diagonal[np.isfinite(off_diagonal)]
    average_correlation = float(np.clip(finite_correlations.mean(), -0.25, 0.75)) if len(finite_correlations) else 0.0
    target = average_correlation * np.outer(standard_deviations, standard_deviations)
    np.fill_diagonal(target, observed_variances)
    sample = np.where(np.isfinite(sample), sample, target)
    sample = (sample + sample.T) / 2

    centered = frame - frame.mean()
    imputed = centered.fillna(0.0).to_numpy(dtype=float)
    effective_n = max(1, int(np.median(counts[counts > 0])) if (counts > 0).any() else len(frame))
    phi = 0.0
    for row in imputed:
        difference = np.outer(row, row) - sample
        phi += float(np.sum(difference * difference))
    phi /= max(len(imputed), 1)
    gamma = float(np.sum((sample - target) ** 2))
    analytical = 1.0 if gamma <= 1e-18 else float(np.clip(phi / (effective_n * gamma), 0, 1))
    imputed_fraction = float(frame.isna().sum().sum() / max(frame.size, 1))
    sparse_penalty = max(0.0, (120 - min(effective_n, 120)) / 120) * 0.5
    coverage_penalty = float(np.clip(imputed_fraction * 0.8 + sparse_penalty, 0, 1))
    shrinkage = float(np.clip(analytical * 0.65 + coverage_penalty * 0.35, 0.02, 0.98))
    shrunk = (1 - shrinkage) * sample + shrinkage * target
    eigenvalues, eigenvectors = np.linalg.eigh((shrunk + shrunk.T) / 2)
    floor = max(float(np.trace(shrunk)) / max(len(tickers), 1) * 1e-8, 1e-12)
    shrunk = eigenvectors @ np.diag(np.maximum(eigenvalues, floor)) @ eigenvectors.T
    annualized = (shrunk + shrunk.T) / 2 * TRADING_DAYS
    return CovarianceEstimate(
        annualized,
        {
            "method": "dynamic Ledoit-Wolf-style constant-correlation shrinkage",
            "target": "constant correlation with observed/fallback variances",
            "sample_count": effective_n,
            "shrinkage_intensity": round(shrinkage, 6),
            "average_target_correlation": round(average_correlation, 6),
            "raw_condition_number": round(_condition_number(sample), 3),
            "shrunk_condition_number": round(_condition_number(shrunk), 3),
            "effective_rank": round(_effective_rank(shrunk), 3),
            "minimum_eigenvalue": round(float(np.linalg.eigvalsh(annualized).min()), 10),
            "imputed_fraction": round(imputed_fraction, 6),
            "asset_observations": {ticker: int(counts.get(ticker, 0)) for ticker in tickers},
        },
    )


def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=prices.columns)
    frame = prices.copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(None)
    return frame.sort_index().resample("ME").last().pct_change(fill_method=None)


def empirical_regime_returns(
    prices: pd.DataFrame,
    labels: Iterable[dict[str, Any]],
    research: list[dict[str, Any]],
    *,
    as_of: pd.Timestamp | None = None,
    prior_strength: float = 12.0,
) -> RegimeEstimate:
    tickers = [row["ticker"] for row in research]
    monthly = monthly_returns(prices)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None) if pd.Timestamp(as_of).tzinfo else pd.Timestamp(as_of)
        monthly = monthly[monthly.index <= cutoff]
    indexed_labels: dict[pd.Period, dict[str, Any]] = {}
    for label in labels:
        label_date = pd.Timestamp(label["as_of_date"])
        if as_of is not None and label_date > pd.Timestamp(as_of):
            continue
        indexed_labels[label_date.to_period("M")] = label

    samples: dict[str, list[pd.Series]] = {key: [] for key in REGIME_KEYS}
    for return_date, row in monthly.iterrows():
        prior_period = return_date.to_period("M") - 1
        label = indexed_labels.get(prior_period)
        if label and label.get("dominant_regime") in samples:
            samples[label["dominant_regime"]].append(row)

    unconditional = monthly.mean(skipna=True) * MONTHS_PER_YEAR if not monthly.empty else pd.Series(dtype=float)
    global_prior = float(unconditional.median(skipna=True)) if len(unconditional.dropna()) else 0.05
    estimates: dict[str, np.ndarray] = {}
    state_diagnostics: dict[str, Any] = {}
    for regime in REGIME_KEYS:
        sample_frame = pd.DataFrame(samples[regime]) if samples[regime] else pd.DataFrame(columns=monthly.columns)
        vector: list[float] = []
        shrinkages: list[float] = []
        per_asset_counts: dict[str, int] = {}
        for item in research:
            ticker = item["ticker"]
            values = sample_frame[ticker].dropna() if ticker in sample_frame else pd.Series(dtype=float)
            count = len(values)
            per_asset_counts[ticker] = count
            raw_mean = float(values.mean() * MONTHS_PER_YEAR) if count else math.nan
            proxy_ticker = SECTOR_PROXIES.get(item.get("sector", ""), "VTI")
            proxy_values = sample_frame[proxy_ticker].dropna() if proxy_ticker in sample_frame else pd.Series(dtype=float)
            proxy_mean = float(proxy_values.mean() * MONTHS_PER_YEAR) if len(proxy_values) else math.nan
            own_unconditional = float(unconditional.get(ticker, math.nan))
            prior_parts = [value for value in (proxy_mean, own_unconditional, global_prior) if np.isfinite(value)]
            prior = float(np.mean(prior_parts)) if prior_parts else global_prior
            weight = count / (count + prior_strength)
            estimate = prior if not np.isfinite(raw_mean) else weight * raw_mean + (1 - weight) * prior
            if ticker == "CASH":
                estimate = 0.025
                weight = 0.0
            vector.append(float(np.clip(estimate, -0.35, 0.35)))
            shrinkages.append(1 - weight)
        estimates[regime] = np.array(vector, dtype=float)
        state_diagnostics[regime] = {
            "regime_months": len(sample_frame),
            "median_asset_samples": int(np.median(list(per_asset_counts.values()))) if per_asset_counts else 0,
            "average_shrinkage": round(float(np.mean(shrinkages)), 6) if shrinkages else 1.0,
            "asset_samples": per_asset_counts,
        }
    return RegimeEstimate(
        estimates,
        {
            "method": "next-month empirical returns by point-in-time dominant regime",
            "annualization": "monthly arithmetic mean × 12",
            "prior": "sector ETF proxy + asset unconditional mean + cross-sectional median",
            "prior_strength_months": prior_strength,
            "states": state_diagnostics,
            "available_months": int(len(monthly)),
            "labelled_forward_months": int(sum(len(value) for value in samples.values())),
            "as_of": None if as_of is None else str(pd.Timestamp(as_of).date()),
        },
    )


def portfolio_path_metrics(daily_returns: pd.Series) -> dict[str, float | int | None]:
    values = daily_returns.dropna().astype(float)
    if values.empty:
        return {
            "observations": 0, "annualized_return": None, "annualized_volatility": None,
            "max_drawdown": None, "sharpe": None,
        }
    wealth = (1 + values).cumprod()
    years = len(values) / TRADING_DAYS
    annualized_return = float(wealth.iloc[-1] ** (1 / years) - 1) if years > 0 and wealth.iloc[-1] > 0 else -1.0
    volatility = float(values.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(values) > 1 else 0.0
    drawdown = wealth / wealth.cummax() - 1
    return {
        "observations": int(len(values)),
        "annualized_return": round(annualized_return, 6),
        "annualized_volatility": round(volatility, 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "sharpe": round(annualized_return / volatility, 6) if volatility > 1e-9 else None,
    }
