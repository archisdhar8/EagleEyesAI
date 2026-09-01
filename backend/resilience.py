from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from .operational_monitoring import record_metric


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 2
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 1.0


class TTLCache:
    """Small process-local cache for disposable, reconstructable results."""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._values: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            value = self._values.get(key)
            if value is None:
                return None
            expires_at, payload = value
            if expires_at <= now:
                self._values.pop(key, None)
                return None
            return payload

    def put(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            if len(self._values) >= self.max_entries:
                oldest = min(self._values, key=lambda item: self._values[item][0])
                self._values.pop(oldest, None)
            self._values[key] = (time.monotonic() + ttl_seconds, value)

    def stats(self) -> dict[str, int]:
        """Return bounded, content-free telemetry about this disposable cache."""
        now = time.monotonic()
        with self._lock:
            expired = [key for key, (expires_at, _) in self._values.items() if expires_at <= now]
            for key in expired:
                self._values.pop(key, None)
            return {"entries": len(self._values), "max_entries": self.max_entries}


def retry_call(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    retryable: Callable[[Exception], bool],
    metric: str,
) -> T:
    """Retry only declared transient failures and never exceed the policy."""
    last_error: Exception | None = None
    for attempt in range(1, max(1, policy.attempts) + 1):
        started = time.perf_counter()
        try:
            result = operation()
            record_metric(f"{metric}.latency_ms", (time.perf_counter() - started) * 1000, tags={"attempt": attempt})
            return result
        except Exception as exc:
            last_error = exc
            if attempt >= policy.attempts or not retryable(exc):
                record_metric(f"{metric}.failure", tags={"attempt": attempt, "error_type": type(exc).__name__})
                raise
            record_metric(f"{metric}.retry", tags={"attempt": attempt, "error_type": type(exc).__name__})
            delay = min(policy.max_delay_seconds, policy.base_delay_seconds * (2 ** (attempt - 1)))
            time.sleep(delay + random.uniform(0, delay * 0.2))
    assert last_error is not None
    raise last_error
