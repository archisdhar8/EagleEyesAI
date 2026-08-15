from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import requests


OBSERVATION_VERSION = "market-observation-v1"
EVENT_VERSION = "market-event-normalization-v1"
VALID_STATUSES = {"live", "delayed", "end-of-day", "cached", "stale"}


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def observation_status(
    observed_at: Any, *, latency_class: str | None = None, retrieved_at: Any = None,
    stale_after_seconds: int | None = None,
) -> str:
    """Return a truthful status from provider metadata; never infer live from recency alone."""
    declared = str(latency_class or "").lower().replace("_", "-")
    if declared not in VALID_STATUSES:
        declared = "end-of-day"
    observed = _utc(observed_at)
    retrieved = _utc(retrieved_at) or datetime.now(timezone.utc)
    default_stale = 120 if declared == "live" else 1200 if declared == "delayed" else 7 * 86400
    if observed is None or (retrieved - observed).total_seconds() > (stale_after_seconds or default_stale):
        return "stale"
    return declared


def normalize_observation(row: dict[str, Any], *, default_status: str = "end-of-day") -> dict[str, Any]:
    observed_at = row.get("observed_at") or row.get("exchange_timestamp") or row.get("date") or row.get("as_of")
    retrieved_at = row.get("retrieved_at") or row.get("fetched_at") or datetime.now(timezone.utc).isoformat()
    latency = row.get("latency_class") or row.get("data_status") or default_status
    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "value": row.get("value", row.get("close")),
        "observed_at": str(observed_at) if observed_at else None,
        "retrieved_at": str(retrieved_at),
        "provider": row.get("provider") or "stored adjusted daily prices",
        "dataset": row.get("dataset") or "adjusted_daily_prices",
        "latency_class": latency,
        "data_status": observation_status(observed_at, latency_class=latency, retrieved_at=retrieved_at, stale_after_seconds=row.get("stale_after_seconds")),
        "entitlement": row.get("entitlement") or "end_of_day",
        "source_url": row.get("source_url") or row.get("source"),
        "version": OBSERVATION_VERSION,
    }


class MarketObservationProvider(Protocol):
    def latest(self, tickers: list[str]) -> list[dict[str, Any]]: ...


class EventProvider(Protocol):
    def upcoming(self, tickers: list[str], days: int = 45) -> list[dict[str, Any]]: ...


@dataclass
class StoredEventProvider:
    loader: Callable[[list[str], int], list[dict[str, Any]]]

    def upcoming(self, tickers: list[str], days: int = 45) -> list[dict[str, Any]]:
        return self.loader(tickers, days)


@dataclass
class ResearchMarketEventProvider:
    research: list[dict[str, Any]]

    def upcoming(self, tickers: list[str], days: int = 45) -> list[dict[str, Any]]:
        allowed = {ticker.upper() for ticker in tickers}
        rows = []
        for research_row in self.research:
            ticker = str(research_row.get("ticker") or "").upper()
            if allowed and ticker and ticker not in allowed:
                continue
            for market in research_row.get("prediction_markets") or []:
                if not market.get("closes_at"):
                    continue
                rows.append({
                    "id": f"{market.get('provider')}:{market.get('id')}",
                    "external_id": str(market.get("id") or ""), "provider": market.get("provider") or "prediction market",
                    "event_type": "market_event", "title": market.get("title"), "starts_at": market.get("closes_at"),
                    "tickers": [ticker] if ticker else [], "source_url": market.get("source"),
                    "verified_at": market.get("observed_at"), "estimated": False,
                    "metadata": {"evidence_type": market.get("evidence_type"), "confidence": market.get("confidence")},
                })
        return rows


@dataclass
class CompositeEventProvider:
    providers: list[EventProvider]

    def upcoming(self, tickers: list[str], days: int = 45) -> list[dict[str, Any]]:
        rows = []
        for provider in self.providers:
            try:
                rows.extend(provider.upcoming(tickers, days))
            except Exception:
                continue
        return rows


class PolygonSnapshotProvider:
    """Optional snapshot adapter. Live is allowed only with an explicit entitlement flag."""

    endpoint = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"

    def latest(self, tickers: list[str]) -> list[dict[str, Any]]:
        api_key = os.getenv("POLYGON_API_KEY", "").strip()
        if not api_key or not tickers:
            return []
        response = requests.get(self.endpoint, params={"tickers": ",".join(tickers[:100]), "apiKey": api_key}, timeout=12)
        response.raise_for_status()
        now = datetime.now(timezone.utc)
        entitled = os.getenv("POLYGON_REALTIME_ENTITLED", "").lower() == "true"
        latency = "live" if entitled else "delayed"
        rows = []
        for item in response.json().get("tickers") or []:
            trade = item.get("lastTrade") or {}
            day = item.get("day") or {}
            value = trade.get("p") or day.get("c")
            timestamp_ns = trade.get("t")
            observed = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, timezone.utc) if timestamp_ns else now
            if value is None:
                continue
            rows.append(normalize_observation({
                "ticker": item.get("ticker"), "value": value, "observed_at": observed.isoformat(),
                "retrieved_at": now.isoformat(), "provider": "Polygon snapshot", "dataset": "stock_snapshot",
                "latency_class": latency, "entitlement": "real_time" if entitled else "provider_delayed",
                "source_url": "https://polygon.io/docs/stocks/get_v2_snapshot_locale_us_markets_stocks_tickers",
            }, default_status=latency))
        return rows


def overlay_observations(price_rows: list[dict[str, Any]], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = list(price_rows)
    latest = {row["ticker"]: row for row in observations if row.get("ticker") and row.get("value") is not None}
    latest_stored: dict[str, datetime] = {}
    for row in price_rows:
        ticker = str(row.get("ticker") or "").upper()
        observed = _utc(row.get("date") or row.get("observed_at"))
        if ticker and observed and observed > latest_stored.get(ticker, datetime.min.replace(tzinfo=timezone.utc)):
            latest_stored[ticker] = observed
    for ticker, row in latest.items():
        observed = _utc(row.get("observed_at"))
        # A delayed or cached snapshot must never displace a newer validated
        # adjusted close. Equal-session snapshots are skipped because the
        # stored bar is the canonical corporate-action-adjusted observation.
        if observed is None or observed <= latest_stored.get(ticker, datetime.min.replace(tzinfo=timezone.utc)):
            continue
        output.append({
            "ticker": ticker, "date": row["observed_at"], "close": row["value"],
            "provider": row["provider"], "fetched_at": row["retrieved_at"],
            "latency_class": row["latency_class"], "data_status": row["data_status"],
            "entitlement": row["entitlement"], "source_url": row.get("source_url"),
        })
    return output


def _event_key(event: dict[str, Any]) -> str:
    external = str(event.get("external_id") or event.get("id") or "")
    provider = str(event.get("provider") or "unknown").lower()
    if external:
        return f"{provider}:{external}"
    title = " ".join(str(event.get("title") or "").lower().split())
    starts = str(event.get("starts_at") or event.get("event_at") or "")[:16]
    tickers = ",".join(sorted(str(item).upper() for item in event.get("tickers") or []))
    return hashlib.sha256(f"{title}|{starts}|{tickers}".encode()).hexdigest()[:24]


def normalize_events(events: list[dict[str, Any]], tickers: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = datetime.now(timezone.utc)
    normalized: dict[str, dict[str, Any]] = {}
    for source in events:
        starts = _utc(source.get("starts_at") or source.get("event_at"))
        if starts is None or starts < now - timedelta(hours=2):
            continue
        verified = _utc(source.get("verified_at") or source.get("fetched_at"))
        metadata = dict(source.get("metadata") or {})
        status = str(source.get("event_status") or metadata.get("event_status") or "scheduled")
        item = {
            **source, "id": str(source.get("id") or _event_key(source)), "dedupe_key": _event_key(source),
            "starts_at": starts.isoformat(), "verified_at": verified.isoformat() if verified else None,
            "event_status": status, "timing_status": "estimated" if bool(source.get("estimated", metadata.get("estimated", False))) else "confirmed",
            "timezone": source.get("timezone") or metadata.get("timezone") or "UTC",
            "tickers": sorted({str(value).upper() for value in source.get("tickers") or []}),
            "version": EVENT_VERSION,
        }
        current = normalized.get(item["dedupe_key"])
        if current is None or str(item.get("verified_at") or "") > str(current.get("verified_at") or ""):
            normalized[item["dedupe_key"]] = item
    rows = sorted(normalized.values(), key=lambda item: (item["starts_at"], item["title"]))
    requested = sorted({ticker.upper() for ticker in tickers if ticker and ticker.upper() != "CASH"})
    earnings = {ticker for row in rows if row.get("event_type") == "earnings" for ticker in row.get("tickers") or []}
    return rows, {
        "version": EVENT_VERSION,
        "requested_tickers": requested,
        "earnings_covered_tickers": sorted(set(requested) & earnings),
        "earnings_missing_tickers": sorted(set(requested) - earnings),
        "earnings_coverage_ratio": len(set(requested) & earnings) / len(requested) if requested else None,
        "macro_release_count": sum(row.get("event_type") == "macro_release" for row in rows),
        "deduplicated_count": max(0, len(events) - len(rows)),
        "note": "Missing coverage means no validated event is stored; it does not prove that no event exists.",
    }
