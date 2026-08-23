#!/usr/bin/env python3
"""Scheduled provider ingestion; never depends on a user opening Today."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import database, feature_flags  # noqa: E402
from backend.ingestion import (  # noqa: E402
    active_tickers, refresh_fred, refresh_markets, refresh_news, refresh_polygon, refresh_sec, refresh_tiingo,
)
from backend.operational_monitoring import record_metric  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded EagleEyes provider-ingestion scope.")
    parser.add_argument("--scope", required=True, choices=("market", "fundamentals", "prediction"))
    parser.add_argument("--ticker-limit", type=int, default=50)
    args = parser.parse_args()
    database.initialize()
    tickers = active_tickers()[:max(1, min(args.ticker_limit, 100))]
    result: dict[str, object] = {"version": "scheduled-provider-ingestion-v1", "scope": args.scope}
    try:
        if args.scope == "market":
            if os.getenv("TIINGO_API_KEY"):
                result["prices"] = refresh_tiingo(tickers)
            elif os.getenv("POLYGON_API_KEY"):
                result["prices"] = refresh_polygon(tickers)
            else:
                raise RuntimeError("No configured price provider")
            result["macro"] = refresh_fred() if os.getenv("FRED_API_KEY") else "not_configured"
        elif args.scope == "fundamentals":
            result["fundamentals"] = refresh_sec(tickers)
            result["news"] = refresh_news(tickers) if os.getenv("POLYGON_API_KEY") else "not_configured"
        elif feature_flags.prediction_market_enrichment_enabled():
            result["prediction_markets"] = refresh_markets()
        else:
            result["prediction_markets"] = "disabled"
        record_metric("providers.ingestion.heartbeat", tags={"scope": args.scope, "status": "success"}, persist=True)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as exc:
        record_metric("providers.ingestion.failure", tags={"scope": args.scope, "error_class": type(exc).__name__}, persist=True)
        print(json.dumps({**result, "status": "failed", "error_class": type(exc).__name__}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
