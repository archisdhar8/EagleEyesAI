from __future__ import annotations

from backend import analytical_telemetry


def test_telemetry_allowlist_excludes_question_and_internal_error(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(analytical_telemetry, "record_metric", lambda name, **kwargs: captured.append((name, kwargs)))
    monkeypatch.setenv("ANALYTICAL_TELEMETRY_DURABLE", "0")

    analytical_telemetry.record_request(
        request_id="request-1", capability="portfolio_analysis", status="SUCCESS",
        question="private portfolio question", error_message_internal="secret",
    )

    name, payload = captured[0]
    assert name == "ask.capability.request"
    assert payload["persist"] is False
    assert payload["tags"] == {
        "request_id": "request-1", "capability": "portfolio_analysis", "status": "SUCCESS",
    }


def test_deadline_context_records_one_absolute_budget(monkeypatch) -> None:
    ticks = iter([10.25, 10.75])
    monkeypatch.setattr(analytical_telemetry.time, "monotonic", lambda: next(ticks))
    deadline = analytical_telemetry.DeadlineContext.from_budget(10.0, 2.0)

    assert deadline.remaining_ms() == 1750.0
    assert deadline.remaining_ms() == 1250.0
