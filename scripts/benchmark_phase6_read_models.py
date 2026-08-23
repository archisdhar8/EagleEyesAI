#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for value in (str(ROOT), str(SCRIPTS)):
    if value not in sys.path:
        sys.path.insert(0, value)

from backend import phase6_domains  # noqa: E402
from evaluate_phase6_acceptance import USER, seed  # noqa: E402


def measure(callable_, samples: int = 100) -> dict[str, float]:
    values = []
    for _ in range(samples):
        started = time.perf_counter()
        callable_()
        values.append((time.perf_counter() - started) * 1000)
    ordered = sorted(values)
    return {"median_ms": round(statistics.median(values), 4),
            "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 4),
            "max_ms": round(max(values), 4), "samples": samples}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eagleeyes-phase6-benchmark-") as directory:
        holdings, portfolio_id = seed(Path(directory) / "benchmark.db")
        cases = {
            "company_analysis": lambda: phase6_domains.company_analysis_result(USER, "MSFT"),
            "two_company_comparison": lambda: phase6_domains.company_comparison_result(USER, ["MSFT", "AMZN"], holdings),
            "macro_state": lambda: phase6_domains.macro_state_result(USER),
            "market_state": lambda: phase6_domains.market_state_result(USER),
            "prediction_market_state": lambda: phase6_domains.prediction_market_result(USER, portfolio_id),
        }
        results = {name: measure(callable_) for name, callable_ in cases.items()}

        def mixed_dag():
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(cases[name]) for name in ("company_analysis", "macro_state", "market_state")]
                return [future.result() for future in futures]

        results["mixed_three_capability_dag"] = measure(mixed_dag)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "benchmark": results,
               "environment": "local SQLite synthetic materialized read models",
               "note": "Local boundary benchmark only; it is not a production SLO and excludes network/auth latency."}
    target = ROOT / "artifacts" / "phase6-read-model-benchmark.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"artifact": str(target), **results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
