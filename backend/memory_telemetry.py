from __future__ import annotations

"""Low-overhead process memory telemetry for bounded analytical routes."""

import json
import logging
import os
import resource
import sys
import subprocess
import threading
import time
from typing import Any, Mapping


LOGGER = logging.getLogger("eagleeyes.memory")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.propagate = False
_REQUEST_LOCK = threading.Lock()
_ACTIVE_REQUESTS = 0


def begin_request() -> tuple[int, int | None, float]:
    global _ACTIVE_REQUESTS
    with _REQUEST_LOCK:
        _ACTIVE_REQUESTS += 1
        active = _ACTIVE_REQUESTS
    return active, rss_bytes(), time.perf_counter()


def end_request() -> int:
    global _ACTIVE_REQUESTS
    with _REQUEST_LOCK:
        _ACTIVE_REQUESTS = max(0, _ACTIVE_REQUESTS - 1)
        return _ACTIVE_REQUESTS


def active_requests() -> int:
    with _REQUEST_LOCK:
        return _ACTIVE_REQUESTS


def rss_bytes() -> int | None:
    """Return current resident bytes without adding a runtime dependency."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        if sys.platform == "darwin":
            try:
                result = subprocess.run(
                    ["ps", "-o", "rss=", "-p", str(os.getpid())],
                    capture_output=True, text=True, timeout=1, check=True,
                )
                return int(result.stdout.strip()) * 1024
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        # ru_maxrss is a peak, so callers label it separately and never treat
        # it as current.
        return None


def peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def json_size_bytes(payload: Any) -> int:
    return len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))


def estimated_size_bytes(payload: Any, *, max_objects: int = 20_000) -> int:
    """Bounded recursive size estimate for diagnostics; never serializes content."""
    seen: set[int] = set()
    pending = [payload]
    total = 0
    while pending and len(seen) < max_objects:
        value = pending.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(value)
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
    return total


def emit(route: str, phase: str, *, started_rss: int | None = None, details: Mapping[str, Any] | None = None) -> None:
    current = rss_bytes()
    LOGGER.info(
        "memory_telemetry %s",
        json.dumps({
            "route": route, "phase": phase, "rss_bytes": current,
            "rss_delta_bytes": current - started_rss if current is not None and started_rss is not None else None,
            "process_peak_rss_bytes": peak_rss_bytes(), **dict(details or {}),
        }, default=str, separators=(",", ":")),
    )
