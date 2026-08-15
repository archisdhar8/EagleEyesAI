from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from . import database


MINIMUM_FULL_CYCLE_YEARS = 7.0
MINIMUM_SENSITIVITY_OBSERVATIONS = 504
DATASET_VERSION = "adjusted-daily-prices-v1"

SECTOR_PROXIES = {
    "Communication Services": "XLC", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Energy": "XLE", "Financials": "XLF",
    "Healthcare": "XLV", "Industrials": "XLI", "Materials": "XLB",
    "Real Estate": "XLRE", "Technology": "XLK", "Utilities": "XLU",
    "Broad Market": "VTI", "Fixed Income": "BND",
}


def _years(first: str | None, last: str | None) -> float:
    if not first or not last:
        return 0.0
    try:
        start = date.fromisoformat(first[:10])
        end = date.fromisoformat(last[:10])
    except ValueError:
        return 0.0
    return max(0.0, (end - start).days / 365.25)


def _adjustment(provider: str, explicit: int) -> tuple[bool, str]:
    if provider == "tiingo":
        return explicit > 0, "Tiingo total-return adjusted close"
    if provider == "polygon":
        return True, "Polygon adjusted=true aggregate bars"
    return explicit > 0, "Explicit adjusted-close column" if explicit else "Adjustment not verified"


def build_historical_coverage(
    research: list[dict[str, Any]], minimum_full_cycle_years: float = MINIMUM_FULL_CYCLE_YEARS,
) -> dict[str, Any]:
    tickers = [str(row.get("ticker") or "").upper() for row in research if row.get("ticker") and str(row.get("ticker")).upper() != "CASH"]
    proxy_by_ticker = {
        str(row.get("ticker") or "").upper(): SECTOR_PROXIES.get(str(row.get("sector") or ""), "VTI")
        for row in research if row.get("ticker") and str(row.get("ticker")).upper() != "CASH"
    }
    requested = sorted(set(tickers) | set(proxy_by_ticker.values()))
    stored = {row["ticker"]: row for row in database.price_coverage_by_symbol(requested)}
    symbols: list[dict[str, Any]] = []
    for ticker in tickers:
        row = stored.get(ticker)
        proxy = proxy_by_ticker[ticker]
        proxy_row = stored.get(proxy)
        if row:
            years = _years(row.get("first_date"), row.get("last_date"))
            adjusted, adjustment_method = _adjustment(str(row.get("provider") or ""), int(row.get("explicit_adjusted_observations") or 0))
            observations = int(row.get("observations") or 0)
        else:
            years, observations, adjusted, adjustment_method = 0.0, 0, False, "No stored daily-price history"
        full_cycle = years >= minimum_full_cycle_years
        direct_usable = adjusted and observations >= MINIMUM_SENSITIVITY_OBSERVATIONS
        proxy_usable = bool(proxy_row and _years(proxy_row.get("first_date"), proxy_row.get("last_date")) >= minimum_full_cycle_years)
        missing_estimate = max(0, round(years * 252) - observations) if years else 0
        warnings: list[str] = []
        if not adjusted:
            warnings.append("Corporate-action adjustment is not verified.")
        if not full_cycle:
            warnings.append(f"Only {years:.1f} years are stored; a {minimum_full_cycle_years:.0f}-year full-cycle minimum is required for regime claims.")
        if not direct_usable:
            warnings.append("Direct factor sensitivity is not decision-ready from this price history.")
        if not proxy_usable:
            warnings.append(f"Fallback proxy {proxy} also lacks verified full-cycle coverage.")
        symbols.append({
            "ticker": ticker, "provider": row.get("provider") if row else None,
            "first_date": row.get("first_date") if row else None,
            "last_date": row.get("last_date") if row else None,
            "observations": observations, "estimated_missing_sessions": missing_estimate,
            "years": round(years, 2), "corporate_action_adjusted": adjusted,
            "adjustment_method": adjustment_method, "full_cycle_available": full_cycle,
            "direct_factor_model_eligible": direct_usable,
            "fallback": {
                "ticker": proxy, "available": proxy_usable,
                "provider": proxy_row.get("provider") if proxy_row else None,
                "first_date": proxy_row.get("first_date") if proxy_row else None,
                "last_date": proxy_row.get("last_date") if proxy_row else None,
            },
            "warnings": warnings,
            "lineage": ([{
                "provider": row.get("provider"), "dataset": "corporate-action-adjusted daily prices",
                "effective_through": row.get("last_date"), "symbols": [ticker],
                "dataset_version": DATASET_VERSION,
            }] if row else []),
        })
    insufficient = [row["ticker"] for row in symbols if not row["full_cycle_available"]]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(), "calculation_version": "historical-coverage-v1",
        "minimum_full_cycle_years": minimum_full_cycle_years,
        "minimum_sensitivity_observations": MINIMUM_SENSITIVITY_OBSERVATIONS,
        "symbols": symbols,
        "summary": {
            "requested": len(symbols), "full_cycle": len(symbols) - len(insufficient),
            "insufficient": len(insufficient), "insufficient_symbols": insufficient,
            "all_adjusted": all(row["corporate_action_adjusted"] for row in symbols) if symbols else False,
        },
        "warnings": ([f"{len(insufficient)} researched securities lack a verified full market cycle."] if insufficient else []),
        "assumptions": [
            "Seven years is the minimum full-cycle proxy; it does not guarantee every economic regime is represented.",
            "Factor and regime models use a sector or broad-market ETF proxy when direct history is inadequate.",
            "Proxy evidence lowers security-level confidence and is never presented as direct company history.",
        ],
    }


def attach_coverage(research: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    coverage = build_historical_coverage(research)
    indexed = {row["ticker"]: row for row in coverage["symbols"]}
    enriched = []
    for row in research:
        item = dict(row)
        item["historical_coverage"] = indexed.get(str(row.get("ticker") or "").upper(), {
            "ticker": row.get("ticker"), "full_cycle_available": False,
            "direct_factor_model_eligible": False, "warnings": ["No stored adjusted-price history."], "lineage": [],
        })
        enriched.append(item)
    return enriched, coverage
