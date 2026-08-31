#!/usr/bin/env python3
from __future__ import annotations

"""Profile the legacy or bounded Research-core data path in a clean process."""

import argparse
import json
import time

from backend import database, memory_telemetry
from backend.research_read_model import build_shared_research_model


def synthetic_bundle(ticker: str, mode: str) -> tuple[dict, list[str]]:
    """Construct the legacy upper-bound shape without private source data."""
    peers = [f"P{index}" for index in range(1, 9 if mode == "legacy" else 5)]
    benchmarks = ["SPY", "QQQ", "XLK", "SOXX"]
    symbols = [ticker, *peers, *benchmarks]
    bundle = {key: [] for key in ("securities", "security_master", "source_observations", "filing_facts",
                                   "fundamental_observations", "filing_documents", "fundamentals", "prices", "news", "company_markets")}
    for symbol in symbols:
        asset_type = "etf" if symbol in benchmarks else "stock"
        bundle["securities"].append({"ticker": symbol, "asset_type": asset_type, "company_name": symbol,
                                     "sector": "Technology", "industry": "Hardware"})
        bundle["security_master"].append({"ticker": symbol, "name": symbol, "metadata": {}})
        for period in range(8):
            bundle["fundamentals"].append({"ticker": symbol, "period_end": f"202{6 - period // 4}-{3 * (4 - period % 4):02d}-28",
                                           "fiscal_period": f"Q{4 - period % 4}", "fiscal_year": 2026 - period // 4,
                                           "metrics": {"revenue": 1000 - period * 20, "gross_profit": 400 - period * 8,
                                                       "operating_income": 200 - period * 4, "net_income": 150 - period * 3,
                                                       "eps_diluted": 2 - period * .05, "shares_diluted": 100}})
        sessions = (1400 if mode == "legacy" else 1260) if symbol == ticker else (
            1400 if mode == "legacy" else 756 if symbol in benchmarks else 2
        )
        bundle["prices"].extend({"ticker": symbol, "date": f"{2020 + index // 252}-{1 + (index % 252) // 21:02d}-{1 + index % 21:02d}",
                                 "close": 100 + index * .01, "provider": "fixture"} for index in range(sessions))
    fact_symbols = symbols if mode == "legacy" else [ticker]
    facts_per_symbol = 10_000 if mode == "legacy" else 1_800
    concepts = database.RESEARCH_CORE_XBRL_CONCEPTS
    for symbol in fact_symbols:
        bundle["filing_facts"].extend({
            "ticker": symbol, "id": index, "concept": concepts[index % len(concepts)], "context_id": f"c{index}",
            "accession_number": f"acc-{index % 12}", "period_start": "2025-01-01", "period_end": "2025-12-31",
            "filed_at": "2026-02-01", "form_type": "10-K", "value": 1000 + index,
            "dimensions": {}, "source_url": "https://example.test/filing", "metadata": {"fixture": True},
        } for index in range(facts_per_symbol))
    observation_symbols = symbols if mode == "legacy" else [ticker, *peers]
    observation_count = 40 if mode == "legacy" else 4
    for symbol in observation_symbols:
        bundle["source_observations"].extend({"ticker": symbol, "provider": "fixture", "dataset": "details",
                                              "metric": f"metric-{index}", "effective_at": "2026-08-28",
                                              "value_numeric": index, "metadata": {}} for index in range(observation_count))
    document_count = 1000 if mode == "legacy" else 8
    bundle["filing_documents"].extend({"ticker": ticker, "document_type": "risk_factor", "external_id": f"doc-{index}",
                                       "content": "risk " * 800, "metadata": {}, "source_url": "https://example.test/risk"}
                                      for index in range(document_count))
    return bundle, peers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="AAPL")
    parser.add_argument("--mode", choices=("legacy", "bounded"), default="bounded")
    parser.add_argument("--synthetic", action="store_true", help="Use a production-shaped fixture instead of the configured database")
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    started_rss = memory_telemetry.rss_bytes()
    started_peak = memory_telemetry.peak_rss_bytes()
    started_at = time.perf_counter()
    if args.synthetic:
        bundle, peers = synthetic_bundle(ticker, args.mode)
    else:
        peers = database.research_peer_tickers(
            ticker, 8 if args.mode == "legacy" else database.RESEARCH_CORE_MAX_PEERS,
        )
        if args.mode == "legacy":
            bundle = database.research_capability_data([ticker, *peers, "SPY", "QQQ", "XLK", "SOXX"])
        else:
            bundle = database.research_core_data(ticker, peer_tickers=peers)
    after_fetch_rss = memory_telemetry.rss_bytes()
    model = build_shared_research_model(ticker, bundle=bundle)
    ended_rss = memory_telemetry.rss_bytes()
    print(json.dumps({
        "ticker": ticker, "mode": args.mode, "duration_seconds": round(time.perf_counter() - started_at, 3),
        "ticker_count": 1 + len(peers) + 4, "peer_count": len(peers),
        "row_counts": {key: len(value) for key, value in bundle.items() if isinstance(value, list)},
        "path_counts": (bundle.get("_telemetry") or {}).get("paths"),
        "response_bytes": memory_telemetry.json_size_bytes(model),
        "rss_before_bytes": started_rss, "rss_after_fetch_bytes": after_fetch_rss, "rss_after_bytes": ended_rss,
        "rss_growth_bytes": ended_rss - started_rss if ended_rss is not None and started_rss is not None else None,
        "process_peak_before_bytes": started_peak, "process_peak_after_bytes": memory_telemetry.peak_rss_bytes(),
    }, default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
