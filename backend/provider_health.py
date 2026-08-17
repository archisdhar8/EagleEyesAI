from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from . import database


PROVIDER_VERSION = "provider-health-v1"


def _latest(status: dict[str, Any], names: set[str]) -> dict[str, Any] | None:
    candidates = [row for row in status.get("providers", []) if str(row.get("provider") or "").lower() in names]
    return max(candidates, key=lambda row: str(row.get("fetched_at") or ""), default=None)


def _rate_limit(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = ("rate_limit_remaining", "quota_remaining", "remaining", "retry_after", "rate_limit_reset")
    values = {key: metadata[key] for key in keys if key in metadata}
    return {"status": "reported" if values else "not_reported", **values}


def _entry(
    key: str, label: str, configured: bool, latest: dict[str, Any] | None,
    datasets: list[str], fallbacks: list[str], coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not configured:
        state = "unconfigured"
    elif latest and latest.get("status") != "success":
        state = "degraded"
    elif latest:
        state = "healthy"
    else:
        state = "awaiting_data"
    metadata = dict((latest or {}).get("metadata") or {})
    window=dict((latest or {}).get("window") or {})
    attempts=int(window.get("attempts") or 0);successes=int(window.get("successes") or 0)
    last_success=window.get("last_success_at")
    stale_hours=None
    if last_success:
        try: stale_hours=round((datetime.now(timezone.utc)-datetime.fromisoformat(str(last_success).replace("Z","+00:00"))).total_seconds()/3600,1)
        except ValueError: pass
    return {
        "key": key, "label": label, "status": state, "configured": configured,
        "last_attempt_at": (latest or {}).get("fetched_at"),
        "effective_through": (latest or {}).get("as_of"),
        "failure_reason": "Provider request failed; the last validated snapshot remains in use." if (latest or {}).get("error") else None,
        "last_success_at": last_success, "stale_duration_hours": stale_hours,
        "recent_attempts": attempts, "recent_error_rate": round((attempts-successes)/attempts,3) if attempts else None,
        "datasets": datasets,
        "coverage": coverage or {}, "fallbacks": fallbacks,
        # Provider metadata is deliberately not returned wholesale because it may
        # contain request details. Only the rate-limit allowlist above is public.
        "rate_limit": _rate_limit(metadata),
    }


def build_provider_health() -> dict[str, Any]:
    status = database.provider_data_status()
    coverage_rows = status.get("price_coverage", [])
    price_coverage = {
        "providers": coverage_rows,
        "symbols": sum(int(row.get("symbols") or 0) for row in coverage_rows),
        "bars": sum(int(row.get("bars") or 0) for row in coverage_rows),
        "earliest": min((row.get("earliest") for row in coverage_rows if row.get("earliest")), default=None),
        "latest": max((row.get("latest") for row in coverage_rows if row.get("latest")), default=None),
    }
    providers = [
        _entry("supabase", "Supabase authentication and storage", bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_SECRET_KEY"))), None,
               ["authentication", "RLS-protected research storage"], ["None; authentication failures block private data"], {"storage": status.get("storage")}),
        _entry("fred", "FRED / ALFRED macro data", bool(os.getenv("FRED_API_KEY")), _latest(status, {"fred", "alfred"}),
               ["macro observations", "point-in-time regime inputs"], ["Latest validated stored macro snapshot"]),
        _entry("prices", "Corporate-action-adjusted prices", bool(os.getenv("TIINGO_API_KEY") or os.getenv("POLYGON_API_KEY")), _latest(status, {"tiingo", "polygon", "polygon_history"}),
               ["daily adjusted prices", "returns", "drawdowns", "correlations"], ["Tiingo → Polygon", "Security → sector ETF → VTI"], price_coverage),
        _entry("market_snapshots", "Market snapshot observations", os.getenv("MARKET_SNAPSHOT_MODE", "").lower() == "polygon" and bool(os.getenv("POLYGON_API_KEY")), _latest(status, {"polygon_snapshot"}),
               ["live or delayed market snapshots", "Today market levels"], ["End-of-day adjusted prices", "Latest validated briefing snapshot"],
               {"mode": os.getenv("MARKET_SNAPSHOT_MODE", "disabled"), "real_time_entitled": os.getenv("POLYGON_REALTIME_ENTITLED", "").lower() == "true", "stored_observations": status.get("counts", {}).get("market_observations", 0), "effective_through": status.get("freshness", {}).get("market_observations")}),
        _entry("events", "Earnings and macro calendar", True, _latest(status, {"earnings_calendar", "economic_calendar", "market_events"}),
               ["earnings dates", "macro releases", "company catalysts"], ["Stored validated events", "Explicit missing-coverage warning"],
               {"stored_events": status.get("counts", {}).get("market_events", 0), "verified_through": status.get("freshness", {}).get("market_events")}),
        _entry("kalshi", "Kalshi prediction markets", True, _latest(status, {"kalshi"}),
               ["macro contract discovery", "probability snapshots"], ["Stored snapshot", "macro trend prior"]),
        _entry("polymarket", "Polymarket prediction markets", True, _latest(status, {"polymarket"}),
               ["macro and company-event discovery", "probability snapshots"], ["Stored snapshot", "macro trend prior"]),
        _entry("sec", "SEC Company Facts", bool(os.getenv("SEC_USER_AGENT")), _latest(status, {"sec", "sec_companyfacts"}),
               ["primary public fundamentals"], ["Latest validated stored fundamentals"]),
        _entry("gemini", "Gemini planner and narrator", bool(os.getenv("GEMINI_API_KEY")), _latest(status, {"gemini"}),
               ["structured dashboard planning", "evidence-grounded narration"], ["Deterministic compiler", "Template-only explanation"]),
    ]
    counts = {state: sum(row["status"] == state for row in providers) for state in ("healthy", "awaiting_data", "degraded", "unconfigured")}
    return {
        "as_of": datetime.now(timezone.utc).isoformat(), "version": PROVIDER_VERSION,
        "summary": {"total": len(providers), **counts, "storage": status.get("storage")},
        "providers": providers,
        "lineage": {"source": "provider_fetches plus environment capability checks", "calculation_version": PROVIDER_VERSION},
        "warnings": [f"{row['label']}: {row['status']}" for row in providers if row["status"] in {"degraded", "unconfigured"}],
    }
