from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend import analytics_jobs, database
from backend.analytical_contract import AnalysisStatus
from backend.main import _analytics_job_chat_status


@pytest.fixture()
def job_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", None)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "jobs.db")
    database.initialize()
    return tmp_path / "jobs.db"


def submit(payload=None, **kwargs):
    return analytics_jobs.submit_job(
        job_type=kwargs.pop("job_type", analytics_jobs.JobType.SIMULATION),
        user_id=kwargs.pop("user_id", "user-1"), payload=payload or {"portfolio": "A"}, **kwargs,
    )


def test_job_is_persisted_queued_before_work(job_db):
    job = submit()
    assert job.status == analytics_jobs.JobStatus.QUEUED
    assert job.created_at and job.started_at is None and job.result_reference is None


def test_duplicate_running_or_success_job_is_reused(job_db):
    first = submit()
    second = submit()
    assert second.job_id == first.job_id
    assert second.dedupe_hit is True
    claimed = analytics_jobs.claim_next("worker-1")
    assert claimed and claimed.job_id == first.job_id
    third = submit()
    assert third.job_id == first.job_id


def test_input_fingerprint_change_creates_new_job(job_db):
    first = submit({"portfolio_fingerprint": "A"})
    second = submit({"portfolio_fingerprint": "B"})
    assert second.job_id != first.job_id


def test_per_user_active_job_limit_prevents_queue_saturation(job_db, monkeypatch):
    monkeypatch.setenv("MAX_ACTIVE_ANALYTICAL_JOBS_PER_USER", "2")
    submit({"portfolio_fingerprint": "A"})
    submit({"portfolio_fingerprint": "B"})
    with pytest.raises(analytics_jobs.JobCapacityError):
        submit({"portfolio_fingerprint": "C"})
    assert submit({"portfolio_fingerprint": "C"}, user_id="user-2").status == analytics_jobs.JobStatus.QUEUED


def test_heavy_analytics_feature_flag_fails_closed(job_db, monkeypatch):
    monkeypatch.setenv("HEAVY_ANALYTICS_ENABLED", "0")
    for job_type in analytics_jobs.JobType:
        with pytest.raises(analytics_jobs.HeavyAnalyticsDisabledError):
            submit({"unique": job_type.value}, job_type=job_type)
    with database.sqlite_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM analytical_jobs").fetchone()[0] == 0


def test_owner_mode_reports_intentional_unavailability(monkeypatch):
    monkeypatch.setenv("HEAVY_ANALYTICS_ENABLED", "0")
    reason = analytics_jobs.disabled_reason(analytics_jobs.JobType.BACKTEST)
    assert reason is not None
    assert "intentionally disabled in owner self-test mode" in reason
    assert "deterministic evidence is still shown" in reason


def test_enabled_job_has_no_disabled_reason(monkeypatch):
    monkeypatch.setenv("HEAVY_ANALYTICS_ENABLED", "1")
    monkeypatch.setenv("BACKTESTING_ENABLED", "1")
    assert analytics_jobs.disabled_reason(analytics_jobs.JobType.BACKTEST) is None


@pytest.mark.parametrize(
    "job_type,flag",
    [
        (analytics_jobs.JobType.SIMULATION, "SIMULATION_ENABLED"),
        (analytics_jobs.JobType.OPTIMIZATION, "OPTIMIZER_ENABLED"),
        (analytics_jobs.JobType.BACKTEST, "BACKTESTING_ENABLED"),
        (analytics_jobs.JobType.COMPANY_RESEARCH_BUILD, "DEEP_COMPANY_RESEARCH_ENABLED"),
    ],
)
def test_heavy_capabilities_have_independent_kill_switches(job_db, monkeypatch, job_type, flag):
    monkeypatch.setenv(flag, "0")
    with pytest.raises(analytics_jobs.HeavyAnalyticsDisabledError):
        submit(job_type=job_type)


def test_calculation_version_change_creates_new_job(job_db):
    first = submit(calculation_version="simulation-v1")
    second = submit(calculation_version="simulation-v2")
    assert second.job_id != first.job_id


def test_two_workers_cannot_claim_same_job(job_db):
    expected = submit()
    first = analytics_jobs.claim_next("worker-1")
    second = analytics_jobs.claim_next("worker-2")
    assert first and first.job_id == expected.job_id
    assert second is None


def test_restart_recovery_reclaims_expired_running_job(job_db):
    job = submit(max_retries=2)
    analytics_jobs.claim_next("dead-worker")
    with database.sqlite_connection() as conn:
        conn.execute("UPDATE analytical_jobs SET lease_expires_at=? WHERE id=?",
                     ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), job.job_id))
    assert analytics_jobs.recover_expired_leases() == 1
    reclaimed = analytics_jobs.claim_next("new-worker")
    assert reclaimed and reclaimed.job_id == job.job_id
    assert reclaimed.retry_count == 1


def test_exhausted_expired_lease_becomes_failed(job_db):
    job = submit(max_retries=0)
    analytics_jobs.claim_next("dead-worker")
    with database.sqlite_connection() as conn:
        conn.execute("UPDATE analytical_jobs SET lease_expires_at=? WHERE id=?",
                     ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), job.job_id))
    analytics_jobs.recover_expired_leases()
    assert analytics_jobs.get_job("user-1", job.job_id).status == analytics_jobs.JobStatus.FAILED


def test_expired_queued_job_reaches_terminal_state(job_db):
    job = submit(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    analytics_jobs.recover_expired_leases()
    assert analytics_jobs.get_job("user-1", job.job_id).status == analytics_jobs.JobStatus.EXPIRED


def test_worker_persists_canonical_analysis_result(job_db, monkeypatch):
    job = submit(job_type=analytics_jobs.JobType.COMPANY_RESEARCH_BUILD)
    monkeypatch.setitem(analytics_jobs.HANDLERS, analytics_jobs.JobType.COMPANY_RESEARCH_BUILD,
        lambda claimed, payload, progress: analytics_jobs._canonical(
            "company_research_build", claimed.calculation_version, claimed.input_fingerprint,
            {"research": [{"ticker": "AAPL"}]}, requested=["AAPL"]))
    finished = analytics_jobs.run_one(worker_id="worker")
    assert finished and finished.job_id == job.job_id
    assert finished.status == analytics_jobs.JobStatus.SUCCESS
    assert finished.result and finished.result.status == AnalysisStatus.SUCCESS
    assert finished.result.input_fingerprint == job.input_fingerprint
    assert finished.result_reference == f"analytical_jobs:{job.job_id}"


def test_analytical_infeasibility_is_successful_execution(job_db, monkeypatch):
    job = submit(job_type=analytics_jobs.JobType.OPTIMIZATION)
    monkeypatch.setitem(analytics_jobs.HANDLERS, analytics_jobs.JobType.OPTIMIZATION,
        lambda claimed, payload, progress: analytics_jobs._canonical(
            "portfolio_optimization", claimed.calculation_version, claimed.input_fingerprint,
            {"feasible": False, "candidate_weights": [], "attempted_weights_withheld": True},
            status=AnalysisStatus.UNAVAILABLE))
    finished = analytics_jobs.run_one(worker_id="optimizer-worker")
    assert finished.status == analytics_jobs.JobStatus.SUCCESS
    assert finished.result.status == AnalysisStatus.UNAVAILABLE
    assert finished.result.data["candidate_weights"] == []


def test_optimizer_crash_is_durable_failed_job(job_db, monkeypatch):
    job = submit(job_type=analytics_jobs.JobType.OPTIMIZATION, max_retries=0)
    def crash(*_args):
        raise ValueError("secret solver details")
    monkeypatch.setitem(analytics_jobs.HANDLERS, analytics_jobs.JobType.OPTIMIZATION, crash)
    finished = analytics_jobs.run_one(worker_id="optimizer-worker")
    assert finished.status == analytics_jobs.JobStatus.FAILED
    assert finished.error_class == "ValueError"
    assert "secret" not in (finished.safe_error_summary or "")


def test_transient_failure_is_bounded_and_requeued(job_db, monkeypatch):
    job = submit(max_retries=1)
    monkeypatch.setitem(analytics_jobs.HANDLERS, analytics_jobs.JobType.SIMULATION,
                        lambda *_args: (_ for _ in ()).throw(TimeoutError("temporary")))
    finished = analytics_jobs.run_one(worker_id="worker")
    assert finished.status == analytics_jobs.JobStatus.QUEUED
    assert finished.retry_count == 1
    assert finished.next_attempt_at is not None


def test_compatible_completed_requires_exact_fingerprint(job_db, monkeypatch):
    job = submit(input_fingerprint="fingerprint-A")
    monkeypatch.setitem(analytics_jobs.HANDLERS, analytics_jobs.JobType.SIMULATION,
        lambda claimed, payload, progress: analytics_jobs._canonical(
            "portfolio_simulation", claimed.calculation_version, claimed.input_fingerprint, {"ok": True}))
    analytics_jobs.run_one(worker_id="worker")
    assert analytics_jobs.compatible_completed(user_id="user-1", job_type=analytics_jobs.JobType.SIMULATION,
                                               input_fingerprint="fingerprint-A")
    assert analytics_jobs.compatible_completed(user_id="user-1", job_type=analytics_jobs.JobType.SIMULATION,
                                               input_fingerprint="fingerprint-B") is None


def test_pending_analysis_includes_job_reference(job_db):
    job = submit()
    result = analytics_jobs.pending_analysis(job, "portfolio_simulation", data={"current_risk": "available"})
    assert result.status == AnalysisStatus.PENDING
    assert result.job and result.job.id == job.job_id
    assert result.data["current_risk"] == "available"


@pytest.mark.parametrize("job_type", list(analytics_jobs.JobType))
def test_all_five_heavy_job_types_share_contract(job_db, job_type):
    job = submit(job_type=job_type, payload={"type": job_type.value})
    assert job.job_type == job_type
    assert job.schema_version == analytics_jobs.JOB_SCHEMA_VERSION
    assert job.calculation_version == analytics_jobs.CALCULATION_VERSIONS[job_type]


def test_progress_and_attempt_observability_are_durable(job_db, monkeypatch):
    job = submit(job_type=analytics_jobs.JobType.BACKTEST)
    def handler(claimed, payload, progress):
        progress("aligning_series", 45)
        return analytics_jobs._canonical("portfolio_backtest", claimed.calculation_version,
                                         claimed.input_fingerprint, {"period": {}})
    monkeypatch.setitem(analytics_jobs.HANDLERS, analytics_jobs.JobType.BACKTEST, handler)
    finished = analytics_jobs.run_one(worker_id="worker-observed")
    assert finished.progress_stage == "complete" and finished.progress_percent == 100
    assert finished.queue_wait_ms is not None and finished.execution_ms is not None
    with database.sqlite_connection() as conn:
        attempt = conn.execute("SELECT * FROM analytical_job_attempts WHERE job_id=?", (job.job_id,)).fetchone()
    assert attempt["status"] == "SUCCESS" and attempt["worker_id"] == "worker-observed"


def test_normal_read_is_not_blocked_by_running_job(job_db):
    submit()
    analytics_jobs.claim_next("slow-worker", lease_seconds=300)
    started = datetime.now(timezone.utc)
    with database.sqlite_connection() as conn:
        conn.execute("SELECT 1").fetchone()
    elapsed_ms = (datetime.now(timezone.utc)-started).total_seconds()*1000
    assert elapsed_ms < 100


def test_migration_has_leases_dedupe_and_rls():
    path = database.APP_DIR / "supabase" / "migrations" / "202608220003_durable_analytical_jobs.sql"
    sql = path.read_text()
    for token in ("analytical_jobs", "deduplication_key", "lease_expires_at", "retry_count", "ENABLE ROW LEVEL SECURITY"):
        assert token in sql


def test_ask_job_failure_and_worker_unavailable_messages_are_specific(monkeypatch):
    simulation = analytics_jobs.AnalyticsJob.model_construct(
        job_type=analytics_jobs.JobType.SIMULATION, status=analytics_jobs.JobStatus.FAILED,
    )
    optimizer = analytics_jobs.AnalyticsJob.model_construct(
        job_type=analytics_jobs.JobType.OPTIMIZATION, status=analytics_jobs.JobStatus.FAILED,
    )
    assert _analytics_job_chat_status(simulation) == (
        "failed", "The simulation failed safely; the immediate deterministic evidence remains available.",
    )
    assert _analytics_job_chat_status(optimizer) == (
        "failed", "The optimizer failed safely; the immediate deterministic evidence remains available.",
    )
    monkeypatch.setattr(analytics_jobs, "operational_health", lambda: {"status": "degraded"})
    queued = analytics_jobs.AnalyticsJob.model_construct(
        job_type=analytics_jobs.JobType.SIMULATION, status=analytics_jobs.JobStatus.QUEUED,
    )
    status, message = _analytics_job_chat_status(queued)
    assert status == "partial" and "worker is temporarily unavailable" in message
