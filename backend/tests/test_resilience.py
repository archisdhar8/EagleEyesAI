from __future__ import annotations

import time

import pytest

from backend.resilience import RetryPolicy, TTLCache, retry_call


def test_retry_call_is_bounded_and_recovers_from_declared_transient_failure() -> None:
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary")
        return "ready"

    result = retry_call(
        operation,
        policy=RetryPolicy(attempts=2, base_delay_seconds=0, max_delay_seconds=0),
        retryable=lambda exc: isinstance(exc, TimeoutError),
        metric="test.retry",
    )
    assert result == "ready"
    assert calls == 2


def test_retry_call_does_not_retry_permanent_errors() -> None:
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("invalid input")

    with pytest.raises(ValueError):
        retry_call(
            operation,
            policy=RetryPolicy(attempts=3, base_delay_seconds=0, max_delay_seconds=0),
            retryable=lambda exc: isinstance(exc, TimeoutError),
            metric="test.retry",
        )
    assert calls == 1


def test_ttl_cache_expires_disposable_results() -> None:
    cache = TTLCache(max_entries=2)
    cache.put("answer", {"ok": True}, ttl_seconds=.01)
    assert cache.get("answer") == {"ok": True}
    time.sleep(.02)
    assert cache.get("answer") is None


def test_ttl_cache_stats_exposes_only_bounded_counts() -> None:
    cache = TTLCache(max_entries=2)
    cache.put("answer", {"private": "content"}, ttl_seconds=60)
    assert cache.stats() == {"entries": 1, "max_entries": 2}
