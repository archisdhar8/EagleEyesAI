from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

from pydantic import BaseModel, Field, model_validator


ANALYSIS_SCHEMA_VERSION = "1"


class AnalysisStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    PENDING = "PENDING"


class VerificationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Coverage(BaseModel):
    requested_entities: list[str] = Field(default_factory=list)
    evaluated_entities: list[str] = Field(default_factory=list)
    missing_entities: list[str] = Field(default_factory=list)
    entity_coverage_percent: float | None = None

    required_fields: list[str] = Field(default_factory=list)
    available_required_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    field_coverage_percent: float | None = None

    requested_portfolio_weight: float | None = None
    evaluated_portfolio_weight: float | None = None
    weight_coverage_percent: float | None = None

    methodology: str = "Required fields must be non-null for an entity to count as analytically evaluated."

    @model_validator(mode="after")
    def normalize(self) -> "Coverage":
        self.requested_entities = list(dict.fromkeys(str(value).upper() for value in self.requested_entities if value))
        evaluated = set(str(value).upper() for value in self.evaluated_entities if value)
        self.evaluated_entities = [value for value in self.requested_entities if value in evaluated]
        self.missing_entities = [value for value in self.requested_entities if value not in evaluated]
        if self.entity_coverage_percent is None:
            self.entity_coverage_percent = round(
                100 * len(self.evaluated_entities) / len(self.requested_entities), 1,
            ) if self.requested_entities else None
        if self.requested_portfolio_weight is not None and self.evaluated_portfolio_weight is not None:
            self.weight_coverage_percent = round(
                100 * self.evaluated_portfolio_weight / self.requested_portfolio_weight, 1,
            ) if self.requested_portfolio_weight > 0 else None
        return self

    @classmethod
    def not_tracked(cls) -> "Coverage":
        return cls(methodology="Coverage was not tracked by the adapted legacy capability.")


class Freshness(BaseModel):
    calculated_at: datetime
    effective_through: datetime | None = None
    oldest_required_input: datetime | None = None
    newest_input: datetime | None = None
    stale: bool | None = None
    stale_dependencies: list[str] = Field(default_factory=list)
    methodology: str = "effective_through is bounded by the oldest known required input; calculation time does not imply source freshness."


class LineageItem(BaseModel):
    domain: str
    dataset: str
    provider: str | None = None
    source_version: str | None = None
    effective_at: datetime | None = None
    claim_group: str | None = None


class DependencyResult(BaseModel):
    name: str
    required: bool
    status: AnalysisStatus
    latency_ms: float | None = None
    freshness: Freshness | None = None
    cache_state: str = "not_tracked"
    error_class: str | None = None
    # Useful to server-side callers while deliberately omitted from API/log serialization.
    error_message_internal: str | None = Field(default=None, exclude=True, repr=False)
    coverage: Coverage | None = None


class Prerequisite(BaseModel):
    name: str
    satisfied: bool
    reason: str


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    severity: VerificationSeverity = VerificationSeverity.ERROR
    message: str


class VerificationResult(BaseModel):
    passed: bool
    answer_allowed: bool
    recommendation_allowed: bool
    checks: list[VerificationCheck] = Field(default_factory=list)


class JobReference(BaseModel):
    id: str
    status: AnalysisStatus = AnalysisStatus.PENDING
    kind: str
    status_url: str | None = None


class AnalysisResult(BaseModel):
    capability: str
    schema_version: str = ANALYSIS_SCHEMA_VERSION
    calculation_version: str
    input_fingerprint: str | None = None
    status: AnalysisStatus
    data: Any
    coverage: Coverage
    freshness: Freshness
    lineage: list[LineageItem] = Field(default_factory=list)
    dependencies: list[DependencyResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    verification: VerificationResult
    job: JobReference | None = None
    summary: dict[str, Any] | None = None


def derive_analysis_status(
    dependencies: Iterable[DependencyResult], *, prerequisites: Iterable[Prerequisite] = (),
    has_usable_data: bool = True,
) -> AnalysisStatus:
    """Apply the shared required/optional dependency semantics."""
    dependency_rows = list(dependencies)
    if any(row.required and row.status == AnalysisStatus.FAILED for row in dependency_rows):
        return AnalysisStatus.FAILED
    if not has_usable_data or any(not row.satisfied for row in prerequisites):
        return AnalysisStatus.UNAVAILABLE
    if any(row.required and row.status in {AnalysisStatus.UNAVAILABLE, AnalysisStatus.PENDING} for row in dependency_rows):
        return AnalysisStatus.UNAVAILABLE
    if any(row.status != AnalysisStatus.SUCCESS for row in dependency_rows):
        return AnalysisStatus.PARTIAL
    return AnalysisStatus.SUCCESS


def stable_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def build_freshness(
    required_inputs: Iterable[tuple[str, Any]], *, calculated_at: datetime | None = None,
    stale_after_days: int = 7,
) -> Freshness:
    calculated = calculated_at or datetime.now(timezone.utc)
    parsed = [(name, timestamp) for name, value in required_inputs if (timestamp := parse_timestamp(value)) is not None]
    timestamps = [timestamp for _, timestamp in parsed]
    oldest = min(timestamps, default=None)
    newest = max(timestamps, default=None)
    stale_dependencies = [
        name for name, timestamp in parsed
        if (calculated - timestamp).total_seconds() > stale_after_days * 86_400
    ]
    return Freshness(
        calculated_at=calculated,
        effective_through=oldest,
        oldest_required_input=oldest,
        newest_input=newest,
        stale=bool(stale_dependencies) if timestamps else None,
        stale_dependencies=sorted(set(stale_dependencies)),
    )


def _field_value(row: dict[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _analytically_available(value: Any) -> bool:
    """Treat empty containers/text as missing, while preserving valid zero/false values."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def build_entity_coverage(
    requested_entities: Iterable[str], rows: Iterable[dict[str, Any]], required_fields: Iterable[str], *,
    weights: dict[str, float] | None = None, entity_key: str = "ticker",
) -> Coverage:
    requested = list(dict.fromkeys(str(value).upper() for value in requested_entities if value))
    fields = list(dict.fromkeys(str(value) for value in required_fields if value))
    indexed = {
        str(row.get(entity_key) or row.get("symbol") or "").upper(): row
        for row in rows if row.get(entity_key) or row.get("symbol")
    }
    evaluated: list[str] = []
    available_cells = 0
    for entity in requested:
        row = indexed.get(entity) or {}
        present = [field for field in fields if _analytically_available(_field_value(row, field))]
        available_cells += len(present)
        if row and (not fields or len(present) == len(fields)):
            evaluated.append(entity)
    available_fields = [
        field for field in fields
        if any(_analytically_available(_field_value(indexed.get(entity) or {}, field)) for entity in requested)
    ]
    total_cells = len(requested) * len(fields)
    normalized_weights = {str(key).upper(): max(0.0, float(value or 0)) for key, value in (weights or {}).items()}
    requested_weight = sum(normalized_weights.get(entity, 0.0) for entity in requested) if weights is not None else None
    evaluated_weight = sum(normalized_weights.get(entity, 0.0) for entity in evaluated) if weights is not None else None
    return Coverage(
        requested_entities=requested,
        evaluated_entities=evaluated,
        required_fields=fields,
        available_required_fields=available_fields,
        missing_required_fields=[field for field in fields if field not in available_fields],
        field_coverage_percent=round(100 * available_cells / total_cells, 1) if total_cells else None,
        requested_portfolio_weight=requested_weight,
        evaluated_portfolio_weight=evaluated_weight,
    )


def status_from_legacy(value: Any) -> AnalysisStatus:
    return {
        "complete": AnalysisStatus.SUCCESS,
        "success": AnalysisStatus.SUCCESS,
        "partial": AnalysisStatus.PARTIAL,
        "unavailable": AnalysisStatus.UNAVAILABLE,
        "failed": AnalysisStatus.FAILED,
        "pending": AnalysisStatus.PENDING,
    }.get(str(value or "").lower(), AnalysisStatus.PARTIAL)


def adapt_legacy_tool_result(
    result: dict[str, Any], *, capability: str | None = None,
    full_data: Any | None = None, calculation_version: str = "legacy-adapter-v1",
    input_fingerprint: str | None = None,
) -> AnalysisResult:
    status = status_from_legacy(result.get("status"))
    as_of = result.get("as_of") or (result.get("summary") or {}).get("as_of")
    coverage = Coverage.not_tracked()
    raw_coverage = result.get("coverage")
    if isinstance(raw_coverage, dict):
        requested_count = int(raw_coverage.get("requested") or 0)
        evaluated_count = int(raw_coverage.get("evaluated") or 0)
        requested = [f"LEGACY_ENTITY_{index + 1}" for index in range(requested_count)]
        coverage = Coverage(
            requested_entities=requested,
            evaluated_entities=requested[:evaluated_count],
            methodology="Adapted legacy count coverage; entity identities and field coverage were not tracked.",
        )
    prerequisites: list[Prerequisite] = []
    if status == AnalysisStatus.UNAVAILABLE:
        message = str((result.get("summary") or {}).get("message") or "Legacy capability is unavailable.")
        prerequisites.append(Prerequisite(name="legacy_capability_available", satisfied=False, reason=message))
    check = VerificationCheck(
        name="legacy_adapter_metadata",
        passed=False,
        severity=VerificationSeverity.WARNING,
        message="This result was adapted from a legacy tool; field coverage, lineage, and source freshness may be untracked.",
    )
    return AnalysisResult(
        capability=capability or str(result.get("tool_name") or "legacy_tool"),
        calculation_version=calculation_version,
        input_fingerprint=input_fingerprint,
        status=status,
        data=full_data if full_data is not None else (result.get("summary") or result),
        coverage=coverage,
        freshness=build_freshness([("legacy_as_of", as_of)]),
        lineage=[],
        dependencies=[DependencyResult(
            name=str(result.get("tool_name") or "legacy_tool"), required=True, status=status,
            cache_state="not_tracked", coverage=coverage,
        )],
        limitations=["Converted through the legacy AnalysisResult adapter; unavailable metadata was not fabricated."],
        warnings=list((result.get("summary") or {}).get("warnings") or []),
        prerequisites=prerequisites,
        verification=VerificationResult(
            passed=status == AnalysisStatus.SUCCESS,
            answer_allowed=status != AnalysisStatus.FAILED,
            recommendation_allowed=False,
            checks=[check],
        ),
        job=JobReference(id=str(result["job_id"]), kind=str(result.get("job_type") or result.get("tool_name") or "analytics"),
                         status=AnalysisStatus.PENDING, status_url=f"/api/analytics/jobs/{result['job_id']}")
            if result.get("job_id") and status == AnalysisStatus.PENDING else None,
        summary=result.get("summary") if isinstance(result.get("summary"), dict) else None,
    )


def canonical_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    value = result.get("analysis_result")
    return value if isinstance(value, dict) else None


def canonical_data(result: dict[str, Any]) -> Any:
    payload = canonical_payload(result)
    return payload.get("data") if payload else (result.get("summary") or {})


def with_canonical_result(legacy: dict[str, Any], analysis: AnalysisResult) -> dict[str, Any]:
    return {**legacy, "analysis_result": analysis.model_dump(mode="json", exclude_none=True)}


def apply_request_verification(analysis: AnalysisResult, verification: Any) -> AnalysisResult:
    """Merge the existing Ask verifier into the canonical contract during migration."""
    payload = verification.payload() if hasattr(verification, "payload") else dict(verification or {})
    failures = [str(value) for value in payload.get("failures") or []]
    warnings = [str(value) for value in payload.get("warnings") or []]

    def check_name(message: str) -> str:
        lowered = message.lower()
        if "portfolio context" in lowered:
            return "portfolio_context_match"
        if "coverage" in lowered:
            return "coverage_threshold"
        if "scenario" in lowered or "mapping" in lowered:
            return "scenario_compatibility"
        if "optimizer" in lowered or "feasible" in lowered:
            return "optimizer_feasible"
        if "candidate" in lowered or "mislabeled" in lowered:
            return "candidate_type_valid"
        if "prerequisite" in lowered or "unavailable" in lowered or "thesis" in lowered:
            return "required_dependencies_available"
        return "request_verification"

    checks = list(analysis.verification.checks)
    checks.extend(VerificationCheck(
        name=check_name(message), passed=False, severity=VerificationSeverity.ERROR, message=message,
    ) for message in failures)
    checks.extend(VerificationCheck(
        name=check_name(message), passed=False, severity=VerificationSeverity.WARNING, message=message,
    ) for message in warnings)
    if not failures and not warnings:
        checks.append(VerificationCheck(
            name="request_verification", passed=True, severity=VerificationSeverity.INFO,
            message="The existing request-scoped verifier reported no additional limitations.",
        ))
    answer_allowed = bool(payload.get("answer_allowed", True)) and analysis.verification.answer_allowed
    recommendation_allowed = bool(payload.get("recommendation_allowed", True)) and analysis.verification.recommendation_allowed
    if analysis.status == AnalysisStatus.UNAVAILABLE:
        status = AnalysisStatus.UNAVAILABLE
    elif not answer_allowed:
        status = AnalysisStatus.FAILED
    elif failures or warnings or analysis.status == AnalysisStatus.PARTIAL:
        status = AnalysisStatus.PARTIAL
    else:
        status = analysis.status
    return analysis.model_copy(update={
        "status": status,
        "warnings": list(dict.fromkeys([*analysis.warnings, *warnings])),
        "verification": VerificationResult(
            passed=status == AnalysisStatus.SUCCESS and all(check.passed for check in checks),
            answer_allowed=answer_allowed,
            recommendation_allowed=recommendation_allowed,
            checks=checks,
        ),
    })
