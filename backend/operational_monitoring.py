from __future__ import annotations

import json
import logging
import math
import threading
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("eagleeyes.operations")
_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=10_000)


def record_metric(name: str, value: float = 1.0, *, tags: dict[str, Any] | None = None, persist: bool = False) -> None:
    event = {"name": name, "value": float(value), "tags": tags or {}, "observed_at": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _events.append(event)
    if persist:
        try:
            from . import database
            database.save_operational_event(event)
        except Exception:
            logger.exception("operational_event_persistence_failed", extra={"metric_name": name})


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, math.ceil(probability * len(ordered)) - 1)], 2)


def operational_snapshot() -> dict[str, Any]:
    with _lock:
        events = list(_events)
    counts = Counter(event["name"] for event in events)
    durations: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if event["name"].endswith(".latency_ms"):
            durations[event["name"]].append(event["value"])
    return {
        "version": "operational-monitoring-v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(events),
        "counts": dict(counts),
        "latency": {name: {"p50_ms": _percentile(values, .50), "p95_ms": _percentile(values, .95), "samples": len(values)} for name, values in durations.items()},
        "tracked": [
            "api latency", "provider freshness and failures", "Gemini planning failures",
            "widget verification failures", "partial success", "cache hits", "calculation versions",
            "cross-user access failures", "backtest stability and coverage deterioration",
        ],
    }


def structured_log(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str, separators=(",", ":")))
