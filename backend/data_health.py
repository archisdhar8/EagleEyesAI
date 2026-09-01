from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from . import database
from .ask_resolution import DataHealthDomain, DataHealthStatus


DOMAINS = (
    "prices", "fundamentals", "fundamental_history", "classifications", "events", "macro",
    "earnings_events", "macro_events", "company_catalysts", "prediction_market_events",
    "market", "prediction_markets", "portfolio_history", "score_history", "cash_hurdle",
)

REPAIR_ACTIONS = {
    "prices": "refresh_prices", "fundamentals": "refresh_fundamentals",
    "fundamental_history": "refresh_fundamental_history", "classifications": "reconcile_security_master",
    "events": "refresh_event_feeds", "macro": "refresh_macro_state", "market": "refresh_market_state",
    "earnings_events": "refresh_earnings_events", "macro_events": "refresh_macro_event_calendar",
    "company_catalysts": "refresh_company_catalysts", "prediction_market_events": "refresh_prediction_market_events",
    "prediction_markets": "refresh_prediction_markets", "portfolio_history": "materialize_portfolio_snapshot",
    "score_history": "materialize_score_snapshot", "cash_hurdle": "refresh_cash_hurdle",
}

MAX_AGE_DAYS = {
    "prices": 3, "fundamentals": 120, "fundamental_history": 120, "classifications": 365,
    "events": 2, "macro": 8, "earnings_events": 2, "macro_events": 2,
    "company_catalysts": 2, "prediction_market_events": 2, "market": 2, "prediction_markets": 2,
    "portfolio_history": 45, "score_history": 45, "cash_hurdle": 8,
}

_CACHE_TTL_SECONDS = 45.0
_DERIVED_CACHE: dict[tuple[str, str], tuple[float, list[DataHealthDomain]]] = {}
_DERIVED_CACHE_MAX_ENTRIES = 256


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def derive(user_id: str, portfolio_id: str, *, field_coverage: dict[str, float] | None = None) -> list[DataHealthDomain]:
    cache_key = (user_id, portfolio_id)
    if field_coverage is None:
        cached = _DERIVED_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return [state.model_copy(deep=True) for state in cached[1]]
    versions = database.analytical_dataset_versions(user_id, portfolio_id)
    existing: dict[str, dict[str, Any]] = {}
    try:
        existing = {row["domain"]: row for row in database.data_health_states(user_id, portfolio_id)}
    except Exception:
        existing = {}
    now = datetime.now(timezone.utc)
    states: list[DataHealthDomain] = []
    for domain in DOMAINS:
        saved = existing.get(domain) or {}
        version = versions.get(domain) or versions.get({
            "fundamental_history": "fundamentals", "classifications": "securities",
            "earnings_events": "events", "macro_events": "events", "company_catalysts": "events",
            "prediction_market_events": "events",
            "portfolio_history": "portfolio_holdings", "score_history": "portfolio_health",
            "cash_hurdle": "macro",
        }.get(domain, "")) or {}
        successful = _parse(saved.get("last_successful_update") or version.get("effective_through") or version.get("updated_at"))
        coverage = (field_coverage or {}).get(domain, saved.get("coverage"))
        if saved.get("status") == DataHealthStatus.FAILED.value:
            status = DataHealthStatus.FAILED
        elif not successful:
            status = DataHealthStatus.MISSING
        elif (now - successful).total_seconds() > MAX_AGE_DAYS[domain] * 86400:
            status = DataHealthStatus.STALE
        elif coverage is not None and float(coverage) < 1:
            status = DataHealthStatus.PARTIAL
        else:
            status = DataHealthStatus.CURRENT
        states.append(DataHealthDomain(
            domain=domain, status=status, coverage=coverage,
            freshness=successful.isoformat() if successful else None,
            last_successful_update=successful.isoformat() if successful else None,
            failure_reason=saved.get("failure_reason"), repair_action=REPAIR_ACTIONS[domain],
        ))
    if field_coverage is None:
        _DERIVED_CACHE[cache_key] = (time.monotonic(), [state.model_copy(deep=True) for state in states])
        while len(_DERIVED_CACHE) > _DERIVED_CACHE_MAX_ENTRIES:
            _DERIVED_CACHE.pop(next(iter(_DERIVED_CACHE)), None)
    return states


def persist(user_id: str, portfolio_id: str, states: list[DataHealthDomain]) -> None:
    for state in states:
        database.upsert_data_health_state(user_id, portfolio_id, state.domain, state.model_dump(mode="json"))
