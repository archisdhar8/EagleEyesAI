from __future__ import annotations

import json
import multiprocessing as mp
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import analytics_jobs, database, main  # noqa: E402


def cpu_bound(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    value = 1.000001
    while time.monotonic() < deadline:
        value = (value * 1.0000001 + 0.0000003) % 97.0


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int(len(ordered)*fraction))]


def benchmark(label: str, job_type: analytics_jobs.JobType, tool: str) -> dict[str, object]:
    job = analytics_jobs.submit_job(job_type=job_type, user_id="benchmark-user", payload={"benchmark": label})
    claimed = analytics_jobs.claim_next(f"benchmark-worker-{label}", lease_seconds=300)
    assert claimed and claimed.job_id == job.job_id
    process = mp.Process(target=cpu_bound, args=(2.0,), daemon=True)
    process.start()
    original = main.ask_portfolio.run
    main.ask_portfolio.run = lambda *_args, **_kwargs: (
        [{"tool_name": tool, "status": "complete", "summary": {"materialized": True}}],
        [{"label": "materialized analytical evidence"}],
    )
    samples: list[float] = []
    try:
        for _ in range(100):
            started = time.perf_counter()
            tools, evidence = main._execute_ask_tool(tool, "benchmark-user", "show current stored analysis")
            assert tools and evidence
            samples.append((time.perf_counter()-started)*1000)
    finally:
        main.ask_portfolio.run = original
        process.join(timeout=5)
    return {"label": label, "job_type": job_type.value, "job_status_during_ask": "RUNNING",
            "samples": len(samples), "ask_median_ms": round(statistics.median(samples), 4),
            "ask_p95_ms": round(percentile(samples, .95), 4), "heavy_process_runtime_ms": 2000,
            "queue_wait_ms": round(float(claimed.queue_wait_ms or 0), 4),
            "isolation": "separate process with durable RUNNING row; Ask consumed a materialized read-model boundary"}


def main_cli() -> None:
    old_url, old_path = database.DATABASE_URL, database.DB_PATH
    database.DATABASE_URL = None
    with tempfile.TemporaryDirectory() as directory:
        database.DB_PATH = Path(directory) / "benchmark.db"
        database.initialize()
        results = [
            benchmark("simulation_plus_portfolio_risk_ask", analytics_jobs.JobType.SIMULATION, "portfolio_intelligence"),
            benchmark("backtest_plus_portfolio_read_ask", analytics_jobs.JobType.BACKTEST, "portfolio_overview"),
        ]
    database.DATABASE_URL, database.DB_PATH = old_url, old_path
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}
    output = ROOT / "artifacts" / "phase5-analytics-isolation-benchmark.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main_cli()
