from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from . import database
from .analytical_contract import (
    AnalysisResult, AnalysisStatus, Coverage, Freshness, JobReference, LineageItem,
    VerificationCheck, VerificationResult, stable_fingerprint,
)
from .operational_monitoring import record_metric


JOB_SCHEMA_VERSION = "1"
WORKER_VERSION = "analytics-worker-v1"
DEFAULT_LEASE_SECONDS = 120


class JobCapacityError(RuntimeError):
    """One tenant has reached the bounded active heavy-job allowance."""


class HeavyAnalyticsDisabledError(RuntimeError):
    """Heavy analytics are disabled by the current rollout configuration."""


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class JobType(StrEnum):
    SIMULATION = "SIMULATION"
    OPTIMIZATION = "OPTIMIZATION"
    BACKTEST = "BACKTEST"
    COMPANY_RESEARCH_BUILD = "COMPANY_RESEARCH_BUILD"
    THESIS_MONITOR = "THESIS_MONITOR"


JOB_FLAGS = {
    JobType.SIMULATION: "SIMULATION_ENABLED",
    JobType.OPTIMIZATION: "OPTIMIZER_ENABLED",
    JobType.BACKTEST: "BACKTESTING_ENABLED",
    JobType.COMPANY_RESEARCH_BUILD: "DEEP_COMPANY_RESEARCH_ENABLED",
}


TERMINAL = {JobStatus.SUCCESS, JobStatus.PARTIAL, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}
CALCULATION_VERSIONS = {
    JobType.SIMULATION: "portfolio-simulation-job-v1",
    JobType.OPTIMIZATION: "portfolio-optimization-job-v1",
    JobType.BACKTEST: "portfolio-backtest-job-v1",
    JobType.COMPANY_RESEARCH_BUILD: "company-research-build-job-v1",
    JobType.THESIS_MONITOR: "thesis-monitor-job-v1",
}
INVALIDATION_DATASET = {
    JobType.SIMULATION: "scenario_model",
    JobType.OPTIMIZATION: "optimizer_config",
    JobType.COMPANY_RESEARCH_BUILD: "fundamentals",
    JobType.THESIS_MONITOR: "thesis_monitor",
}


class AnalyticsJob(BaseModel):
    job_id: str
    job_type: JobType
    request_id: str | None = None
    user_id: str
    portfolio_id: str | None = None
    input_fingerprint: str
    schema_version: str = JOB_SCHEMA_VERSION
    calculation_version: str
    worker_version: str = WORKER_VERSION
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress_stage: str = "queued"
    progress_percent: int | None = 0
    result_reference: str | None = None
    result: AnalysisResult | None = None
    error_class: str | None = None
    safe_error_summary: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    deduplication_key: str
    expires_at: datetime | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    next_attempt_at: datetime | None = None
    queue_wait_ms: float | None = None
    execution_ms: float | None = None
    dedupe_hit: bool = False
    compatible_result_reused: bool = False


class SimulationResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    input_fingerprint: str
    assumptions: list[Any] = Field(default_factory=list)
    path_count: int
    horizon_years: int
    median_outcome: float | None = None
    downside_percentiles: dict[str, float | None] = Field(default_factory=dict)
    probability_of_loss: float | None = None
    drawdown_statistics: dict[str, float | None] = Field(default_factory=dict)
    scenario_outputs: list[dict[str, Any]] = Field(default_factory=list)
    robust_weight_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class OptimizationResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    feasible: bool
    current_weights: dict[str, float] = Field(default_factory=dict)
    candidate_weights: list[dict[str, Any]] = Field(default_factory=list)
    turnover: float | None = None
    violated_constraints: list[str] = Field(default_factory=list)
    objective_value: float | None = None
    trading_cost_model: dict[str, Any] | None = None
    estimated_costs: float | None = None
    tax_aware: bool = False
    tax_lot_coverage: float = 0
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    period: dict[str, Any] | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    turnover: float | None = None
    attribution: dict[str, Any] | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QualitativeClassification(BaseModel):
    model_provider: str
    model_name: str
    prompt_version: str
    classification_version: str
    input_fingerprint: str
    item_id: str
    result: str
    confidence: str
    evidence_ids: list[str] = Field(default_factory=list)
    generated_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _db_value(value: Any) -> Any:
    if value is None:
        return None
    return value if database.DATABASE_URL else (value.isoformat() if isinstance(value, datetime) else value)


def _json(value: Any) -> Any:
    return database._jsonb(value) if database.DATABASE_URL else json.dumps(value, default=str, separators=(",", ":"))


def _loads(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _row_job(row: dict[str, Any]) -> AnalyticsJob:
    result = _loads(row.get("result_payload") or row.get("result_json"))
    return AnalyticsJob.model_validate({
        **row, "job_id": str(row.get("job_id") or row.get("id")),
        "user_id": str(row["user_id"]),
        "portfolio_id": str(row["portfolio_id"]) if row.get("portfolio_id") is not None else None,
        "request_id": str(row["request_id"]) if row.get("request_id") is not None else None,
        "input_payload": None, "result": result,
    })


def deduplication_key(job_type: JobType | str, input_fingerprint: str, calculation_version: str) -> str:
    return stable_fingerprint({"job_type": str(job_type), "input_fingerprint": input_fingerprint,
                               "calculation_version": calculation_version})


def disabled_reason(job_type: JobType) -> str | None:
    """Return the configured unavailability reason without touching the job store."""
    if os.getenv("HEAVY_ANALYTICS_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return (
            "This heavy calculation is intentionally disabled in owner self-test mode because "
            "no durable analytics worker is provisioned. Available deterministic evidence is still shown."
        )
    job_flag = JOB_FLAGS.get(job_type)
    if job_flag and os.getenv(job_flag, "1").strip().lower() in {"0", "false", "off", "no"}:
        label = job_type.value.replace("_", " ").title()
        return f"{label} is intentionally disabled by the current production capability configuration."
    return None


def submit_job(*, job_type: JobType, user_id: str, payload: dict[str, Any], portfolio_id: str | None = None,
               request_id: str | None = None, input_fingerprint: str | None = None,
               calculation_version: str | None = None, max_retries: int = 2,
               expires_at: datetime | None = None) -> AnalyticsJob:
    reason = disabled_reason(job_type)
    if reason:
        raise HeavyAnalyticsDisabledError(reason)
    calculation = calculation_version or CALCULATION_VERSIONS[job_type]
    fingerprint = input_fingerprint or stable_fingerprint(payload)
    key = deduplication_key(job_type, fingerprint, calculation)
    existing = find_by_deduplication(user_id, key)
    if existing and existing.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCESS, JobStatus.PARTIAL}:
        return existing.model_copy(update={"dedupe_hit": True, "compatible_result_reused": existing.status in {JobStatus.SUCCESS, JobStatus.PARTIAL}})
    if existing and existing.status == JobStatus.FAILED and existing.retry_count < existing.max_retries:
        requeue(existing.job_id)
        return get_job(user_id, existing.job_id).model_copy(update={"dedupe_hit": True})
    job_id, created = str(uuid.uuid4()), _now()
    values = (
        job_id, job_type.value, request_id, user_id, portfolio_id, fingerprint, JOB_SCHEMA_VERSION,
        calculation, WORKER_VERSION, JobStatus.QUEUED.value, _db_value(created), "queued", 0,
        _json(payload), max(0, min(max_retries, 10)), key, _db_value(expires_at), _db_value(created),
    )
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        if database.DATABASE_URL:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"analytical-jobs:{user_id}",))
        active_limit = max(1, min(20, int(os.getenv("MAX_ACTIVE_ANALYTICAL_JOBS_PER_USER", "4"))))
        active = conn.execute(
            f"SELECT count(*) AS count FROM {prefix}analytical_jobs WHERE user_id={p} AND status IN ('QUEUED','RUNNING')",
            (user_id,),
        ).fetchone()
        active_count = int(active["count"] if hasattr(active, "keys") else active[0])
        if active_count >= active_limit:
            raise JobCapacityError(f"Active analytical job limit reached ({active_limit})")
        try:
            conn.execute(
                f"""INSERT INTO {prefix}analytical_jobs
                (id,job_type,request_id,user_id,portfolio_id,input_fingerprint,schema_version,calculation_version,
                 worker_version,status,created_at,progress_stage,progress_percent,input_payload,max_retries,
                 deduplication_key,expires_at,next_attempt_at)
                VALUES ({','.join([p] * 18)})""", values,
            )
        except Exception:
            concurrent = find_by_deduplication(user_id, key)
            if concurrent:
                return concurrent.model_copy(update={"dedupe_hit": True})
            raise
    return get_job(user_id, job_id)


def _select_one(sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def get_job(user_id: str, job_id: str) -> AnalyticsJob:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    row = _select_one(f"SELECT *,result_payload{'' if database.DATABASE_URL else ' AS result_json'} FROM {prefix}analytical_jobs WHERE id={p} AND user_id={p}", (job_id, user_id))
    if not row:
        raise KeyError(job_id)
    return _row_job(row)


def find_by_deduplication(user_id: str, key: str) -> AnalyticsJob | None:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    row = _select_one(
        f"SELECT *,result_payload{'' if database.DATABASE_URL else ' AS result_json'} FROM {prefix}analytical_jobs "
        f"WHERE user_id={p} AND deduplication_key={p} ORDER BY created_at DESC LIMIT 1", (user_id, key),
    )
    return _row_job(row) if row else None


def compatible_completed(*, user_id: str, job_type: JobType, input_fingerprint: str,
                         calculation_version: str | None = None) -> AnalyticsJob | None:
    calculation = calculation_version or CALCULATION_VERSIONS[job_type]
    job = find_by_deduplication(user_id, deduplication_key(job_type, input_fingerprint, calculation))
    return job if job and job.status in {JobStatus.SUCCESS, JobStatus.PARTIAL} and job.result else None


def requeue(job_id: str) -> None:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    now = _db_value(_now())
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        conn.execute(f"UPDATE {prefix}analytical_jobs SET status='QUEUED',worker_id=NULL,lease_expires_at=NULL,heartbeat_at=NULL,next_attempt_at={p},progress_stage='queued',progress_percent=0 WHERE id={p}", (now, job_id))


def recover_expired_leases() -> int:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    now = _db_value(_now())
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        conn.execute(f"UPDATE {prefix}analytical_jobs SET status='EXPIRED',completed_at={p},progress_stage='expired',progress_percent=100 WHERE status='QUEUED' AND expires_at IS NOT NULL AND expires_at < {p}", (now, now))
        cursor = conn.execute(
            f"""UPDATE {prefix}analytical_jobs SET status=CASE WHEN retry_count < max_retries THEN 'QUEUED' ELSE 'FAILED' END,
            retry_count=retry_count+1, worker_id=NULL,lease_expires_at=NULL,heartbeat_at=NULL,next_attempt_at={p},
            progress_stage=CASE WHEN retry_count < max_retries THEN 'recovered' ELSE 'failed' END,
            error_class='WorkerLeaseExpired',safe_error_summary='The worker lease expired; the job was recovered safely.'
            WHERE status='RUNNING' AND lease_expires_at < {p}""", (now, now),
        )
        return cursor.rowcount


def claim_next(worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
               job_types: list[JobType] | None = None) -> AnalyticsJob | None:
    recover_expired_leases()
    now, lease = _now(), _now() + timedelta(seconds=max(10, lease_seconds))
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    type_values = [item.value for item in (job_types or list(JobType))]
    placeholders = ",".join([p] * len(type_values))
    if database.DATABASE_URL:
        with database.postgres_connection() as conn:
            row = conn.execute(
                f"""WITH candidate AS (SELECT id FROM public.analytical_jobs WHERE status='QUEUED'
                AND (next_attempt_at IS NULL OR next_attempt_at<=%s) AND (expires_at IS NULL OR expires_at>%s)
                AND job_type IN ({placeholders}) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
                UPDATE public.analytical_jobs j SET status='RUNNING',started_at=COALESCE(started_at,%s),worker_id=%s,
                lease_expires_at=%s,heartbeat_at=%s,progress_stage='claimed',progress_percent=1,
                queue_wait_ms=EXTRACT(EPOCH FROM (%s-created_at))*1000 FROM candidate WHERE j.id=candidate.id RETURNING j.*""",
                (_db_value(now), _db_value(now), *type_values, _db_value(now), worker_id, _db_value(lease), _db_value(now), _db_value(now)),
            ).fetchone()
            claimed = _row_job(dict(row)) if row else None
        if claimed:
            _start_attempt(claimed, worker_id)
        return claimed
    with database.sqlite_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"SELECT * FROM analytical_jobs WHERE status='QUEUED' AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
            f"AND (expires_at IS NULL OR expires_at>?) AND job_type IN ({placeholders}) ORDER BY created_at LIMIT 1",
            (_db_value(now), _db_value(now), *type_values),
        ).fetchone()
        if not row:
            return None
        queue_wait = max(0.0, (now - datetime.fromisoformat(row["created_at"])).total_seconds() * 1000)
        conn.execute("UPDATE analytical_jobs SET status='RUNNING',started_at=COALESCE(started_at,?),worker_id=?,lease_expires_at=?,heartbeat_at=?,progress_stage='claimed',progress_percent=1,queue_wait_ms=? WHERE id=? AND status='QUEUED'",
                     (_db_value(now), worker_id, _db_value(lease), _db_value(now), queue_wait, row["id"]))
        claimed = conn.execute("SELECT * FROM analytical_jobs WHERE id=?", (row["id"],)).fetchone()
        result = _row_job(dict(claimed))
    _start_attempt(result, worker_id)
    return result


def _start_attempt(job: AnalyticsJob, worker_id: str) -> None:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    attempt = job.retry_count + 1
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        conn.execute(f"""INSERT INTO {prefix}analytical_job_attempts
        (id,job_id,attempt_number,worker_id,started_at,status) VALUES ({','.join([p]*6)})
        ON CONFLICT (job_id,attempt_number) DO NOTHING""",
        (str(uuid.uuid4()), job.job_id, attempt, worker_id, _db_value(_now()), JobStatus.RUNNING.value))


def _finish_attempt(job: AnalyticsJob, status: JobStatus, *, error_class: str | None = None,
                    safe_error_summary: str | None = None) -> None:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    now = _now()
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        conn.execute(f"""UPDATE {prefix}analytical_job_attempts SET completed_at={p},status={p},error_class={p},
        safe_error_summary={p},execution_ms={p} WHERE job_id={p} AND attempt_number={p}""",
        (_db_value(now), status.value, error_class, safe_error_summary,
         max(0.0, (now-(job.started_at or now)).total_seconds()*1000), job.job_id, job.retry_count+1))


def heartbeat(job_id: str, worker_id: str, stage: str | None, percent: int | None = None,
              *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    now, lease = _now(), _now() + timedelta(seconds=lease_seconds)
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        cursor = conn.execute(f"UPDATE {prefix}analytical_jobs SET heartbeat_at={p},lease_expires_at={p},progress_stage=COALESCE({p},progress_stage),progress_percent=COALESCE({p},progress_percent) WHERE id={p} AND worker_id={p} AND status='RUNNING'",
                              (_db_value(now), _db_value(lease), stage[:80] if stage else None, percent, job_id, worker_id))
        return cursor.rowcount == 1


def _input_payload(job_id: str) -> dict[str, Any]:
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    row = _select_one(f"SELECT input_payload FROM {prefix}analytical_jobs WHERE id={p}", (job_id,))
    return _loads((row or {}).get("input_payload")) or {}


def _finish(job: AnalyticsJob, worker_id: str, result: AnalysisResult) -> None:
    terminal = JobStatus.PARTIAL if result.status == AnalysisStatus.PARTIAL else JobStatus.SUCCESS
    now = _now()
    started = job.started_at or now
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    payload = result.model_dump(mode="json")
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        conn.execute(f"""UPDATE {prefix}analytical_jobs SET status={p},completed_at={p},progress_stage='complete',progress_percent=100,
        result_reference={p},result_payload={p},execution_ms={p},lease_expires_at=NULL,heartbeat_at={p}
        WHERE id={p} AND worker_id={p} AND status='RUNNING'""",
        (terminal.value, _db_value(now), f"analytical_jobs:{job.job_id}", _json(payload),
         max(0.0, (now-started).total_seconds()*1000), _db_value(now), job.job_id, worker_id))
    _finish_attempt(job, terminal)
    _invalidate(job, result)


def _fail(job: AnalyticsJob, worker_id: str, exc: Exception) -> None:
    retryable = isinstance(exc, (TimeoutError, ConnectionError, database.psycopg.OperationalError))
    retry = job.retry_count < job.max_retries and retryable
    now = _now()
    status = JobStatus.QUEUED if retry else JobStatus.FAILED
    next_attempt = now + timedelta(seconds=min(60, 2 ** (job.retry_count + 1))) if retry else None
    prefix, p = ("public.", "%s") if database.DATABASE_URL else ("", "?")
    with (database.postgres_connection() if database.DATABASE_URL else database.sqlite_connection()) as conn:
        conn.execute(f"""UPDATE {prefix}analytical_jobs SET status={p},completed_at={p},retry_count=retry_count+1,
        error_class={p},safe_error_summary={p},next_attempt_at={p},worker_id=NULL,lease_expires_at=NULL,
        progress_stage={p},execution_ms={p} WHERE id={p} AND worker_id={p}""",
        (status.value, _db_value(None if retry else now), type(exc).__name__, "The analytical job could not complete safely.",
         _db_value(next_attempt), "retry_wait" if retry else "failed",
         max(0.0, (now-(job.started_at or now)).total_seconds()*1000), job.job_id, worker_id))
    _finish_attempt(job, status, error_class=type(exc).__name__,
                    safe_error_summary="The analytical job could not complete safely.")


def _canonical(capability: str, calculation_version: str, fingerprint: str, data: Any, *,
               status: AnalysisStatus = AnalysisStatus.SUCCESS, requested: list[str] | None = None,
               evaluated: list[str] | None = None, warnings: list[str] | None = None,
               limitations: list[str] | None = None, lineage: list[LineageItem] | None = None) -> AnalysisResult:
    now = _now()
    return AnalysisResult(
        capability=capability, calculation_version=calculation_version, input_fingerprint=fingerprint,
        status=status, data=data, coverage=Coverage(requested_entities=requested or [], evaluated_entities=evaluated or requested or []),
        freshness=Freshness(calculated_at=now, effective_through=now, stale=False,
                            methodology="Job inputs are versioned stored datasets; completion time is not provider refresh time."),
        lineage=lineage or [], limitations=limitations or [], warnings=warnings or [],
        verification=VerificationResult(passed=status not in {AnalysisStatus.FAILED, AnalysisStatus.UNAVAILABLE},
            answer_allowed=status not in {AnalysisStatus.FAILED}, recommendation_allowed=False,
            checks=[VerificationCheck(name="job_input_fingerprint", passed=True, message="The result carries the submitted job fingerprint.")]),
    )


def _simulation(job: AnalyticsJob, payload: dict[str, Any], progress: Callable[[str, int], None]) -> AnalysisResult:
    from .models import SimulationRunInput
    from .simulation_engine import run_simulation
    progress("loading_data", 10)
    request = SimulationRunInput.model_validate(payload)
    progress("running_paths", 35)
    result = run_simulation(request)
    # Persist the durable job fingerprint on the reusable simulation artifact,
    # not only on the wrapping analytical-job result.
    result["input_fingerprint"] = job.input_fingerprint
    result["portfolio_context_version"] = job.input_fingerprint
    progress("aggregating", 85)
    database.save_simulation_run(job.user_id, result)
    symbols = [row.ticker for row in request.holdings]
    current = next((row for row in result.get("outcomes") or [] if row.get("strategy_key") in {"current", "current_portfolio"}),
                   next(iter(result.get("outcomes") or []), {}))
    typed = SimulationResult.model_validate({**result, "input_fingerprint": job.input_fingerprint,
        "path_count": request.paths, "horizon_years": request.horizon_years or request.profile.horizon_years,
        "median_outcome": (current.get("wealth_percentiles") or {}).get("p50"),
        "downside_percentiles": current.get("wealth_percentiles") or {},
        "probability_of_loss": current.get("probability_of_loss"),
        "drawdown_statistics": current.get("drawdown_percentiles") or {},
        "scenario_outputs": result.get("outcomes") or [],
        "robust_weight_alternatives": [row for row in result.get("outcomes") or [] if row.get("strategy_key") not in {"current", "current_portfolio"}],
        "limitations": result.get("warnings") or []}).model_dump(mode="json")
    status = AnalysisStatus.PARTIAL if result.get("warnings") else AnalysisStatus.SUCCESS
    return _canonical("portfolio_simulation", job.calculation_version, job.input_fingerprint, typed, status=status,
                      requested=symbols, evaluated=symbols, warnings=result.get("warnings") or [],
                      limitations=result.get("assumptions") or [], lineage=[LineageItem(domain="market", dataset="stored_price_history", source_version=result.get("shared_path_fingerprint"))])


def _optimization(job: AnalyticsJob, payload: dict[str, Any], progress: Callable[[str, int], None]) -> AnalysisResult:
    from .allocation_builders import optimize_etfs, optimize_stocks
    from .analysis import run_analysis
    from .model_portfolios import compare
    from .models import (ETFAllocationRequest, InvestorProfile, ModelPortfolioCompareRequest,
                         StockBasketRequest)
    progress("loading_data", 10)
    operation = str(payload.get("operation") or "portfolio_analysis")
    if operation in {"etf_allocation", "stock_basket", "model_portfolio_compare"}:
        progress("optimizing", 35)
        if operation == "etf_allocation":
            result = optimize_etfs(ETFAllocationRequest.model_validate(payload["request"]))
        elif operation == "stock_basket":
            result = optimize_stocks(StockBasketRequest.model_validate(payload["request"]))
        else:
            result = compare(ModelPortfolioCompareRequest.model_validate(payload["request"]))
        diagnostics = json.dumps(result.get("warnings") or [], default=str).lower()
        infeasible = str(result.get("status") or "").lower() == "infeasible" or "infeasible" in diagnostics
        if infeasible:
            result["alternatives"] = {}
            result["attempted_weights_withheld"] = True
        typed = OptimizationResult.model_validate({**result, "feasible": not infeasible,
            "candidate_weights": [] if infeasible else list((result.get("alternatives") or {}).values()) if isinstance(result.get("alternatives"), dict) else result.get("allocations") or [],
            "alternatives": [] if infeasible else list((result.get("alternatives") or {}).values()) if isinstance(result.get("alternatives"), dict) else [],
            "diagnostics": {"operation": operation}}).model_dump(mode="json")
        return _canonical("portfolio_optimization", job.calculation_version, job.input_fingerprint, typed,
            status=AnalysisStatus.UNAVAILABLE if infeasible else AnalysisStatus.PARTIAL if result.get("warnings") else AnalysisStatus.SUCCESS,
            requested=list(payload.get("request", {}).get("candidate_tickers") or []), warnings=result.get("warnings") or [],
            limitations=["Tax-aware recommendations require lot-level coverage.", "Estimated costs require a supported trading-cost model."])
    holdings = payload.get("holdings") or []
    profile = InvestorProfile.model_validate(payload.get("profile") or {})
    progress("optimizing", 35)
    result = run_analysis(holdings, profile)
    diagnostics = json.dumps({"warnings": result.get("warnings"), "diagnostics": result.get("model_diagnostics")}, default=str).lower()
    infeasible = any(word in diagnostics for word in ("infeasible", "constraints incompatible", "constraint violation"))
    if infeasible:
        result["alternatives"] = []
        result["attempted_weights_withheld"] = True
    result["input_fingerprint"] = job.input_fingerprint
    result["portfolio_context_version"] = payload.get("portfolio_fingerprint")
    database.save_analysis(result["id"], {"portfolio_id": job.portfolio_id, "input_fingerprint": job.input_fingerprint,
                                          "portfolio_context_version": payload.get("portfolio_fingerprint")}, result, job.user_id)
    status = AnalysisStatus.UNAVAILABLE if infeasible else AnalysisStatus.PARTIAL if result.get("warnings") else AnalysisStatus.SUCCESS
    current_weights = {str(row.get("ticker")): float(row.get("weight") or 0) for row in holdings}
    typed = OptimizationResult.model_validate({**result, "feasible": not infeasible, "current_weights": current_weights,
        "candidate_weights": [] if infeasible else result.get("alternatives") or [],
        "violated_constraints": ["optimizer_constraints_incompatible"] if infeasible else [],
        "trading_cost_model": payload.get("trading_cost_model"), "tax_aware": False,
        "tax_lot_coverage": float((payload.get("tax_lot_state") or {}).get("coverage") or 0),
        "diagnostics": result.get("model_diagnostics") or {}}).model_dump(mode="json")
    return _canonical("portfolio_optimization", job.calculation_version, job.input_fingerprint, typed, status=status,
                      requested=[str(x.get("ticker")) for x in holdings], warnings=result.get("warnings") or [],
                      limitations=["Tax-aware recommendations require lot-level coverage.", "Estimated costs require a supported trading-cost model."])


def _backtest(job: AnalyticsJob, payload: dict[str, Any], progress: Callable[[str, int], None]) -> AnalysisResult:
    from .model_portfolios import backtest
    from .models import ModelPortfolioBacktestRequest
    request = ModelPortfolioBacktestRequest.model_validate(payload)
    requested = sorted({ticker.upper() for weights in request.alternatives.values() for ticker in weights} | {request.benchmark.upper()})
    progress("loading_history", 10)
    result = backtest(request)
    progress("calculating_returns", 65)
    coverage = result.get("coverage") or {}
    evaluated = coverage.get("symbols_with_sufficient_history") or requested
    status = AnalysisStatus.UNAVAILABLE if result.get("status") == "unavailable" else AnalysisStatus.PARTIAL if result.get("warnings") else AnalysisStatus.SUCCESS
    typed = BacktestResult.model_validate(result).model_dump(mode="json")
    return _canonical("portfolio_backtest", job.calculation_version, job.input_fingerprint, typed, status=status,
                      requested=requested, evaluated=evaluated, warnings=result.get("warnings") or [],
                      limitations=["Historical performance is hypothetical and does not predict future returns."],
                      lineage=[LineageItem(domain="market", dataset="stored_adjusted_prices", source_version=result.get("version"))])


def _company_research(job: AnalyticsJob, payload: dict[str, Any], progress: Callable[[str, int], None]) -> AnalysisResult:
    if payload.get("operation") == "portfolio_overview_rebuild":
        from .main import _calculate_portfolio_overview
        progress("fundamentals", 10)
        result = _calculate_portfolio_overview(job.user_id, job.portfolio_id or payload["portfolio_id"],
                                               str(payload.get("trigger") or "JOB"))
        progress("persisting", 90)
        tickers = [str(value).upper() for value in payload.get("tickers") or []]
        return _canonical("company_research_build", job.calculation_version, job.input_fingerprint,
                          {"portfolio_overview": result, "tickers": tickers}, requested=tickers,
                          evaluated=tickers, limitations=["Provider ingestion is separate from this stored-data analytical rebuild."])
    from .analysis import security_research
    tickers = list(dict.fromkeys(str(x).upper() for x in payload.get("tickers") or []))[:50]
    progress("fundamentals", 15)
    stored = database.security_data(tickers, price_limit=int(payload.get("price_limit") or 756)) if database.DATABASE_URL else None
    progress("factors", 55)
    rows = security_research(tickers, price_limit=int(payload.get("price_limit") or 756), stored=stored)
    # Deep research and the fast interactive projection remain separate
    # artifacts. The worker advances only the requested ticker projections;
    # Ask never reruns this builder.
    from . import phase6_domains
    for row in rows:
        phase6_domains.materialize_company(job.user_id, str(row["ticker"]), stored=stored, research_row=row)
    evaluated = [row["ticker"] for row in rows if row.get("price") is not None or row.get("fundamentals_as_of")]
    missing = sorted(set(tickers)-set(evaluated))
    status = AnalysisStatus.PARTIAL if missing else AnalysisStatus.SUCCESS
    data = {"tickers": tickers, "research": rows, "materialized_at": _now().isoformat(), "missing_tickers": missing}
    return _canonical("company_research_build", job.calculation_version, job.input_fingerprint, data, status=status,
                      requested=tickers, evaluated=evaluated, warnings=[f"Missing analytical coverage: {', '.join(missing)}"] if missing else [])


def _thesis(job: AnalyticsJob, payload: dict[str, Any], progress: Callable[[str, int], None]) -> AnalysisResult:
    from .chat import classify_thesis_evidence
    from .thesis_monitor import evaluate_thesis
    thesis_ids = [str(x) for x in payload.get("thesis_ids") or []]
    qualitative = bool(payload.get("include_qualitative", True))
    progress("deterministic_checks", 15)
    results, unavailable = [], []
    classifier = classify_thesis_evidence if qualitative else None
    for index, thesis_id in enumerate(thesis_ids):
        try:
            results.append(evaluate_thesis(job.user_id, thesis_id, classifier=classifier, use_cache=False).model_dump(mode="json"))
        except Exception as exc:
            if classifier is None:
                raise
            unavailable.append({"thesis_id": thesis_id, "status": "UNAVAILABLE", "error_class": type(exc).__name__,
                                "safe_error_summary": "Qualitative classification is unavailable; deterministic monitoring remains usable."})
            results.append(evaluate_thesis(job.user_id, thesis_id, classifier=None, use_cache=False).model_dump(mode="json"))
        progress("qualitative_classification", 25 + int(60*(index+1)/max(1, len(thesis_ids))))
    status = AnalysisStatus.PARTIAL if unavailable else AnalysisStatus.SUCCESS
    classifications: list[dict[str, Any]] = []
    if qualitative:
        for monitored in results:
            items = [*(monitored.get("assumption_results") or []), *(monitored.get("risk_results") or []),
                     *(monitored.get("catalyst_results") or []), *(monitored.get("thesis_breaker_results") or [])]
            for item in items:
                if item.get("deterministic") is True:
                    continue
                evidence_ids = [stable_fingerprint({"reference": trace.get("source_references"), "metric": trace.get("metric")})[:20]
                                for trace in item.get("evidence") or []]
                classifications.append(QualitativeClassification(
                    model_provider="gemini", model_name=os.getenv("GEMINI_MODEL", "configured-gemini-model"),
                    prompt_version="thesis-evidence-v1", classification_version="qualitative-thesis-v1",
                    input_fingerprint=job.input_fingerprint,
                    item_id=str(item.get("assumption_id") or item.get("factor_id") or "unknown"),
                    result=str(item.get("state") or "UNAVAILABLE"),
                    confidence=str(item.get("relevance_confidence") or item.get("evidence_quality") or "UNAVAILABLE"),
                    evidence_ids=evidence_ids, generated_at=_now(),
                ).model_dump(mode="json"))
    data = {"results": results, "qualitative_items": unavailable, "qualitative_classifications": classifications}
    return _canonical("thesis_monitor", job.calculation_version, job.input_fingerprint, data, status=status,
                      requested=thesis_ids, evaluated=thesis_ids, warnings=["One or more qualitative items were unavailable; deterministic checks completed."] if unavailable else [])


HANDLERS: dict[JobType, Callable[[AnalyticsJob, dict[str, Any], Callable[[str, int], None]], AnalysisResult]] = {
    JobType.SIMULATION: _simulation, JobType.OPTIMIZATION: _optimization, JobType.BACKTEST: _backtest,
    JobType.COMPANY_RESEARCH_BUILD: _company_research, JobType.THESIS_MONITOR: _thesis,
}


def _invalidate(job: AnalyticsJob, result: AnalysisResult) -> None:
    if job.job_type not in INVALIDATION_DATASET:
        return
    if job.job_type == JobType.COMPANY_RESEARCH_BUILD and isinstance(result.data, dict) and result.data.get("portfolio_overview"):
        # The portfolio rebuild handler already materialized the dependent
        # capability models from the same stored input snapshot.
        return
    from . import read_models
    dataset = INVALIDATION_DATASET[job.job_type]
    portfolio_ids: list[str] = [job.portfolio_id] if job.portfolio_id else []
    if not portfolio_ids and job.job_type in {JobType.COMPANY_RESEARCH_BUILD, JobType.THESIS_MONITOR}:
        result_tickers = {str(row.get("ticker") or "").upper() for row in (
            (result.data or {}).get("research") or (result.data or {}).get("results") or []) if isinstance(row, dict)}
        profile = database.load_profile(job.user_id) or {}
        watchlist = {str(value).upper() for value in profile.get("watchlist") or []}
        for portfolio in database.list_portfolios(job.user_id):
            holdings = {str(row.get("ticker") or "").upper() for row in portfolio.get("holdings") or []}
            if not result_tickers or result_tickers & (holdings | watchlist):
                portfolio_ids.append(str(portfolio["id"]))
    for portfolio_id in portfolio_ids:
        read_models.invalidate_for_upstream_change(job.user_id, portfolio_id, dataset,
                                                   stable_fingerprint(result.data), result.freshness.effective_through.isoformat() if result.freshness.effective_through else None)
        if job.job_type in {JobType.SIMULATION, JobType.OPTIMIZATION}:
            # Completion advances a versioned dependency. Queue the existing
            # portfolio projection builder so Ask can read the completed result
            # without calculating it synchronously on the next question.
            try:
                from .main import _queue_portfolio_overview_rebuild
                _queue_portfolio_overview_rebuild(job.user_id, portfolio_id, f"{job.job_type.value}_COMPLETED")
            except Exception as exc:
                record_metric("analytics.job.read_model_rebuild.failure",
                              tags={"job_type": job.job_type.value, "error_class": type(exc).__name__})


def run_one(*, worker_id: str | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS,
            job_types: list[JobType] | None = None) -> AnalyticsJob | None:
    worker = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    job = claim_next(worker, lease_seconds=lease_seconds, job_types=job_types)
    if not job:
        return None
    def progress(stage: str, percent: int) -> None:
        if not heartbeat(job.job_id, worker, stage, percent, lease_seconds=lease_seconds):
            raise RuntimeError("Job lease was lost")
    stop_heartbeat = threading.Event()
    def maintain_lease() -> None:
        interval = max(3.0, lease_seconds / 3)
        while not stop_heartbeat.wait(interval):
            if not heartbeat(job.job_id, worker, None, None, lease_seconds=lease_seconds):
                return
    heartbeat_thread = threading.Thread(target=maintain_lease, name=f"analytics-heartbeat-{job.job_id[:8]}", daemon=True)
    heartbeat_thread.start()
    try:
        result = HANDLERS[job.job_type](job, _input_payload(job.job_id), progress)
        _finish(job, worker, result)
    except Exception as exc:
        _fail(job, worker, exc)
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)
    return get_job(job.user_id, job.job_id)


def run_worker(*, poll_seconds: float = 1.0, once: bool = False, concurrency: int = 1) -> int:
    # One process may host a small bounded worker pool; each claim remains database-authoritative.
    completed, last_heartbeat = 0, 0.0
    while True:
        if time.monotonic() - last_heartbeat >= 60 or last_heartbeat == 0:
            record_metric("analytics.worker.heartbeat", tags={"worker_version": WORKER_VERSION}, persist=bool(database.DATABASE_URL))
            last_heartbeat = time.monotonic()
        limit = max(1, min(concurrency, 4))
        if limit == 1:
            jobs = [run_one(worker_id=f"{socket.gethostname()}:{os.getpid()}:0")]
        else:
            with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="analytics-worker") as pool:
                jobs = list(pool.map(lambda slot: run_one(worker_id=f"{socket.gethostname()}:{os.getpid()}:{slot}"), range(limit)))
        claimed = sum(job is not None for job in jobs)
        completed += claimed
        if once or claimed == 0:
            if once:
                return completed
            time.sleep(max(.1, poll_seconds))


def pending_analysis(job: AnalyticsJob, capability: str, *, data: Any = None,
                     limitations: list[str] | None = None) -> AnalysisResult:
    now = _now()
    return AnalysisResult(
        capability=capability, calculation_version=job.calculation_version,
        input_fingerprint=job.input_fingerprint, status=AnalysisStatus.PENDING, data=data or {},
        coverage=Coverage.not_tracked(), freshness=Freshness(calculated_at=now, stale=None),
        limitations=limitations or ["The heavy calculation is running in the durable analytics worker."],
        verification=VerificationResult(passed=True, answer_allowed=True, recommendation_allowed=False),
        job=JobReference(id=job.job_id, kind=job.job_type.value, status=AnalysisStatus.PENDING,
                         status_url=f"/api/analytics/jobs/{job.job_id}"),
    )


def operational_health() -> dict[str, Any]:
    """Return queue/lease health without exposing job payloads or tenant data."""
    prefix = "public." if database.DATABASE_URL else ""
    connection = database.postgres_connection if database.DATABASE_URL else database.sqlite_connection
    with connection() as conn:
        rows = conn.execute(
            f"SELECT status,count(*) AS count FROM {prefix}analytical_jobs GROUP BY status"
        ).fetchall()
        oldest = conn.execute(
            f"SELECT min(created_at) AS oldest FROM {prefix}analytical_jobs WHERE status='QUEUED'"
        ).fetchone()
        running = conn.execute(
            f"SELECT max(heartbeat_at) AS heartbeat FROM {prefix}analytical_jobs WHERE status='RUNNING'"
        ).fetchone()
        worker = None
        if database.DATABASE_URL:
            worker = conn.execute(
                "SELECT observed_at FROM public.operational_events WHERE metric_name='analytics.worker.heartbeat' ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    now = _now()
    oldest_at = _parse(oldest["oldest"]) if oldest and oldest["oldest"] else None
    worker_at = _parse(worker["observed_at"]) if worker and worker["observed_at"] else None
    queue_age = (now - oldest_at).total_seconds() if oldest_at else 0.0
    worker_age = (now - worker_at).total_seconds() if worker_at else None
    healthy = not counts.get("QUEUED") or (worker_age is not None and worker_age <= 180)
    return {
        "version": "analytics-job-health-v1", "status": "healthy" if healthy else "degraded",
        "counts": counts, "oldest_queue_age_seconds": round(max(0.0, queue_age), 1),
        "latest_running_heartbeat": _db_value(running["heartbeat"]) if running and running["heartbeat"] else None,
        "worker_heartbeat_age_seconds": round(worker_age, 1) if worker_age is not None else None,
    }
