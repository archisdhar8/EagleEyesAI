from __future__ import annotations

"""Low-overhead process memory telemetry for bounded analytical routes."""

import json
import logging
import os
import resource
import sys
from typing import Any, Mapping


LOGGER = logging.getLogger("eagleeyes.memory")


def rss_bytes() -> int | None:
    """Return current resident bytes without adding a runtime dependency."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        # ru_maxrss is the only dependency-free fallback on macOS. It is a
        # peak, so callers label it separately and never treat it as current.
        return None


def peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def json_size_bytes(payload: Any) -> int:
    return len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))


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
