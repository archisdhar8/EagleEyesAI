from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
import atexit
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("eagleeyes.operations")
_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=10_000)
_persist_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
_persist_thread: threading.Thread | None = None
_persist_thread_lock = threading.Lock()
_persist_stop = threading.Event()


def _persist_worker() -> None:
    while not _persist_stop.is_set() or not _persist_queue.empty():
        batch: list[dict[str, Any]] = []
        try:
            batch.append(_persist_queue.get(timeout=.2))
        except queue.Empty:
            continue
        deadline = time.monotonic() + .05
        while len(batch) < 100 and time.monotonic() < deadline:
            try:
                batch.append(_persist_queue.get_nowait())
            except queue.Empty:
                break
        try:
            from . import database
            database.save_operational_events(batch)
        except Exception:
            logger.exception("operational_event_batch_persistence_failed", extra={"event_count": len(batch)})
        finally:
            for _ in batch:
                _persist_queue.task_done()


def _ensure_persist_worker() -> None:
    global _persist_thread
    with _persist_thread_lock:
        if _persist_thread is None or not _persist_thread.is_alive():
            _persist_thread = threading.Thread(target=_persist_worker, name="telemetry-outbox", daemon=True)
            _persist_thread.start()


def flush_persisted_metrics(timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while _persist_queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(.01)


def _shutdown_persist_worker() -> None:
    _persist_stop.set()
    flush_persisted_metrics()


atexit.register(_shutdown_persist_worker)


def record_metric(name: str, value: float = 1.0, *, tags: dict[str, Any] | None = None, persist: bool = False) -> None:
    event = {"name": name, "value": float(value), "tags": tags or {}, "observed_at": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _events.append(event)
    if persist:
        if os.getenv("OPERATIONAL_TELEMETRY_ASYNC", "1").strip().lower() in {"1", "true", "on", "yes"}:
            _ensure_persist_worker()
            try:
                _persist_queue.put_nowait(event)
            except queue.Full:
                logger.warning("operational_event_queue_full", extra={"metric_name": name})
        else:
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
