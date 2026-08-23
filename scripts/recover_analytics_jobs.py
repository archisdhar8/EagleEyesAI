from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import analytics_jobs, database  # noqa: E402
from backend.operational_monitoring import record_metric  # noqa: E402


if __name__ == "__main__":
    database.initialize()
    recovered = analytics_jobs.recover_expired_leases()
    record_metric("analytics.recovery.heartbeat", tags={"recovered": recovered}, persist=bool(database.DATABASE_URL))
    print(f"Recovered {recovered} expired analytical job lease(s).")
