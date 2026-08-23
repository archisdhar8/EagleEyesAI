from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import analytics_jobs, database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the durable EagleEyes analytics worker.")
    parser.add_argument("--once", action="store_true", help="Claim at most one bounded batch and exit.")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--concurrency", type=int, default=1, choices=range(1, 5))
    args = parser.parse_args()
    database.initialize()
    completed = analytics_jobs.run_worker(poll_seconds=args.poll_seconds, once=args.once, concurrency=args.concurrency)
    if args.once:
        print(f"Processed {completed} analytical job(s).")


if __name__ == "__main__":
    main()
