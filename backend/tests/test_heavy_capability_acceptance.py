from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import analytics_jobs, database, main
from backend.analytical_contract import AnalysisStatus


@pytest.fixture(autouse=True)
def durable_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", None)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "acceptance.db")
    database.initialize()


def canned(status=AnalysisStatus.SUCCESS, data=None):
    def handler(job, _payload, progress):
        progress("calculating", 50)
        return analytics_jobs._canonical(job.job_type.value.lower(), job.calculation_version,
                                         job.input_fingerprint, data or {"completed": True}, status=status)
    return handler


def run(job_type, monkeypatch, *, payload=None, status=AnalysisStatus.SUCCESS, data=None):
    monkeypatch.setitem(analytics_jobs.HANDLERS, job_type, canned(status, data))
    job = analytics_jobs.submit_job(job_type=job_type, user_id="acceptance-user", payload=payload or {"input": 1})
    return job, analytics_jobs.run_one(worker_id="acceptance-worker")


def test_01_run_portfolio_simulation(monkeypatch):
    job, done = run(analytics_jobs.JobType.SIMULATION, monkeypatch, data={"path_count": 500, "outcomes": []})
    assert done.job_id == job.job_id and done.status == analytics_jobs.JobStatus.SUCCESS


def test_02_reuse_completed_compatible_simulation(monkeypatch):
    job, _ = run(analytics_jobs.JobType.SIMULATION, monkeypatch)
    reused = analytics_jobs.submit_job(job_type=analytics_jobs.JobType.SIMULATION,
                                        user_id="acceptance-user", payload={"input": 1})
    assert reused.job_id == job.job_id and reused.compatible_result_reused


def test_03_run_feasible_optimizer(monkeypatch):
    _, done = run(analytics_jobs.JobType.OPTIMIZATION, monkeypatch,
                  data={"feasible": True, "candidate_weights": [{"SPY": 1.0}]})
    assert done.status == analytics_jobs.JobStatus.SUCCESS
    assert done.result.data["feasible"] is True


def test_04_handle_infeasible_optimizer_without_weights(monkeypatch):
    _, done = run(analytics_jobs.JobType.OPTIMIZATION, monkeypatch, status=AnalysisStatus.UNAVAILABLE,
                  data={"feasible": False, "candidate_weights": [], "attempted_weights_withheld": True})
    assert done.status == analytics_jobs.JobStatus.SUCCESS
    assert done.result.status == AnalysisStatus.UNAVAILABLE and not done.result.data["candidate_weights"]


def test_05_run_portfolio_backtest_vs_spy(monkeypatch):
    _, done = run(analytics_jobs.JobType.BACKTEST, monkeypatch,
                  payload={"alternatives": {"current": {"AAPL": 1}}, "benchmark": "SPY"},
                  data={"period": {"start": "2020-01-01", "end": "2026-01-01"}, "benchmark": "SPY"})
    assert done.result.data["benchmark"] == "SPY"


def test_06_handle_missing_historical_data(monkeypatch):
    _, done = run(analytics_jobs.JobType.BACKTEST, monkeypatch, status=AnalysisStatus.UNAVAILABLE,
                  data={"coverage": {"requested_symbols": ["OLD", "SPY"], "missing_symbols": ["OLD"]}})
    assert done.status == analytics_jobs.JobStatus.SUCCESS
    assert done.result.data["coverage"]["missing_symbols"] == ["OLD"]


def test_07_build_deep_company_research(monkeypatch):
    _, done = run(analytics_jobs.JobType.COMPANY_RESEARCH_BUILD, monkeypatch,
                  payload={"tickers": ["AAPL"]}, data={"research": [{"ticker": "AAPL"}]})
    assert done.result.data["research"][0]["ticker"] == "AAPL"


def test_08_thesis_monitor_classifier_unavailable_is_partial(monkeypatch):
    _, done = run(analytics_jobs.JobType.THESIS_MONITOR, monkeypatch, status=AnalysisStatus.PARTIAL,
                  data={"deterministic": {"breaker": "NOT_TRIGGERED"},
                        "qualitative_items": [{"status": "UNAVAILABLE"}]})
    assert done.status == analytics_jobs.JobStatus.PARTIAL
    assert done.result.data["deterministic"]["breaker"] == "NOT_TRIGGERED"


def test_09_restart_worker_during_job(monkeypatch):
    job = analytics_jobs.submit_job(job_type=analytics_jobs.JobType.SIMULATION,
                                    user_id="acceptance-user", payload={"input": 1})
    analytics_jobs.claim_next("worker-that-died")
    with database.sqlite_connection() as conn:
        conn.execute("UPDATE analytical_jobs SET lease_expires_at=? WHERE id=?",
                     ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), job.job_id))
    analytics_jobs.recover_expired_leases()
    assert analytics_jobs.claim_next("replacement-worker").job_id == job.job_id


def test_10_normal_ask_evidence_while_heavy_job_running(monkeypatch):
    analytics_jobs.submit_job(job_type=analytics_jobs.JobType.BACKTEST,
                              user_id="acceptance-user", payload={"input": 1})
    analytics_jobs.claim_next("heavy-worker")
    started = datetime.now(timezone.utc)
    monkeypatch.setattr(main.ask_portfolio, "run", lambda *_args, **_kwargs: (
        [{"tool_name": "portfolio_intelligence", "status": "complete", "summary": {"risk": "available"}}],
        [{"label": "current portfolio risk"}],
    ))
    tools, evidence = main._execute_ask_tool("portfolio_intelligence", "acceptance-user", "show current risk")
    assert tools[0]["summary"]["risk"] == "available"
    assert evidence[0]["label"] == "current portfolio risk"
    assert (datetime.now(timezone.utc)-started).total_seconds() < .1
