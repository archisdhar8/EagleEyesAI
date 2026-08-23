from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .operational_monitoring import record_metric


def _durable() -> bool:
    return os.getenv("ANALYTICAL_TELEMETRY_DURABLE", "1").strip().lower() not in {"0", "false", "off", "no"}


@dataclass(frozen=True)
class DeadlineContext:
    started_monotonic: float
    absolute_deadline_monotonic: float

    @classmethod
    def from_budget(cls, started_monotonic: float, budget_seconds: float) -> "DeadlineContext":
        return cls(started_monotonic, started_monotonic + max(0.0, budget_seconds))

    def remaining_ms(self) -> float:
        return round(max(0.0, self.absolute_deadline_monotonic - time.monotonic()) * 1000, 2)


def _safe_tags(fields: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "request_id", "conversation_id", "capability", "intent", "dependency", "required",
        "request_started_at", "request_completed_at", "started_at", "completed_at",
        "total_latency_ms", "latency_ms", "deadline_remaining_at_start_ms",
        "deadline_remaining_at_end_ms", "input_fingerprint", "result_status",
        "verification_status", "entity_coverage", "field_coverage", "weight_coverage",
        "calculated_at", "effective_through", "oldest_required_input", "cache_state",
        "read_model_version", "gemini_started", "gemini_completed", "gemini_latency_ms",
        "persistence_status", "status", "error_class", "required_dependency_failures",
        "optional_dependency_failures",
        "read_model_type", "read_model_id", "read_model_state", "schema_version",
        "calculation_version", "builder_version", "cache_hit", "legacy_adapter_used",
        "input_fingerprint_match", "upstream_version_match", "stale_reason",
        "build_latency_ms", "build_status", "upstream_dependency",
        "absolute_deadline", "initial_budget_ms", "queue_wait_ms", "auth_latency_ms",
        "execution_started_at", "execution_completed_at", "nodes_total", "nodes_started",
        "nodes_completed", "nodes_timed_out", "nodes_skipped", "total_execution_ms",
        "deterministic_render_ms", "persistence_latency_ms", "duplicate_replay",
        "node_id", "depends_on", "start_ms", "end_ms", "configured_timeout_ms",
        "effective_timeout_ms",
    }
    return {key: value for key, value in fields.items() if key in allowed and value is not None}


def record_dependency(**fields: Any) -> None:
    record_metric("ask.capability.dependency", tags=_safe_tags(fields), persist=_durable())


def record_request(**fields: Any) -> None:
    record_metric("ask.capability.request", tags=_safe_tags(fields), persist=_durable())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
