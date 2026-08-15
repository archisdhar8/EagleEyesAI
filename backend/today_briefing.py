from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .guidance import guidance_disclosure
from .market_context import normalize_events, normalize_observation


INDEXES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow", "IWM": "Russell 2000"}
SECTORS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health care",
    "XLI": "Industrials", "XLY": "Consumer discretionary", "XLP": "Consumer staples",
    "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real estate", "XLC": "Communication services",
}
MARKET_SERIES = {
    "DGS10": ("10-year Treasury", "% yield", "rates"),
    "DCOILWTICO": ("WTI crude oil", "USD/barrel", "oil"),
    "BAMLH0A0HYM2": ("High-yield credit spread", "% spread", "credit"),
    "DTWEXBGS": ("Broad U.S. dollar", "index", "dollar"),
    "VIXCLS": ("VIX volatility", "index", "volatility"),
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _business_days_since(value: Any, today: date | None = None) -> int | None:
    observed = _iso_date(value)
    if observed is None:
        return None
    cursor = observed
    end = today or datetime.now(timezone.utc).date()
    count = 0
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count


def _source(label: str, url: str | None, as_of: Any, provider: str) -> dict[str, Any]:
    return {"label": label, "url": url, "as_of": str(as_of) if as_of else None, "provider": provider}


def market_movement_rows(price_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in price_rows:
        grouped.setdefault(str(row.get("ticker", "")).upper(), []).append(row)
    output: list[dict[str, Any]] = []
    for ticker, rows in grouped.items():
        # Provider histories may overlap. Treat a calendar session as one
        # observation so 1/5/21-session changes cannot accidentally count the
        # same market day twice.
        sessions: dict[str, dict[str, Any]] = {}
        for row in rows:
            session = str(row.get("date") or row.get("observed_at") or "")[:10]
            if not session:
                continue
            current = sessions.get(session)
            preference = (
                1 if str(row.get("provider") or "").lower() == "tiingo" else 0,
                str(row.get("fetched_at") or row.get("retrieved_at") or ""),
            )
            current_preference = (
                1 if str((current or {}).get("provider") or "").lower() == "tiingo" else 0,
                str((current or {}).get("fetched_at") or (current or {}).get("retrieved_at") or ""),
            )
            if current is None or preference > current_preference:
                sessions[session] = row
        ordered = [sessions[key] for key in sorted(sessions)]
        if not ordered:
            continue
        latest = ordered[-1]
        latest_close = _number(latest.get("close"))
        if latest_close <= 0:
            continue
        def change(offset: int) -> float | None:
            if len(ordered) <= offset:
                return None
            base = _number(ordered[-1 - offset].get("close"))
            return None if base <= 0 else round(latest_close / base - 1, 6)
        label = INDEXES.get(ticker) or SECTORS.get(ticker) or ticker
        observation = normalize_observation(latest, default_status="end-of-day")
        output.append({
            "ticker": ticker, "label": label,
            "group": "index" if ticker in INDEXES else "sector" if ticker in SECTORS else "portfolio",
            "value": round(latest_close, 4), "change_1d": change(1), "change_1w": change(5), "change_1m": change(21),
            # Daily bars represent exchange sessions, not midnight instants.
            # Return a date so Pacific-time rendering cannot display the prior
            # calendar day for a 00:00 UTC database timestamp.
            "as_of": str(observation["observed_at"] or "")[:10] or None,
            "unit": "USD", "provider": observation["provider"],
            "source": observation.get("source_url") or f"/explore?view=securities&symbol={ticker}",
            "data_status": observation["data_status"], "latency_class": observation["latency_class"],
            "retrieved_at": observation["retrieved_at"], "entitlement": observation["entitlement"],
        })
    return sorted(output, key=lambda row: (row["group"], row["ticker"]))


def market_indicator_rows(macro_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in macro_rows:
        grouped.setdefault(str(row.get("series_id")), []).append(row)
    output = []
    for series_id, (label, unit, key) in MARKET_SERIES.items():
        rows = sorted(grouped.get(series_id, []), key=lambda row: str(row.get("date") or ""), reverse=True)
        if not rows:
            continue
        latest, previous = rows[0], rows[1] if len(rows) > 1 else None
        value = _number(latest.get("value"))
        observation = normalize_observation({**latest, "ticker": series_id, "as_of": latest.get("date"), "latency_class": "delayed", "dataset": "macro_observation", "stale_after_seconds": 45 * 86400}, default_status="delayed")
        output.append({
            "key": key, "series_id": series_id, "label": label, "unit": unit, "value": value,
            "change": None if previous is None else round(value - _number(previous.get("value")), 4),
            "as_of": latest.get("date"), "provider": latest.get("provider") or "FRED",
            "source": latest.get("source_url") or f"https://fred.stlouisfed.org/series/{series_id}",
            "data_status": observation["data_status"], "latency_class": "delayed",
            "retrieved_at": observation["retrieved_at"], "entitlement": "public_release",
        })
    return output


def _holding_weights(holdings: list[dict[str, Any]]) -> dict[str, float]:
    raw = {}
    for row in holdings:
        ticker = str(row.get("ticker") or "").upper()
        size = _number(row.get("weight")) or _number(row.get("market_value"))
        if ticker and size > 0:
            raw[ticker] = raw.get(ticker, 0) + size
    total = sum(raw.values())
    return {ticker: value / total for ticker, value in raw.items()} if total else {}


def _leadership(movements: list[dict[str, Any]]) -> dict[str, Any]:
    sectors = [row for row in movements if row["group"] == "sector" and row.get("change_1w") is not None]
    indexes = [row for row in movements if row["group"] == "index" and row.get("change_1w") is not None]
    sectors.sort(key=lambda row: row["change_1w"], reverse=True)
    indexes.sort(key=lambda row: row["change_1w"], reverse=True)
    return {
        "leading_sectors": sectors[:3], "lagging_sectors": list(reversed(sectors[-3:])),
        "leading_style": indexes[0] if indexes else None, "lagging_style": indexes[-1] if indexes else None,
        "method": "Ranked stored broad and sector ETF adjusted-price returns over the latest five trading sessions.",
    }


def build_today_briefing(
    payload: dict[str, Any],
    price_rows: list[dict[str, Any]],
    macro_market_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    portfolio = payload.get("portfolio") or None
    holdings = (portfolio or {}).get("holdings", [])
    weights = _holding_weights(holdings)
    research = payload.get("research") or []
    research_by_ticker = {str(row.get("ticker", "")).upper(): row for row in research}
    movements = market_movement_rows(price_rows)
    indicators = market_indicator_rows(macro_market_rows)
    warnings: list[str] = []
    evidence_state = "current"
    if not movements and previous_snapshot:
        movements = previous_snapshot.get("market_movement", [])
        indicators = previous_snapshot.get("market_indicators", indicators)
        movements = [{**row, "data_status": "cached"} for row in movements]
        indicators = [{**row, "data_status": "cached"} for row in indicators]
        evidence_state = "stale_fallback"
        warnings.append("Live market movement data was unavailable, so the latest validated briefing snapshot is shown.")
    elif not movements:
        evidence_state = "partial"
        warnings.append("Stored price history is not yet sufficient for weekly index and sector movement.")

    market_dates = [row.get("as_of") for row in movements if row.get("as_of")]
    market_data_as_of = max(market_dates, default=None)
    market_business_days_old = _business_days_since(market_data_as_of)
    if market_business_days_old is not None and market_business_days_old > 1:
        evidence_state = "partial" if evidence_state == "current" else evidence_state
        warnings.append(
            f"Latest stored market close is {market_business_days_old} trading days old. "
            "Use Refresh today's data to request newer provider observations."
        )

    missing_symbols = [ticker for ticker in weights if ticker != "CASH" and ticker not in research_by_ticker]
    weak_symbols = [ticker for ticker in weights if ticker != "CASH" and _number(research_by_ticker.get(ticker, {}).get("confidence")) < 45]
    if missing_symbols or weak_symbols:
        warnings.append("Some portfolio conclusions are limited by missing or low-coverage security evidence.")

    movement_by_ticker = {row["ticker"]: row for row in movements}
    largest = max(weights.items(), key=lambda item: item[1]) if weights else None
    sector_weights: dict[str, float] = {}
    for ticker, weight in weights.items():
        sector = research_by_ticker.get(ticker, {}).get("sector")
        if sector and sector not in {"Unclassified", "Broad Market"}:
            sector_weights[str(sector)] = sector_weights.get(str(sector), 0) + weight
    largest_sector = max(sector_weights.items(), key=lambda item: item[1]) if sector_weights else None

    scenario_by_key = {row.get("key"): row for row in payload.get("scenarios", {}).get("scenarios", [])}
    sticky = _number((scenario_by_key.get("sticky_inflation") or {}).get("probability"))
    recession = _number((scenario_by_key.get("recession_cuts") or {}).get("probability"))
    oil = _number((scenario_by_key.get("oil_shock") or {}).get("probability"))
    has_energy = sector_weights.get("Energy", 0) > .05
    analysis = payload.get("latest_analysis") or {}

    relevance = [
        {"key": "rates", "factor": "Higher rates", "relevance": "moderate", "direction": "negative", "explanation": "Rates affect equity valuation and company financing costs; sensitivity depends on the portfolio's sector and company mix.", "destination": "macro", "evidence": [_source("FRED rates evidence", "https://fred.stlouisfed.org/series/DGS10", next((row.get("as_of") for row in indicators if row["key"] == "rates"), None), "FRED")]},
        {"key": "inflation", "factor": "Inflation", "relevance": "high" if sticky >= .45 else "moderate" if sticky >= .25 else "low", "direction": "negative" if sticky >= .25 else "mixed", "explanation": "Inflation is evaluated independently from growth and recession evidence.", "destination": "scenarios", "evidence": [_source("Inflation scenario evidence", "/explore?view=scenarios", (scenario_by_key.get("sticky_inflation") or {}).get("as_of"), "FRED and prediction markets")]},
        {"key": "recession", "factor": "Recession", "relevance": "high" if recession >= .45 else "moderate" if recession >= .25 else "low", "direction": "negative", "explanation": "The latest analysis compares modeled portfolio loss ranges with saved constraints." if analysis else "Run portfolio analysis to compare modeled loss ranges with your constraints.", "destination": "portfolio", "evidence": [_source("Portfolio analysis", "/portfolio?view=analysis", analysis.get("created_at"), "EagleEyes calculations")]},
        {"key": "oil", "factor": "Oil shock", "relevance": "moderate" if has_energy or oil >= .30 else "low", "direction": "mixed" if has_energy else "negative", "explanation": "Energy exposure can respond directly; other holdings may be affected through inflation and input costs.", "destination": "scenarios", "evidence": [_source("Oil scenario evidence", "/explore?view=prediction-markets", (scenario_by_key.get("oil_shock") or {}).get("as_of"), "Kalshi, Polymarket, and macro priors")]},
    ]

    attention_candidates: list[dict[str, Any]] = []
    if largest and largest[1] >= .20:
        ticker, weight = largest
        attention_candidates.append({"key": "position_concentration", "priority": 100 if weight >= .30 else 80, "severity": "high" if weight >= .30 else "medium", "title": f"{ticker} is {weight:.0%} of current portfolio sizing", "why": "A single holding can dominate outcomes even when its company evidence is strong.", "affected": [ticker], "confidence": "high", "destination": "portfolio", "changed": "Current saved sizing exceeds the concentration review threshold.", "evidence": [_source(f"{ticker} saved holding", "/portfolio?view=holdings", now.isoformat(), "Saved portfolio")]})
    if largest_sector and largest_sector[1] >= .35:
        sector, weight = largest_sector
        affected = [ticker for ticker, ticker_weight in weights.items() if research_by_ticker.get(ticker, {}).get("sector") == sector and ticker_weight > 0]
        attention_candidates.append({"key": "sector_concentration", "priority": 75, "severity": "medium", "title": f"{sector} represents {weight:.0%} of classified exposure", "why": "Companies in the same sector can become more correlated when the same economic driver changes.", "affected": affected, "confidence": "medium", "destination": "portfolio", "changed": "Classified sector exposure is above the policy review level.", "evidence": [_source("Stored sector classifications", "/explore?view=securities", now.isoformat(), "SEC and stored research")]})
    if missing_symbols or weak_symbols:
        affected = sorted(set(missing_symbols + weak_symbols))
        attention_candidates.append({"key": "research_coverage", "priority": 70, "severity": "medium", "title": "Some holdings have incomplete research evidence", "why": "Missing or weak data reduces confidence in portfolio-specific conclusions.", "affected": affected, "confidence": "high", "destination": "explore", "changed": "Coverage validation found incomplete security evidence.", "evidence": [_source("Security coverage", "/explore?view=securities", now.isoformat(), "Provider coverage audit")]})
    stale_providers = [row for row in payload.get("data_status", {}).get("providers", []) if row.get("status") != "success"]
    if stale_providers:
        attention_candidates.append({"key": "provider_freshness", "priority": 60, "severity": "medium", "title": "Some research providers need refresh", "why": "Failed or stale providers are excluded or down-weighted instead of being treated as current.", "affected": [row.get("provider", "provider") for row in stale_providers[:4]], "confidence": "high", "destination": "advanced", "changed": "The most recent provider run did not complete successfully.", "evidence": [_source("Provider lineage", "/advanced?view=lineage", max((row.get("fetched_at") or "" for row in stale_providers), default=None), "Provider audit log")]})
    attention = sorted(attention_candidates, key=lambda row: (-int(row["priority"]), row["key"]))[:3]
    attention = [{key: value for key, value in row.items() if key != "priority"} for row in attention]

    leadership = _leadership(movements)
    top_sector = leadership.get("leading_sectors", [None])[0] if leadership.get("leading_sectors") else None
    rates_relevance = next(row for row in relevance if row["key"] == "rates")
    headline_parts = []
    if top_sector:
        headline_parts.append(f"{top_sector['label']} led stored sector ETFs over the latest week")
    headline_parts.append(f"{rates_relevance['factor']} have {rates_relevance['relevance']} {rates_relevance['direction']} relevance")
    if largest:
        headline_parts.append(f"{largest[0]} concentration is the largest portfolio-specific issue" if largest[1] >= .20 else "no single-position concentration breach is identified")
    else:
        headline_parts.append("add a portfolio to calculate holding-specific relevance")
    headline = ". ".join(part[0].upper() + part[1:] for part in headline_parts) + "."

    ideas: list[dict[str, Any]] = []
    idea_disclosure = {
        "universe": "Saved holdings, watchlist, explicitly requested securities, and stored broad/sector ETF research.",
        "eligibility_filters": ["Validated stored security research", "Evidence confidence at least 60/100"],
        "exclusions": ["Holdings already in the current portfolio for new-name comparisons", "Low-coverage or invalid records"],
        "minimum_data_requirements": ["Ticker classification", "Freshness metadata", "At least one auditable research source"],
        "selection_method": "Deterministic follow-up rules; stored composite evidence may order eligible names but is never the conclusion.",
    }
    non_holdings = [row for row in research if str(row.get("ticker", "")).upper() not in weights and _number(row.get("confidence")) >= 60]
    if non_holdings:
        candidate = max(non_holdings, key=lambda row: (_number(row.get("final_score")), _number(row.get("confidence"))))
        ideas.append({**idea_disclosure, "key": f"compare_{candidate['ticker']}", "title": f"Compare {candidate['ticker']} with current portfolio exposures", "why": "This is a high-coverage name in the saved research universe, not a buy recommendation.", "why_appeared": "It is outside current holdings and has the strongest eligible stored evidence and coverage.", "what_would_invalidate": "New evidence that weakens company quality, valuation, coverage, or portfolio fit.", "freshness": candidate.get("fundamentals_as_of") or candidate.get("price_as_of"), "ticker": candidate["ticker"], "confidence": "medium", "destination": f"/explore?view=comparisons&symbol={candidate['ticker']}", "evidence": [_source("Stored security research", candidate.get("source") or f"/explore?view=securities&symbol={candidate['ticker']}", candidate.get("fundamentals_as_of") or candidate.get("price_as_of"), "SEC, prices, and stored research")]})
    if weak_symbols:
        ticker = weak_symbols[0]
        ideas.append({**idea_disclosure, "key": f"coverage_{ticker}", "title": f"Investigate the missing evidence for {ticker}", "why": "Closing a data gap may be more useful than producing another low-confidence ranking.", "why_appeared": "This saved holding failed the minimum evidence-coverage rule.", "what_would_invalidate": "A successful provider refresh that restores sufficient current evidence.", "freshness": now.isoformat(), "ticker": ticker, "confidence": "high", "destination": f"/explore?view=securities&symbol={ticker}", "evidence": [_source("Coverage audit", f"/explore?view=securities&symbol={ticker}", now.isoformat(), "EagleEyes coverage rules")]})
    if top_sector:
        ideas.append({**idea_disclosure, "key": f"sector_{top_sector['ticker']}", "title": f"Review what is driving {top_sector['label']} leadership", "why": "A one-week ETF move is a research prompt, not evidence that leadership will continue.", "why_appeared": "It ranks first among stored sector ETF five-session returns.", "what_would_invalidate": "Leadership reversing over a longer window or inadequate constituent and catalyst evidence.", "freshness": top_sector.get("as_of"), "ticker": top_sector["ticker"], "confidence": "medium", "destination": f"/explore?view=securities&symbol={top_sector['ticker']}", "evidence": [_source("Adjusted ETF prices", top_sector["source"], top_sector["as_of"], top_sector["provider"])]})

    normalized_events, event_coverage = normalize_events(events, list(weights))
    upcoming = normalized_events[:8]
    no_urgent = not any(row["severity"] == "high" for row in attention)
    summary = "No urgent portfolio-specific change is supported by the available evidence." if no_urgent else "Review the prioritized portfolio-specific evidence before considering a change."
    summary += " No allocation change is justified by a macro label or short-term market move alone."
    return {
        "version": "today-briefing-v2", "as_of": now.isoformat(), "market_data_as_of": market_data_as_of,
        "market_business_days_old": market_business_days_old, "evidence_state": evidence_state,
        "guidance": guidance_disclosure(portfolio=portfolio, profile=payload.get("profile")),
        "headline": headline, "summary": summary,
        "portfolio_context": {"available": bool(portfolio), "name": (portfolio or {}).get("name"), "holding_count": len(holdings), "missing_symbols": missing_symbols, "weak_coverage_symbols": weak_symbols},
        "market_movement": movements, "market_indicators": indicators, "leadership": leadership,
        "portfolio_relevance": relevance, "attention": attention, "attention_limit": 3,
        "upcoming_events": upcoming, "event_coverage": event_coverage, "research_ideas": ideas[:3],
        "warnings": warnings, "quick_actions": ["explore", "ask", "portfolio", "advanced"],
        "calculation": {"method": "deterministic_today_briefing", "version": "today-briefing-v2", "assumptions": ["Five trading sessions represent one week.", "Sector leadership uses stored sector ETF adjusted prices.", "Research ideas identify follow-up work and are not recommendations."]},
    }
