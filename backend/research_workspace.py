from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


THEMES: dict[str, dict[str, Any]] = {
    "ai_infrastructure": {
        "label": "AI infrastructure",
        "keywords": ["semiconductor", "software", "cloud", "data", "network", "technology"],
        "description": "Compute, networking, semiconductor, cloud, and data-infrastructure exposure.",
    },
    "semiconductors": {
        "label": "Semiconductors",
        "keywords": ["semiconductor", "chip"],
        "description": "Semiconductor designers, manufacturers, equipment, and related suppliers.",
    },
    "cybersecurity": {
        "label": "Cybersecurity",
        "keywords": ["cyber", "security software", "network security"],
        "description": "Security software, identity, network protection, and related infrastructure.",
    },
    "energy": {
        "label": "Energy and oil",
        "keywords": ["energy", "oil", "gas", "petroleum"],
        "description": "Energy producers, services, infrastructure, and broad energy funds.",
    },
    "dividend_income": {
        "label": "Dividend income",
        "keywords": ["dividend", "utilities", "real estate", "consumer staples"],
        "description": "Income-oriented companies and funds identified from stored classifications.",
    },
    "healthcare_innovation": {
        "label": "Healthcare innovation",
        "keywords": ["health", "biotech", "pharma", "medical"],
        "description": "Healthcare, biotechnology, pharmaceutical, and medical-technology exposure.",
    },
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _components(row: dict[str, Any]) -> list[tuple[str, float]]:
    return [
        ("Growth", _number(row.get("growth_rating"), 50)),
        ("Valuation", _number(row.get("valuation_score"), 50)),
        ("Business quality", _number(row.get("fundamental_score"), 50)),
        ("Industry position", _number(row.get("industry_score"), 50)),
        ("Price behavior", _number(row.get("technical_score"), 50)),
    ]


def _available_components(row: dict[str, Any]) -> list[tuple[str, float]]:
    """Return only evidenced components; missing fields never become neutral 50s."""
    coverage = row.get("component_coverage")
    definitions = [
        ("Growth", "growth_rating", "growth"),
        ("Valuation", "valuation_score", "valuation"),
        ("Business quality", "fundamental_score", "business_quality"),
        ("Industry position", "industry_score", "industry_position"),
        ("Price behavior", "technical_score", "price_behavior"),
    ]
    available = []
    for label, field, coverage_key in definitions:
        evidenced = (coverage or {}).get(coverage_key) if isinstance(coverage, dict) else row.get(field) is not None
        if evidenced and row.get(field) is not None:
            available.append((label, _number(row[field])))
    return available


def evidence_bucket(row: dict[str, Any]) -> tuple[str, str]:
    """Translate stored component evidence into a deterministic, non-recommendation label."""
    confidence = _number(row.get("confidence"))
    quality = str(row.get("data_quality") or "low").lower()
    available = _available_components(row)
    if len(available) < 3:
        return "Limited evidence", f"Only {len(available)} of 5 required component areas have auditable evidence."
    components = [value for _, value in available]
    supportive = sum(value >= 58 for value in components)
    weak = sum(value < 42 for value in components)
    if confidence < 45 or quality == "low":
        return "Limited evidence", "Coverage or freshness is too weak for a strong comparative conclusion."
    if supportive >= 4 and weak == 0:
        return "Broadly supportive", "At least four component areas are supportive and none is materially weak."
    if supportive >= 2 and weak <= 1:
        return "Supportive with tradeoffs", "Several component areas are supportive, with no more than one material weakness."
    if weak >= 3:
        return "Mostly cautious", "At least three component areas are weak relative to the disclosed universe."
    return "Mixed evidence", "The component evidence is balanced or internally inconsistent."


def _fundamental_trend(row: dict[str, Any]) -> dict[str, Any]:
    growth = row.get("revenue_growth")
    margin = row.get("net_margin")
    if growth is None and margin is None:
        return {"label": "Unavailable", "detail": "Revenue growth and margin history are missing."}
    growth_value = _number(growth)
    margin_value = _number(margin)
    if growth_value >= .10 and margin_value >= .10:
        label = "Expanding"
    elif growth_value < 0 or margin_value < 0:
        label = "Under pressure"
    else:
        label = "Stable / mixed"
    return {"label": label, "revenue_growth": growth, "net_margin": margin}


def _freshness(row: dict[str, Any]) -> dict[str, Any]:
    dates = [value for value in [row.get("price_as_of"), row.get("fundamentals_as_of")] if value]
    stale = False
    if dates:
        try:
            parsed = []
            for value in dates:
                item = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                parsed.append(item.replace(tzinfo=timezone.utc) if item.tzinfo is None else item.astimezone(timezone.utc))
            latest = max(parsed)
            stale = (datetime.now(timezone.utc) - latest).days > 120
        except ValueError:
            stale = True
    coverage = _number(row.get("confidence"))
    return {
        "status": "stale" if stale else "current" if dates else "unknown",
        "price_as_of": row.get("price_as_of"),
        "fundamentals_as_of": row.get("fundamentals_as_of"),
        "coverage": "high" if coverage >= 75 else "medium" if coverage >= 50 else "low",
        "confidence_reasons": [
            f"Stored research confidence is {coverage:.0f}/100.",
            "A weak or stale input lowers the evidence bucket even when other components are strong.",
        ],
    }


def enrich_security(
    row: dict[str, Any], rank: int, universe: dict[str, Any], holdings: set[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    holdings = holdings or set()
    available_components = _available_components(row)
    components = sorted(available_components, key=lambda item: item[1], reverse=True)
    bucket, explanation = evidence_bucket(row)
    weak = list(reversed(components))
    risk_flags = list(row.get("risk_flags") or [])
    news = row.get("latest_news")
    valuation = _number(row.get("valuation_score"), 50)
    valuation_evidence = row.get("valuation_evidence") or {
        "status": "available", "score": valuation, "source": "legacy stored valuation evidence",
        "method": "legacy-valuation-evidence-v1", "raw_metrics": {}, "components": [],
        "formula": "The stored fixture or legacy row supplies the valuation evidence directly.",
        "limitations": ["Raw multiple inputs are unavailable for this compatibility row."],
    }
    valuation_available = valuation_evidence.get("status") == "available"
    ticker = str(row.get("ticker") or "").upper()
    context = context or {}
    peers = [item for item in context.get("peer_rows", []) if item.get("ticker") != ticker and (
        item.get("industry") == row.get("industry") or item.get("sector") == row.get("sector")
    )]
    industry_peers = [item for item in peers if item.get("industry") == row.get("industry")]
    selected_peers = (industry_peers or peers)[:12]
    valuation_peers = [item for item in selected_peers if "valuation_evidence" not in item or (item.get("valuation_evidence") or {}).get("status") == "available"]
    peer_values = sorted(_number(item.get("valuation_score"), 50) for item in valuation_peers)
    peer_median = peer_values[len(peer_values) // 2] if peer_values else None
    memberships = [item for item in context.get("memberships", []) if item.get("security_ticker") == ticker]
    fund = next((item for item in context.get("funds", []) if item.get("ticker") == ticker), None)
    fund_holdings = [item for item in context.get("fund_holdings", []) if item.get("fund_ticker") == ticker]
    containing_funds = [item for item in context.get("containing_funds", []) if item.get("constituent_ticker") == ticker]
    events = [item for item in context.get("events", []) if not item.get("tickers") or ticker in item.get("tickers", [])]
    fund_lookup = (context.get("fund_lookup") or {}).get(ticker)
    if ticker in holdings:
        portfolio_fit = "Existing holding — assess its concentration and risk contribution."
    elif str(row.get("sector") or "") in {"Broad Market", "Fixed Income"}:
        portfolio_fit = "Potential diversifier, subject to overlap and account-level checks."
    else:
        portfolio_fit = "New exposure — compare sector overlap and marginal risk before considering it."
    if _number(row.get("confidence")) < 50:
        change_view = "Fresher fundamentals, longer adjusted-price history, and better coverage could change this view."
    elif weak and weak[0][0] == "Valuation":
        change_view = "A lower market price or stronger forward cash-flow evidence could improve valuation evidence."
    elif weak and weak[0][0] == "Growth":
        change_view = "Sustained revenue and earnings acceleration could improve the growth assessment."
    else:
        change_view = f"Material improvement or deterioration in {weak[0][0].lower()} would change this view." if weak else "Auditable fundamentals, valuation, and price history are required before a comparative view can be formed."
    return {
        **row,
        "relative_rank": rank,
        "universe": universe,
        "evidence_bucket": bucket,
        "bucket_explanation": explanation,
        "strengths": [{"label": name, "evidence": round(value, 1)} for name, value in components[:2]],
        "weaknesses": [{"label": name, "evidence": round(value, 1)} for name, value in weak[:2]],
        "field_coverage": {
            "available": [name for name, _ in available_components],
            "missing": [name for name, _ in _components({}) if name not in {item[0] for item in available_components}],
            "ratio": round(len(available_components) / 5, 2),
            "policy": "Missing evidence is excluded; it is never replaced with a neutral score.",
        },
        "valuation_range": {
            "label": "Insufficient valuation evidence" if not valuation_available else "Relatively attractive" if valuation >= 65 else "Relatively demanding" if valuation < 45 else "Mixed / near peer range",
            "basis": "Required price/fundamental inputs are missing; no valuation conclusion is shown." if not valuation_available else "Relative valuation evidence; not a price target or intrinsic-value guarantee.",
        },
        "comparable_valuation": {
            "label": "Insufficient security valuation evidence" if not valuation_available else "Above peer evidence" if peer_median is not None and valuation >= peer_median + 5 else "Below peer evidence" if peer_median is not None and valuation <= peer_median - 5 else "Near peer evidence" if peer_median is not None else "Insufficient peer coverage",
            "security_evidence": round(valuation, 1), "peer_median_evidence": None if peer_median is None else round(peer_median, 1),
            "peer_count": len(valuation_peers), "peer_tickers": [item.get("ticker") for item in valuation_peers],
            "basis": "Deterministic comparison with stored same-industry peers first, then same-sector peers. This compares valuation evidence scores, not price targets.",
        },
        "valuation_methodology": valuation_evidence,
        "fundamental_trend": _fundamental_trend(row),
        "price_behavior": {
            "one_year_change": row.get("price_change_1y"),
            "label": "Positive" if _number(row.get("price_change_1y")) > .05 else "Negative" if _number(row.get("price_change_1y")) < -.05 else "Range-bound / mixed",
        },
        "catalysts": ([{"title": news.get("title"), "source_url": news.get("source_url"), "published_at": news.get("published_at"), "type": "news"}] if isinstance(news, dict) and news.get("title") else []) + [
            {"title": event.get("title"), "source_url": event.get("source_url"), "published_at": event.get("starts_at"), "type": event.get("event_type"), "provider": event.get("provider")}
            for event in events[:3]
        ] + [
            {"title": market.get("title"), "source_url": market.get("source"), "probability": market.get("probability")}
            for market in list(row.get("prediction_markets") or [])[:2]
        ],
        "thesis_risks": risk_flags or ([f"The weakest stored component is {weak[0][0].lower()}."] if weak else ["Insufficient component coverage"]),
        "portfolio_fit": portfolio_fit,
        "classification": {
            "sector": row.get("sector") or "Unclassified", "industry": row.get("industry") or "Unclassified",
            "memberships": [{"type": item.get("collection_type"), "name": item.get("collection_name"), "weight": item.get("weight"), "as_of": item.get("as_of"), "provider": item.get("provider"), "source_url": item.get("source_url")} for item in memberships[:12]],
        },
        "fund_details": None if not fund else {
            "expense_ratio": fund.get("expense_ratio"), "effective_at": fund.get("effective_at"), "provider": fund.get("provider"), "source_url": fund.get("source_url"),
            "total_holdings": len(fund_holdings),
            "top_holdings": [{"ticker": item.get("constituent_ticker"), "weight": item.get("weight"), "as_of": item.get("as_of"), "provider": item.get("provider")} for item in fund_holdings[:25]],
        },
        "fund_coverage": fund_lookup or {
            "status": "available" if fund else "not_applicable" if str(row.get("industry") or "").upper() not in {"ETF", "SECTOR ETF", "ACTIVE GROWTH ETF", "GROWTH"} and str(row.get("sector") or "") not in {"Broad Market", "Fixed Income"} else "missing",
            "reason": None if fund else "No current ETF reference or holdings snapshot is stored.",
        },
        "etf_overlap": [{"fund_ticker": item.get("fund_ticker"), "weight": item.get("weight"), "as_of": item.get("as_of"), "provider": item.get("provider"), "source_url": item.get("source_url")} for item in containing_funds[:10]],
        "what_would_change_the_view": change_view,
        "freshness": _freshness(row),
        "missing_data": [
            item for item in [
                None if row.get("price_as_of") else {"field": "Price history", "reason": "No adjusted-price observations are stored for this symbol.", "provider": "Polygon/Massive or Tiingo"},
                None if row.get("fundamentals_as_of") or fund else {"field": "Fundamental trend", "reason": "No usable SEC Company Facts period is stored for this security.", "provider": "SEC EDGAR Company Facts"},
                None if valuation_available else {"field": "Valuation", "reason": "Missing: " + ", ".join(valuation_evidence.get("missing_inputs") or ["auditable valuation inputs"]), "provider": valuation_evidence.get("source")},
                None if memberships else {"field": "Index/theme membership", "reason": "No current membership dataset is stored.", "provider": "ETF/index reference provider"},
                None if fund or fund_lookup is None or fund_lookup.get("status") == "not_applicable" else {"field": "ETF holdings", "reason": fund_lookup.get("reason") or "The holdings provider returned no validated snapshot.", "provider": fund_lookup.get("provider")},
            ] if item is not None
        ],
        "disclaimer": "Comparative research evidence only; not a buy recommendation or price target.",
    }


def build_universe(
    rows: list[dict[str, Any]], holdings: list[str] | None = None, watchlist: list[str] | None = None,
    requested: list[str] | None = None, source: str = "stored research universe",
) -> dict[str, Any]:
    tickers = {str(row.get("ticker") or "").upper() for row in rows if row.get("ticker")}
    holdings_set, watchlist_set, requested_set = set(holdings or []), set(watchlist or []), set(requested or [])
    return {
        "definition": "Saved holdings, watchlist, explicitly requested securities, and stored broad/sector ETF research.",
        "source": source,
        "total": len(tickers),
        "holdings": len(tickers & holdings_set),
        "watchlist": len(tickers & watchlist_set),
        "explicitly_requested": len(tickers & requested_set),
        "sector_or_broad_etfs": sum(str(row.get("sector") or "") in {"Broad Market", "Fixed Income"} or "ETF" in str(row.get("industry") or "").upper() for row in rows),
        "tickers": sorted(tickers),
    }


def search(
    rows: list[dict[str, Any]], query: str = "", fundamentals: str = "", valuation: str = "",
    theme: str = "", holdings: list[str] | None = None, watchlist: list[str] | None = None,
    requested: list[str] | None = None, limit: int = 100, context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = query.strip().lower()
    theme_rule = THEMES.get(theme)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        searchable = " ".join(str(row.get(key) or "") for key in ("ticker", "company", "sector", "industry")).lower()
        if normalized and normalized not in searchable:
            continue
        if fundamentals == "strong" and _number(row.get("fundamental_score")) < 60:
            continue
        if valuation == "reasonable" and (("valuation_evidence" in row and (row.get("valuation_evidence") or {}).get("status") != "available") or _number(row.get("valuation_score")) < 50):
            continue
        if theme_rule and not any(keyword in searchable for keyword in theme_rule["keywords"]):
            continue
        filtered.append(row)
    filtered.sort(key=lambda row: (_number(row.get("final_score")), _number(row.get("confidence"))), reverse=True)
    universe = build_universe(filtered, holdings, watchlist, requested, source="deterministic stored-security search")
    enriched_context = {**(context or {}), "peer_rows": rows}
    results = [enrich_security(row, index + 1, universe, set(holdings or []), enriched_context) for index, row in enumerate(filtered[:limit])]
    return {
        "query": query,
        "filters": {"fundamentals": fundamentals or None, "valuation": valuation or None, "theme": theme or None},
        "universe": universe,
        "results": results,
        "method": {"name": "deterministic evidence buckets", "version": "research-workspace-v2", "ranking_use": "Stored composite is used only to order otherwise eligible results; it is not the conclusion."},
        "disclaimer": "Results are comparative research within the disclosed universe and are not buy recommendations.",
    }


def sector_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("sector") or "Unclassified")].append(row)
    items = []
    for sector, members in grouped.items():
        buckets = Counter(evidence_bucket(row)[0] for row in members)
        items.append({
            "sector": sector,
            "security_count": len(members),
            "coverage": "high" if sum(_number(row.get("confidence")) for row in members) / len(members) >= 70 else "medium" if sum(_number(row.get("confidence")) for row in members) / len(members) >= 45 else "low",
            "evidence_mix": dict(buckets),
            "leaders": [row.get("ticker") for row in sorted(members, key=lambda row: _number(row.get("final_score")), reverse=True)[:3]],
            "disclaimer": "Relative evidence within the stored universe, not a sector recommendation.",
        })
    items.sort(key=lambda item: (-item["security_count"], item["sector"]))
    return {"universe": build_universe(rows), "sectors": items, "version": "research-sectors-v1"}


def theme_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for key, rule in THEMES.items():
        members = []
        for row in rows:
            searchable = " ".join(str(row.get(field) or "") for field in ("company", "sector", "industry")).lower()
            if any(keyword in searchable for keyword in rule["keywords"]):
                members.append(row)
        items.append({
            "key": key, "label": rule["label"], "description": rule["description"],
            "member_count": len(members), "tickers": sorted(str(row.get("ticker")) for row in members),
            "mapping_rule": f"Stored company, sector, and industry text matched: {', '.join(rule['keywords'])}.",
            "universe": build_universe(rows),
        })
    return {"universe": build_universe(rows), "themes": items, "version": "research-themes-v1"}


def ideas(rows: list[dict[str, Any]], holdings: list[str] | None = None) -> dict[str, Any]:
    payload = search(rows, holdings=holdings, limit=20)
    candidates = [row for row in payload["results"] if row["evidence_bucket"] in {"Broadly supportive", "Supportive with tradeoffs"}]
    disclosure = {
        "universe": payload["universe"],
        "eligibility_filters": ["Broadly supportive or supportive-with-tradeoffs evidence bucket"],
        "exclusions": ["Limited-evidence, mixed-evidence, and mostly-cautious records"],
        "minimum_data_requirements": ["Auditable component evidence", "Current freshness and coverage metadata"],
        "selection_method": payload["method"],
    }
    return {
        "universe": payload["universe"],
        "ideas": [{
            "ticker": row["ticker"], "question": f"Investigate whether {row['ticker']} fits the portfolio after overlap, valuation, and risk checks.",
            "evidence_bucket": row["evidence_bucket"], "portfolio_fit": row["portfolio_fit"],
            "missing_or_reversal_evidence": row["what_would_change_the_view"],
            "why_appeared": row["bucket_explanation"],
            "confidence": row["freshness"]["coverage"],
            "freshness": row["freshness"],
            **disclosure,
        } for row in candidates[:8]],
        "eligibility": disclosure,
        "disclaimer": "Research follow-ups, not buy recommendations.",
    }


def comparisons(rows: list[dict[str, Any]], tickers: list[str], holdings: list[str] | None = None) -> dict[str, Any]:
    selected = [row for row in rows if str(row.get("ticker") or "").upper() in set(tickers)]
    payload = search(selected, holdings=holdings, requested=tickers, limit=20)
    return {**payload, "requested_tickers": tickers, "comparison_dimensions": [name for name, _ in _components({})]}
