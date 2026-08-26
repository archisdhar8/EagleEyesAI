from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from typing import Any

from backend import database
from backend.auth import AuthenticatedUser
from backend.main import consolidated_research_security_overview
from backend.research_metric_registry import REGISTRY, registry_payload


AUDIT_USER = AuthenticatedUser("00000000-0000-0000-0000-000000000001", "research-audit@example.invalid")


def nonempty(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return True


def get_path(data: Any, dotted: str | None) -> Any:
    if not dotted:
        return None
    value = data
    for part in dotted.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            values = [get_path(item, ".".join(dotted.split(".")[dotted.split(".").index(part):])) for item in value]
            return [item for item in values if nonempty(item)]
        else:
            return None
    return value


def aligned(rows: list[dict[str, Any]], key: str) -> bool:
    complete = [row for row in rows if (row.get("metrics") or {}).get(key) is not None]
    for current in complete:
        if any(row.get("fiscal_period") == current.get("fiscal_period") and row.get("fiscal_year") != current.get("fiscal_year") for row in complete):
            return True
    return False


def complete_periods(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [row for row in rows if all((row.get("metrics") or {}).get(key) is not None for key in keys)]


def input_tokens(ticker: str, bundle: dict[str, Any], payload: dict[str, Any], master: dict[str, Any] | None,
                 event_count: int, transcript_count: int) -> set[str]:
    rows = [row for row in bundle.get("fundamentals", []) if row.get("ticker") == ticker]
    prices = [row for row in bundle.get("prices", []) if row.get("ticker") == ticker]
    latest = rows[0].get("metrics", {}) if rows else {}
    tokens = {"security", "source_lineage", "model_output"}
    if master and master.get("exchange"): tokens.add("security_master.exchange")
    security = next((row for row in bundle.get("securities", []) if row.get("ticker") == ticker), {})
    if security.get("sector"): tokens.add("security.sector")
    if security.get("industry"): tokens.update({"security.industry", "peer_universe"})
    if prices:
        tokens.update({"price_history", "price_ytd"})
        for count, name in ((15, "price_15d"), (50, "price_50d"), (63, "price_63d"), (126, "price_126d"), (200, "price_200d"), (253, "price_1y"), (1000, "price_5y")):
            if len(prices) >= count: tokens.add(name)
    for key, value in latest.items():
        if value is not None: tokens.add(f"fund.{key}")
    if rows: tokens.add("fundamental_periods")
    for key, name in (("revenue", "aligned_revenue"), ("eps_diluted", "aligned_eps"), ("shares_diluted", "aligned_shares")):
        if aligned(rows, key): tokens.add(name)
    if aligned(rows, "revenue") and aligned(rows, "gross_profit"):
        tokens.update({"aligned_gross_margin", "aligned_margins"})
    if aligned(rows, "revenue") and aligned(rows, "operating_income"):
        tokens.update({"aligned_operating_margin", "aligned_margins"})
    revenue_pairs = sum(1 for row in rows if (row.get("metrics") or {}).get("revenue") is not None)
    if revenue_pairs >= 3: tokens.add("two_aligned_revenue_growths")
    fy = next((row for row in rows if str(row.get("fiscal_period")).upper() == "FY"), None)
    fy_metrics = (fy or {}).get("metrics") or {}
    if fy_metrics.get("eps_diluted") is not None: tokens.add("ttm_eps")
    if fy_metrics.get("revenue") is not None: tokens.add("ttm_revenue")
    if fy_metrics.get("operating_cash_flow") is not None and fy_metrics.get("capex") is not None:
        tokens.update({"ttm_fcf", "free_cash_flow", "period_duration"})
    if len([row for row in rows if str(row.get("fiscal_period")).upper() == "FY" and (row.get("metrics") or {}).get("revenue") is not None]) >= 2:
        tokens.add("historical_fundamentals")
    if "price_history" in tokens and latest.get("shares_diluted") is not None: tokens.add("market_cap")
    if "market_cap" in tokens and "ttm_revenue" in tokens: tokens.add("valuation_comparison")
    if "market_cap" in tokens and "ttm_fcf" in tokens: tokens.add("valuation_read")
    if nonempty(get_path(payload, "intelligence.catalysts")): tokens.update({"catalyst_evidence", "company_event"})
    if nonempty(get_path(payload, "intelligence.risks")): tokens.add("risk_evidence")
    if nonempty(get_path(payload, "intelligence.thesis")): tokens.update({"research_evidence", "saved_or_generated_thesis"})
    news = [row for row in bundle.get("news", []) if row.get("ticker") == ticker]
    if news: tokens.add("news_30d")
    if event_count: tokens.update({"earnings_event", "company_event"})
    if transcript_count: tokens.add("transcript_chunks")
    benchmark_counts = Counter(row.get("ticker") for row in bundle.get("prices", []))
    if benchmark_counts["SPY"] >= 253: tokens.update({"spy_1y", "betas"})
    if benchmark_counts["QQQ"] >= 253: tokens.add("qqq_1y")
    if benchmark_counts["XLK"] >= 253 or benchmark_counts["SOXX"] >= 253: tokens.add("sector_etf_1y")
    if "fund.gross_profit" in tokens and "fund.revenue" in tokens: tokens.add("gross_margin")
    if "fund.operating_income" in tokens and "fund.revenue" in tokens: tokens.add("operating_margin")
    if "aligned_revenue" in tokens and "aligned_margins" in tokens: tokens.add("aligned_revenue|aligned_margins")
    return tokens


def metric_status(item: Any, intelligence: dict[str, Any], tokens: set[str]) -> tuple[str, str]:
    current = get_path(intelligence, item.current_path)
    has_current = nonempty(current)
    inputs_ready = all(input_name in tokens for input_name in item.required_inputs)
    if item.classification == "UNAVAILABLE" or item.implementation_state == "NEW_INGESTION":
        return "UNAVAILABLE", "Requires ingestion not present in existing Supabase data."
    if item.implementation_state == "CONTEXT_REQUIRED":
        return "CONTEXT_REQUIRED", "Existing capability requires an authenticated portfolio/policy context."
    if has_current and item.implementation_state in {"CURRENT", "MODEL_LOGIC", "DETERMINISTIC_WIRING"}:
        return "AVAILABLE", "Current Research payload is non-null."
    if item.implementation_state == "CURRENT":
        return "UNAVAILABLE", "Current path is null or structurally empty."
    if inputs_ready and item.implementation_state == "DETERMINISTIC_WIRING":
        return "RECOVERABLE", "All disclosed existing inputs are present; deterministic wiring is missing."
    if inputs_ready and item.implementation_state == "MODEL_LOGIC":
        return "MODEL_READY", "Existing evidence is present, but approved model/policy logic is not wired."
    return "UNAVAILABLE", "One or more required existing inputs are absent."


def section_status(rows: list[dict[str, Any]], *, maximized: bool) -> str:
    core = [row for row in rows if row["status_role"] == "CORE"]
    usable = {"AVAILABLE"} | ({"RECOVERABLE", "MODEL_READY"} if maximized else set())
    count = sum(row["status"] in usable for row in core)
    if count == len(core) and core: return "SUCCESS"
    if count: return "PARTIAL"
    return "UNAVAILABLE"


def audit(tickers: list[str]) -> dict[str, Any]:
    universe = list(dict.fromkeys([*tickers, "SPY", "QQQ", "XLK", "SOXX"]))
    bundle = database.security_data(universe, price_limit=1400)
    result: dict[str, Any] = {"registry": registry_payload(), "tickers": {}}
    with database.postgres_connection() as conn:
        for ticker in tickers:
            master_row = conn.execute("SELECT * FROM public.security_master WHERE ticker=%s", (ticker,)).fetchone()
            event_count = conn.execute("SELECT count(*) AS count FROM public.market_events WHERE %s=ANY(tickers)", (ticker,)).fetchone()["count"]
            transcript_count = conn.execute(
                """SELECT count(*) AS count FROM public.documents d JOIN public.securities s ON s.id=d.security_id
                   WHERE s.ticker=%s AND d.document_type IN ('transcript','earnings_transcript')""", (ticker,),
            ).fetchone()["count"]
            payload = consolidated_research_security_overview(ticker, None, AUDIT_USER)
            intelligence = payload.get("intelligence") or {}
            tokens = input_tokens(ticker, bundle, payload, dict(master_row) if master_row else None, event_count, transcript_count)
            rows = []
            for item in REGISTRY:
                status, reason = metric_status(item, intelligence, tokens)
                rows.append({"key": item.key, "section": item.section, "classification": item.classification,
                             "status_role": item.status_role, "implementation_state": item.implementation_state,
                             "status": status, "reason": reason})
            by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows: by_section[row["section"]].append(row)
            section_rows = {
                section: {
                    "current_status": section_status(items, maximized=False),
                    "maximized_existing_status": section_status(items, maximized=True),
                    "counts": dict(Counter(item["status"] for item in items)),
                    "core_gaps": [item["key"] for item in items if item["status_role"] == "CORE" and item["status"] not in {"AVAILABLE", "RECOVERABLE", "MODEL_READY"}],
                }
                for section, items in by_section.items()
            }
            result["tickers"][ticker] = {
                "source_dates": {"price": get_path(intelligence, "market.as_of"), "fundamentals": payload.get("freshness", {}).get("fundamentals_as_of")},
                "events": event_count, "transcripts": transcript_count,
                "available_input_tokens": sorted(tokens), "sections": section_rows, "metrics": rows,
                "summary": dict(Counter(row["status"] for row in rows)),
            }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit the Research Metric Registry against existing EagleEyes data.")
    parser.add_argument("tickers", nargs="*", default=["AAPL", "MSFT", "NVDA"])
    parser.add_argument("--summary", action="store_true", help="Emit section and aggregate coverage without metric definitions/details.")
    args = parser.parse_args()
    output = audit([ticker.upper() for ticker in args.tickers])
    if args.summary:
        output["registry"] = {"version": output["registry"]["version"], "metric_count": len(REGISTRY)}
        for item in output["tickers"].values():
            item.pop("metrics", None)
            item.pop("available_input_tokens", None)
            for section in item["sections"].values():
                section["core_gap_count"] = len(section.pop("core_gaps", []))
    print(json.dumps(output, indent=2, default=str))
