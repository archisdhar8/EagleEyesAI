from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import database, read_models  # noqa: E402
from backend.ask_runtime import build_portfolio_context  # noqa: E402
from backend.operational_monitoring import record_metric  # noqa: E402


def main() -> None:
    """Cron/scheduler entry point for durable missed-invalidation reconciliation."""
    results: list[dict[str, object]] = []
    for scope in database.analytical_read_model_scopes():
        try:
            portfolio = database.get_portfolio(scope["portfolio_id"], scope["user_id"])
            fingerprint = build_portfolio_context(portfolio).version
            states = read_models.reconcile_portfolio_read_models(
                scope["user_id"], scope["portfolio_id"], fingerprint,
            )
            results.append({**scope, "states": states})
        except Exception as exc:
            results.append({**scope, "error_class": type(exc).__name__})
    failures = sum("error_class" in row for row in results)
    record_metric("read_models.reconciliation.heartbeat", tags={"scopes": len(results), "failures": failures}, persist=bool(database.DATABASE_URL))
    print(json.dumps({"version": "read-model-reconciliation-v1", "scopes": results}, indent=2))


if __name__ == "__main__":
    main()
