from __future__ import annotations

"""Canonical deterministic calculations shared by Research and Ask.

The functions in this module are deliberately provider- and UI-agnostic.  A
missing prerequisite produces ``None``; no calculation substitutes zero, a
neutral score, or a current fundamental value for a historical observation.
"""

import math
from datetime import date, datetime, timezone
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


VERSION = "research-metrics-v2.0.0"
TRADING_DAYS = 252


ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "gross_profit": ("gross_profit", "GrossProfit"),
    "operating_income": ("operating_income", "OperatingIncomeLoss"),
    "net_income": ("net_income", "NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("eps_diluted", "EarningsPerShareDiluted"),
    "operating_cash_flow": ("operating_cash_flow", "NetCashProvidedByUsedInOperatingActivities"),
    "capex": ("capex", "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "cash": ("cash", "CashAndCashEquivalentsAtCarryingValue"),
    "total_debt": ("total_debt", "LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"),
    "equity": ("shareholder_equity", "equity", "StockholdersEquity"),
    "total_assets": ("total_assets", "assets", "Assets"),
    "total_liabilities": ("total_liabilities", "liabilities", "Liabilities"),
    "shares_diluted": ("shares_diluted", "WeightedAverageNumberOfDilutedSharesOutstanding"),
    "shares_outstanding": ("shares_outstanding", "EntityCommonStockSharesOutstanding"),
    "depreciation_amortization": (
        "depreciation_amortization", "DepreciationDepletionAndAmortization",
        "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment", "DepreciationAmortizationAndOther",
    ),
    "income_tax_expense": ("income_tax_expense", "IncomeTaxExpenseBenefit"),
    "pretax_income": ("pretax_income", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
}


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def metric(row: Mapping[str, Any] | None, name: str) -> float | None:
    values = (row or {}).get("metrics") if isinstance(row, Mapping) else None
    values = values if isinstance(values, Mapping) else (row or {})
    for key in ALIASES.get(name, (name,)):
        value = number(values.get(key))
        if value is not None:
            return value
    return None


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    n, d = number(numerator), number(denominator)
    return n / d if n is not None and d not in (None, 0) else None


def growth(current: Any, previous: Any, *, positive_base: bool = False) -> float | None:
    current_value, previous_value = number(current), number(previous)
    if current_value is None or previous_value is None or previous_value == 0:
        return None
    if positive_base and previous_value <= 0:
        return None
    return current_value / previous_value - 1


def _period_key(row: Mapping[str, Any]) -> tuple[Any, Any]:
    return (str(row.get("fiscal_period") or "").upper(), row.get("fiscal_year"))


def aligned_previous(rows: Sequence[Mapping[str, Any]], current: Mapping[str, Any]) -> Mapping[str, Any] | None:
    fiscal_period, fiscal_year = _period_key(current)
    candidates = [row for row in rows if fiscal_period and fiscal_year is not None and _period_key(row) == (fiscal_period, int(fiscal_year) - 1)]
    if not candidates and current.get("period_end"):
        try:
            current_end = date.fromisoformat(str(current["period_end"])[:10])
            duration = _duration_days(current)
            candidates = [
                row for row in rows
                if row is not current and row.get("period_end") and duration is not None
                and _duration_days(row) is not None and abs((_duration_days(row) or 0) - duration) <= 7
                and 330 <= (current_end - date.fromisoformat(str(row["period_end"])[:10])).days <= 400
            ]
        except ValueError:
            candidates = []
    return max(candidates, key=lambda row: str(row.get("period_end") or ""), default=None)


def _duration_days(row: Mapping[str, Any]) -> int | None:
    if row.get("period_start") and row.get("period_end"):
        try:
            start = date.fromisoformat(str(row["period_start"])[:10])
            end = date.fromisoformat(str(row["period_end"])[:10])
            return (end - start).days
        except ValueError:
            return None
    if row.get("context_ids") and not row.get("period_start"):
        return None
    period = str(row.get("fiscal_period") or "").upper()
    return 365 if period == "FY" else 91 if period.startswith("Q") else None


def _annual_period(rows: Sequence[Mapping[str, Any]], field: str) -> Mapping[str, Any] | None:
    candidates = [row for row in rows if metric(row, field) is not None and 300 <= (_duration_days(row) or 0) <= 380]
    return max(candidates, key=lambda row: str(row.get("period_end") or ""), default=None)


def ttm(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    """Return a point-in-time-safe trailing value.

    Four discrete 70–120 day quarters are preferred.  If duration metadata is
    absent or the quarters overlap/YTD, the latest completed annual fact is the
    only safe fallback.
    """
    quarters = [row for row in rows if metric(row, field) is not None and 70 <= (_duration_days(row) or 0) <= 120]
    quarters = sorted(quarters, key=lambda row: str(row.get("period_end") or ""), reverse=True)
    selected: list[Mapping[str, Any]] = []
    for row in quarters:
        if row.get("period_end") not in {item.get("period_end") for item in selected}:
            selected.append(row)
        if len(selected) == 4:
            break
    if len(selected) == 4:
        return sum(metric(row, field) or 0.0 for row in selected)
    annual = _annual_period(rows, field)
    return metric(annual, field) if annual else None


def latest_instant(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    candidates = [row for row in rows if metric(row, field) is not None]
    row = max(candidates, key=lambda item: str(item.get("period_end") or ""), default=None)
    return metric(row, field) if row else None


def instant_at(rows: Sequence[Mapping[str, Any]], field: str, period_end: Any) -> float | None:
    candidates = [row for row in rows if str(row.get("period_end") or "")[:10] == str(period_end or "")[:10] and metric(row, field) is not None]
    row = max(candidates, key=lambda item: str(item.get("filed_at") or ""), default=None)
    return metric(row, field) if row else None


def financial_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("period_end") or ""), reverse=True)
    current = next((row for row in ordered if metric(row, "revenue") is not None), None)
    previous = aligned_previous(ordered, current) if current else None
    revenue = metric(current, "revenue")
    previous_revenue = metric(previous, "revenue")
    eps = metric(current, "eps_diluted")
    previous_eps = metric(previous, "eps_diluted")
    gross_margin = safe_ratio(metric(current, "gross_profit"), revenue)
    previous_gross_margin = safe_ratio(metric(previous, "gross_profit"), previous_revenue)
    operating_margin = safe_ratio(metric(current, "operating_income"), revenue)
    previous_operating_margin = safe_ratio(metric(previous, "operating_income"), previous_revenue)
    net_margin = safe_ratio(metric(current, "net_income"), revenue)
    cash_flow_period = next((row for row in ordered if metric(row, "operating_cash_flow") is not None
                             and metric(row, "capex") is not None and metric(row, "revenue") is not None), None)
    operating_cash_flow = metric(cash_flow_period, "operating_cash_flow")
    capex = metric(cash_flow_period, "capex")
    fcf = operating_cash_flow - abs(capex) if operating_cash_flow is not None and capex is not None else None
    cash = latest_instant(ordered, "cash")
    debt = latest_instant(ordered, "total_debt")
    shares = metric(current, "shares_diluted") or latest_instant(ordered, "shares_outstanding")
    prior_shares = metric(previous, "shares_diluted") if previous else None

    # ROIC = NOPAT / average(debt + equity - cash).  A reported effective tax
    # rate is required and clipped to [0, 50%] to reject sign/pathology artifacts.
    annual = _annual_period(ordered, "operating_income")
    annual_previous = aligned_previous(ordered, annual) if annual else None
    op_income = metric(annual, "operating_income")
    tax_rate = safe_ratio(metric(annual, "income_tax_expense"), metric(annual, "pretax_income"))
    if tax_rate is not None:
        tax_rate = min(.5, max(0.0, tax_rate))
    invested_now = None
    if annual:
        values = (instant_at(ordered, "total_debt", annual.get("period_end")),
                  instant_at(ordered, "equity", annual.get("period_end")),
                  instant_at(ordered, "cash", annual.get("period_end")))
        if all(value is not None for value in values):
            invested_now = values[0] + values[1] - values[2]  # type: ignore[operator]
    invested_prior = None
    if annual_previous:
        values = (instant_at(ordered, "total_debt", annual_previous.get("period_end")),
                  instant_at(ordered, "equity", annual_previous.get("period_end")),
                  instant_at(ordered, "cash", annual_previous.get("period_end")))
        if all(value is not None for value in values):
            invested_prior = values[0] + values[1] - values[2]  # type: ignore[operator]
    average_invested = (invested_now + invested_prior) / 2 if invested_now is not None and invested_prior is not None else invested_now
    roic = safe_ratio(op_income * (1 - tax_rate), average_invested) if op_income is not None and tax_rate is not None else None

    ttm_revenue = ttm(ordered, "revenue")
    ttm_eps = ttm(ordered, "eps_diluted")
    ttm_ocf = ttm(ordered, "operating_cash_flow")
    ttm_capex = ttm(ordered, "capex")
    ttm_fcf = ttm_ocf - abs(ttm_capex) if ttm_ocf is not None and ttm_capex is not None else None
    ttm_operating_income = ttm(ordered, "operating_income")
    ttm_da = ttm(ordered, "depreciation_amortization")
    ttm_ebitda = ttm_operating_income + ttm_da if ttm_operating_income is not None and ttm_da is not None else None
    acceleration = None
    if current and previous:
        prior_aligned = aligned_previous(ordered, previous)
        previous_growth = growth(previous_revenue, metric(prior_aligned, "revenue"))
        current_growth = growth(revenue, previous_revenue)
        acceleration = current_growth - previous_growth if current_growth is not None and previous_growth is not None else None
    else:
        current_growth = None
    return {
        "as_of": current.get("period_end") if current else None,
        "revenue_growth_yoy": current_growth,
        "revenue_growth_acceleration": acceleration,
        "eps_growth_yoy": growth(eps, previous_eps, positive_base=True),
        "gross_margin": gross_margin,
        "gross_margin_change_bps": (gross_margin - previous_gross_margin) * 10_000 if gross_margin is not None and previous_gross_margin is not None else None,
        "operating_margin": operating_margin,
        "operating_margin_change_bps": (operating_margin - previous_operating_margin) * 10_000 if operating_margin is not None and previous_operating_margin is not None else None,
        "net_margin": net_margin,
        "free_cash_flow": fcf,
        "fcf_margin": safe_ratio(fcf, metric(cash_flow_period, "revenue")),
        "cash": cash,
        "debt": debt,
        "net_cash_debt": cash - debt if cash is not None and debt is not None else None,
        "shares_diluted": shares,
        "share_count_change": growth(shares, prior_shares),
        "roic": roic,
        "ttm": {"revenue": ttm_revenue, "eps_diluted": ttm_eps, "free_cash_flow": ttm_fcf, "ebitda": ttm_ebitda},
        "methodology": {"version": VERSION, "ttm": "four non-overlapping discrete quarters; latest annual fact fallback"},
    }


def valuation_metrics(price: Any, financials: Mapping[str, Any], *, shares_outstanding: Any = None) -> dict[str, Any]:
    price_value = number(price)
    shares = number(shares_outstanding) or number(financials.get("shares_diluted"))
    market_cap = price_value * shares if price_value is not None and shares is not None else None
    debt, cash = number(financials.get("debt")), number(financials.get("cash"))
    ev = market_cap + debt - cash if market_cap is not None and debt is not None and cash is not None else None
    trailing = financials.get("ttm") or {}
    eps, revenue = number(trailing.get("eps_diluted")), number(trailing.get("revenue"))
    fcf, ebitda = number(trailing.get("free_cash_flow")), number(trailing.get("ebitda"))
    return {
        "market_cap": market_cap,
        "pe_ttm": safe_ratio(price_value, eps) if eps is not None and eps > 0 else None,
        "price_to_sales": safe_ratio(market_cap, revenue),
        "enterprise_value": ev,
        "ev_to_ebitda": safe_ratio(ev, ebitda) if ebitda is not None and ebitda > 0 else None,
        "fcf_yield": safe_ratio(fcf, market_cap),
        "methodology": {"version": VERSION, "basis": "current price with latest available trailing fundamentals"},
    }


def historical_valuation(
    price_points: Sequence[Mapping[str, Any]], filing_periods: Sequence[Mapping[str, Any]], metric_name: str,
) -> dict[str, Any]:
    """Build a valuation history using only filings public on each price date."""
    samples: list[dict[str, Any]] = []
    for point in sorted(price_points, key=lambda row: str(row.get("date") or row.get("ts") or "")):
        as_of = str(point.get("date") or point.get("ts") or "")[:10]
        eligible = [row for row in filing_periods if row.get("filed_at") and str(row["filed_at"])[:10] <= as_of]
        if not eligible:
            continue
        financials = financial_metrics(eligible)
        valuation = valuation_metrics(point.get("close"), financials)
        value = number(valuation.get(metric_name))
        if value is not None and value > 0:
            samples.append({"date": as_of, "value": value, "latest_filing": max(str(row["filed_at"])[:10] for row in eligible)})
    values = [item["value"] for item in samples]
    current = values[-1] if values else None
    percentile = (sum(value <= current for value in values) / len(values)) if current is not None else None
    return {
        "metric": metric_name, "samples": samples,
        "range": {"low": min(values), "median": median(values), "high": max(values)} if values else None,
        "current_percentile": percentile,
        "methodology": {"version": VERSION, "point_in_time": True, "rule": "filing.filed_at <= price.date"},
    }


def peer_medians(rows: Sequence[Mapping[str, Any]], fields: Iterable[str]) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for field in fields:
        values = [value for row in rows if (value := number(row.get(field))) is not None]
        output[field] = median(values) if values else None
    return output


def technical_metrics(prices: Sequence[Mapping[str, Any]], benchmark_prices: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    frame = pd.DataFrame(prices)
    if frame.empty:
        return {}
    date_column = "date" if "date" in frame else "ts"
    frame[date_column] = pd.to_datetime(frame[date_column], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).sort_values(date_column).drop_duplicates(date_column, keep="last").set_index(date_column)
    if frame.empty:
        return {}
    closes = frame["close"]
    returns = closes.pct_change().dropna()
    benchmark_returns = pd.Series(dtype=float)
    if benchmark_prices:
        benchmark = pd.DataFrame(benchmark_prices)
        benchmark_date = "date" if "date" in benchmark else "ts"
        benchmark[benchmark_date] = pd.to_datetime(benchmark[benchmark_date], utc=True)
        benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
        benchmark = benchmark.dropna(subset=["close"]).sort_values(benchmark_date).drop_duplicates(benchmark_date, keep="last").set_index(benchmark_date)
        benchmark_returns = benchmark["close"].pct_change().dropna()
    beta = None
    pair = pd.concat([returns.rename("asset"), benchmark_returns.rename("market")], axis=1).dropna()
    if len(pair) >= 30 and pair["market"].var() > 0:
        beta = float(pair.cov().loc["asset", "market"] / pair["market"].var())
    changes = closes.diff().dropna().tail(14)
    gain, loss = changes.clip(lower=0).mean(), -changes.clip(upper=0).mean()
    rsi = None if len(changes) < 14 else 100.0 if loss == 0 else float(100 - 100 / (1 + gain / loss))
    recent = closes.tail(126)
    current = float(closes.iloc[-1])
    support = sorted({round(float(recent.quantile(q)), 2) for q in (.10, .25) if float(recent.quantile(q)) < current}, reverse=True) if len(recent) >= 20 else []
    resistance = sorted({round(float(recent.quantile(q)), 2) for q in (.75, .90) if float(recent.quantile(q)) > current}) if len(recent) >= 20 else []
    horizon_returns = {name: (float(closes.iloc[-1] / closes.iloc[-sessions - 1] - 1) if len(closes) > sessions else None)
                       for name, sessions in (("1_week", 5), ("1_month", 21), ("3_month", 63), ("1_year", 252), ("3_year", 756))}
    return {
        "as_of": frame.index[-1].isoformat(), "price": current, "returns": horizon_returns,
        "volatility": float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(returns) > 1 else None,
        "beta": beta, "maximum_drawdown": float((closes / closes.cummax() - 1).min()),
        "rsi_14": rsi,
        "moving_averages": {"sma_50": float(closes.tail(50).mean()) if len(closes) >= 50 else None,
                            "sma_200": float(closes.tail(200).mean()) if len(closes) >= 200 else None},
        "support_resistance": {"support": support, "resistance": resistance,
                               "method": "10th/25th and 75th/90th percentiles of latest 126 adjusted closes"},
        "methodology": {"version": VERSION, "adjusted_prices": True, "annualization": TRADING_DAYS},
    }


def portfolio_metrics(target_ticker: str, target_prices: Sequence[Mapping[str, Any]], holdings: Sequence[Mapping[str, Any]],
                      price_history: Mapping[str, Sequence[Mapping[str, Any]]], benchmark_prices: Sequence[Mapping[str, Any]],
                      *, proposed_weight: float | None = None) -> dict[str, Any]:
    """Canonical return-series portfolio fit; no policy weight is invented."""
    normalized_weights = {str(row.get("ticker") or "").upper(): number(row.get("weight")) or 0.0 for row in holdings}
    if normalized_weights and sum(normalized_weights.values()) > 1.5:
        normalized_weights = {key: value / 100 for key, value in normalized_weights.items()}
    target = technical_metrics(target_prices, benchmark_prices)
    target_frame = pd.DataFrame(target_prices)
    if target_frame.empty:
        return {}
    date_key = "date" if "date" in target_frame else "ts"
    target_frame[date_key] = pd.to_datetime(target_frame[date_key], utc=True)
    target_returns = target_frame.set_index(date_key)["close"].astype(float).sort_index().pct_change().rename("target")
    holding_returns, correlations, betas = [], {}, {}
    benchmark_frame = pd.DataFrame(benchmark_prices)
    benchmark_returns = pd.Series(dtype=float)
    if not benchmark_frame.empty:
        benchmark_date = "date" if "date" in benchmark_frame else "ts"
        benchmark_frame[benchmark_date] = pd.to_datetime(benchmark_frame[benchmark_date], utc=True)
        benchmark_returns = benchmark_frame.set_index(benchmark_date)["close"].astype(float).sort_index().pct_change().rename("market")
    for ticker, weight in normalized_weights.items():
        rows = list(price_history.get(ticker) or [])
        if not rows or weight == 0:
            continue
        frame = pd.DataFrame(rows)
        key = "date" if "date" in frame else "ts"
        frame[key] = pd.to_datetime(frame[key], utc=True)
        returns = frame.set_index(key)["close"].astype(float).sort_index().pct_change().rename(ticker)
        holding_returns.append(returns * weight)
        pair = pd.concat([target_returns, returns], axis=1).dropna()
        correlations[ticker] = float(pair.corr().iloc[0, 1]) if len(pair) >= 30 else None
        market_pair = pd.concat([returns, benchmark_returns], axis=1).dropna()
        betas[ticker] = float(market_pair.cov().iloc[0, 1] / market_pair["market"].var()) if len(market_pair) >= 30 and market_pair["market"].var() > 0 else None
    portfolio_returns = pd.concat(holding_returns, axis=1).sum(axis=1, min_count=1).rename("portfolio") if holding_returns else pd.Series(dtype=float)
    pair = pd.concat([target_returns, portfolio_returns], axis=1).dropna()
    correlation = float(pair.corr().iloc[0, 1]) if len(pair) >= 30 else None
    portfolio_beta = sum(normalized_weights[ticker] * beta for ticker, beta in betas.items() if beta is not None)
    after_beta = None
    stress_impact = None
    if proposed_weight is not None and target.get("beta") is not None:
        weight = proposed_weight / 100 if proposed_weight > 1 else proposed_weight
        after_beta = portfolio_beta * (1 - weight) + target["beta"] * weight
        stress_impact = -(after_beta - portfolio_beta) * .20
    ranked = [(ticker, value) for ticker, value in correlations.items() if value is not None]
    return {
        "current_exposure": normalized_weights.get(target_ticker.upper(), 0.0),
        "correlation": correlation,
        "highest_overlap": max(ranked, key=lambda item: item[1]) if ranked else None,
        "portfolio_beta_before": portfolio_beta if betas else None,
        "portfolio_beta_after": after_beta, "stress_test_increment_at_minus_20_market": stress_impact,
        "proposed_weight": proposed_weight,
        "methodology": {"version": VERSION, "returns": "daily adjusted close", "minimum_overlap": 30,
                        "beta": "covariance(asset,SPY)/variance(SPY)", "policy_weight_invented": False},
    }
