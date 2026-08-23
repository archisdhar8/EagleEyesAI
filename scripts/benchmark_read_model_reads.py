from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import database, read_models
from backend.ask_runtime import build_portfolio_context


SAMPLES = 200
TARGETS = (
    "portfolio_opportunity", "portfolio_risk", "portfolio_factor_state", "portfolio_change",
    "portfolio_events", "portfolio_scenario", "watchlist_comparison",
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction) - 1))]


def main() -> None:
    database.DATABASE_URL = None
    with tempfile.TemporaryDirectory(prefix="eagleeyes-read-model-benchmark-") as directory:
        database.DB_PATH = Path(directory) / "benchmark.db"
        database.initialize()
        now = datetime.now(timezone.utc).isoformat()
        holdings = [{"ticker": f"T{index:02d}", "weight": 1 / 50} for index in range(50)]
        portfolio = database.save_portfolio("Benchmark", holdings, user_id="benchmark-user")
        context = build_portfolio_context(portfolio)
        rows = [{**row, "health_score": 70, "fundamental_score": 70, "valuation_score": 70,
                 "momentum_score": 70, "risk_contribution": 1 / 50, "data_confidence": "High",
                 "as_of": now} for row in holdings]
        bundle = {
            "prices": [{"ticker": row["ticker"], "date": now, "close": 100} for row in holdings],
            "fundamentals": [{"ticker": row["ticker"], "as_of": now} for row in holdings],
            "securities": [{"ticker": row["ticker"], "sector": "Benchmark", "industry": "Benchmark"} for row in holdings],
        }
        overview = {"as_of": now, "health": {"score": 70}, "holdings": rows, "changes": [], "warnings": [],
                    "ask_cache": {"portfolio_intelligence": {}, "watchlist_research": [], "events": [],
                                  "scenarios": [], "latest_simulation": {"id": "simulation", "created_at": now},
                                  "latest_optimizer": {"id": "optimizer", "created_at": now}}}
        read_models.build_capability_read_models(
            "benchmark-user", portfolio, overview, input_fingerprint=context.version,
            profile={"watchlist": [], "updated_at": now}, thesis_rows=[], security_bundle=bundle,
            watchlist_bundle={"prices": [], "fundamentals": [], "securities": []}, baseline_available=True,
        )
        results = {}
        for model_type in TARGETS:
            timings = []
            for _ in range(SAMPLES):
                started = time.perf_counter()
                loaded = read_models.load_compatible_read_model(
                    "benchmark-user", str(portfolio["id"]), model_type, context.version,
                )
                assert loaded.state == read_models.CompatibilityState.CURRENT
                timings.append((time.perf_counter() - started) * 1000)
            results[model_type] = {"samples": SAMPLES, "p50_ms": round(percentile(timings, .50), 3),
                                   "p95_ms": round(percentile(timings, .95), 3)}
        print(json.dumps({"version": "local-sqlite-read-model-benchmark-v1", "results": results}, indent=2))


if __name__ == "__main__":
    main()
