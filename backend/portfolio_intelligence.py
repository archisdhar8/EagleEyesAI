from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .forecasting import FACTOR_RULES

DEPENDENCY_RULES = (*FACTOR_RULES,
    {"factor": "AI_INFRASTRUCTURE_DEMAND", "mechanism": "AI training, inference, and data-center capital spending", "direction": "MIXED", "strength": "HIGH",
     "companies": ["MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "AVGO", "AMD"]},
    {"factor": "LONG_DURATION_GROWTH", "mechanism": "cash flows whose valuation is especially sensitive to discount rates", "direction": "NEGATIVE", "strength": "MODERATE",
     "sectors": ["Technology"]},
    {"factor": "CONSUMER_DEMAND", "mechanism": "household spending and employment-sensitive demand", "direction": "NEGATIVE", "strength": "MODERATE",
     "sectors": ["Consumer Cyclical", "Consumer Discretionary"]},
)


def _num(value: Any) -> float | None:
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None


def weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    values = {str(row.get("ticker") or "").upper(): (_num(row.get("market_value")) or _num(row.get("weight")) or 0) for row in holdings}
    total = sum(values.values()); return {key: value / total for key, value in values.items() if key and value > 0} if total else {}


def correlation_clusters(prices: list[dict[str, Any]], portfolio_weights: dict[str, float], threshold: float = .65) -> dict[str, Any]:
    frame = pd.DataFrame(prices)
    if frame.empty: return {"status": "UNAVAILABLE", "clusters": [], "reason": "Adjusted-price history is unavailable."}
    pivot = frame.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index().pct_change(fill_method=None)
    corr, nodes = pivot.corr(min_periods=60), sorted(set(pivot.columns) & set(portfolio_weights))
    edges = [{"left": left, "right": right, "correlation": float(corr.loc[left, right]), "observations": int(pivot[[left, right]].dropna().shape[0])}
             for i, left in enumerate(nodes) for right in nodes[i + 1:] if pd.notna(corr.loc[left, right]) and corr.loc[left, right] >= threshold]
    graph = {node: set() for node in nodes}
    for edge in edges: graph[edge["left"]].add(edge["right"]); graph[edge["right"]].add(edge["left"])
    clusters, seen = [], set()
    for node in nodes:
        if node in seen or not graph[node]: continue
        stack, group = [node], set()
        while stack:
            current = stack.pop()
            if current in group: continue
            group.add(current); stack.extend(graph[current])
        seen |= group; members = sorted(group)
        clusters.append({"holdings": members, "portfolio_weight": sum(portfolio_weights.get(t, 0) for t in members),
                         "strongest_pair": max((e for e in edges if e["left"] in group and e["right"] in group), key=lambda e:e["correlation"], default=None)})
    return {"status": "AVAILABLE" if nodes else "UNAVAILABLE", "clusters": sorted(clusters, key=lambda x:x["portfolio_weight"], reverse=True),
            "threshold": threshold, "sample_window": "Up to 1,300 stored daily adjusted closes", "methodology": "Pearson return correlation; common drivers are analyzed separately."}


def economic_dependencies(portfolio_weights: dict[str, float], securities: list[dict[str, Any]], theses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classifications = {str(row.get("ticker") or "").upper(): row for row in securities}
    output = []
    for rule in DEPENDENCY_RULES:
        affected = []
        for ticker in portfolio_weights:
            row = classifications.get(ticker, {})
            if ticker in rule.get("companies", []) or row.get("sector") in rule.get("sectors", []) or row.get("industry") in rule.get("industries", []): affected.append(ticker)
        thesis_matches = []
        terms = {term.lower() for term in rule["factor"].split("_") if len(term) > 3}
        for thesis in theses:
            matched = [item for item in thesis.get("assumptions", []) if terms.intersection(str(item.get("description") or "").lower().replace("-", " ").split())]
            if matched: thesis_matches.append({"thesis_id": thesis.get("id"), "ticker": thesis.get("ticker"), "assumptions": [item.get("description") for item in matched]})
        if affected or thesis_matches:
            exposure = sum(portfolio_weights.get(t, 0) for t in affected)
            output.append({"factor": rule["factor"], "mechanism": rule["mechanism"], "direction": rule["direction"], "strength": rule["strength"],
                           "holdings": sorted(affected), "mapped_portfolio_weight": exposure if affected else None,
                           "level": "HIGH" if exposure >= .30 else "MODERATE" if exposure >= .10 else "LOW", "thesis_dependencies": thesis_matches,
                           "methodology": "Explicit company/industry/sector mapping from Phase 5; not a statistical beta."})
    return sorted(output, key=lambda row: row.get("mapped_portfolio_weight") or 0, reverse=True)


def fundamental_health(portfolio_weights: dict[str, float], periods: list[dict[str, Any]]) -> dict[str, Any]:
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in periods: by_ticker[str(row.get("ticker") or "").upper()].append(row)
    specs = {"revenue_growth": ("revenue", "growth"), "eps_growth": ("eps_diluted", "growth"), "fcf_growth": ("free_cash_flow", "growth"),
             "gross_margin": ("gross_profit", "margin"), "operating_margin": ("operating_income", "margin")}
    results = {}
    for output_key, (metric, mode) in specs.items():
        numerator = coverage = 0.0
        for ticker, weight in portfolio_weights.items():
            rows = sorted(by_ticker.get(ticker, []), key=lambda x:str(x.get("period_end") or ""), reverse=True)
            if len(rows) < (1 if mode == "margin" else 2): continue
            current = rows[0].get("metrics") or {}; prior = next((r.get("metrics") or {} for r in rows[1:] if r.get("fiscal_period") == rows[0].get("fiscal_period")), {})
            value = _num(current.get(metric)); base = _num(current.get("revenue")) if mode == "margin" else _num(prior.get(metric))
            calculated = None if value is None or base in (None, 0) else value / base if mode == "margin" else value / base - 1
            if calculated is not None: numerator += weight * calculated; coverage += weight
        weighted = numerator / coverage if coverage else None
        results[output_key] = {"value": weighted, "coverage": coverage, "status": "AVAILABLE" if weighted is not None else "UNAVAILABLE"}
    growth = results["revenue_growth"]["value"]
    return {"metrics": results, "summary": {"growth": "Strong" if growth is not None and growth >= .10 else "Improving" if growth is not None and growth > 0 else "Weakening" if growth is not None else "Unavailable"},
            "coverage": min((row["coverage"] for row in results.values()), default=0),
            "methodology": "Current portfolio weights applied only to holdings with aligned reported periods; uncovered weight remains explicit."}


def build_portfolio_intelligence(*, holdings: list[dict[str, Any]], security_data: dict[str, Any], diagnostics: dict[str, Any], theses: list[dict[str, Any]],
                                 monitor_results: list[dict[str, Any]], forecasting: dict[str, Any], events: list[dict[str, Any]], scenario_outcomes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current_weights = weights(holdings); statuses = defaultdict(int)
    for row in monitor_results: statuses[str(row.get("overall_status") or "INSUFFICIENT_EVIDENCE")] += 1
    thesis_tickers = {str(row.get("ticker") or "").upper() for row in theses}
    upcoming = []
    for event in events:
        affected = sorted(set(event.get("tickers") or []) & set(current_weights)); exposure = sum(current_weights.get(t, 0) for t in affected)
        if affected: upcoming.append({**event, "affected_holdings": affected, "portfolio_weight": exposure})
    prediction = [row for row in forecasting.get("markets", []) if row.get("affected_holdings")]
    health = fundamental_health(current_weights, security_data.get("fundamentals", []))
    scenarios = [{**row, "holding_contributors": row.get("holding_contributors") or [],
                  "holding_contributors_status": "AVAILABLE" if row.get("holding_contributors") else "UNAVAILABLE",
                  "contributor_note": None if row.get("holding_contributors") else "The stored aggregate scenario does not contain holding-level attribution; none is inferred.",
                  "methodology": row.get("method") or "Existing deterministic scenario outcome."} for row in (scenario_outcomes or [])]
    return {"version": "portfolio-intelligence-v1", "as_of": datetime.now(timezone.utc).isoformat(),
            "performance_methodology": {"label": diagnostics.get("performance_label"), "type": "CURRENT_WEIGHT_HYPOTHETICAL", "actual_account_performance_mixed": False},
            "concentration": {"positions": [{"ticker": t, "weight": w} for t,w in sorted(current_weights.items(), key=lambda x:x[1], reverse=True)],
                              "effective_holdings": None if not current_weights else 1 / sum(value * value for value in current_weights.values()),
                              "sector": diagnostics.get("sector_exposure", []), "industry": diagnostics.get("industry_exposure", [])},
            "risk_contribution": diagnostics.get("marginal_risk", {}), "correlation": correlation_clusters(security_data.get("prices", []), current_weights),
            "economic_dependencies": economic_dependencies(current_weights, security_data.get("securities", []), theses),
            "fundamental_health": health,
            "thesis_health": {"holding_count": len(current_weights), "active_thesis_count": len(theses), "status_counts": dict(statuses),
                              "holdings_without_thesis": sorted(set(current_weights) - thesis_tickers)},
            "prediction_market_exposure": prediction, "scenario_exposure": scenarios,
            "upcoming_events": sorted(upcoming, key=lambda row: row.get("portfolio_weight", 0), reverse=True),
            "coverage": {"classification": diagnostics.get("classification_coverage") or {},
                         "fundamental_weight": health["coverage"]},
            "methodology": "portfolio-intelligence-v1: existing holdings, covariance, Phase 5 mappings, stored financial periods, thesis monitor, and verified events."}
