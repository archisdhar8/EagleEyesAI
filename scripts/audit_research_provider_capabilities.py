from __future__ import annotations

import argparse
import json
from typing import Any

from backend.research_provider_capability_registry import CAPABILITIES, CAPABILITY_BY_KEY, capability_payload
from scripts.audit_research_metric_registry import audit as metric_audit


USABLE_STORED = {"AVAILABLE", "RECOVERABLE", "MODEL_READY"}
STORED_FORMULA_FIXES = {
    "AAPL": {"technical.rsi_read"},
    "MSFT": {"technical.rsi_read", "technical.resistance"},
    "NVDA": {"technical.rsi_read"},
}

# The configured key returned the legacy standardized financials endpoint for
# all three tickers on 2026-08-26. These are fields its returned statement
# concepts can unlock without the newer, plan-gated Fundamentals v1 endpoints.
POLYGON_FINANCIAL_UNLOCK = {
    "AAPL": {
        "summary.cheap", "financial.revenue_growth_yoy", "financial.eps_growth_yoy",
        "financial.gross_margin_change", "financial.operating_margin_change",
        "financial.share_count_change", "valuation.pe_ttm", "valuation.price_to_sales",
        "valuation.history_range", "valuation.read",
    },
    "MSFT": set(),
    "NVDA": {
        "summary.cheap", "financial.revenue_growth_yoy", "financial.revenue_trend",
        "financial.gross_margin", "financial.gross_margin_change", "financial.operating_margin",
        "financial.operating_margin_change", "financial.chart.revenue",
        "financial.chart.gross_margin", "financial.chart.operating_margin",
        "valuation.price_to_sales", "valuation.history_range", "valuation.read",
    },
}

# Customer identities are anonymized in all three filings. AAPL's customer
# facts are receivable/vendor concentration rather than revenue concentration;
# MSFT's MajorCustomers contexts are remaining-performance-obligation facts.
SEC_DISCLOSED_FIELDS = {
    "AAPL": {
        "overview.segment.name", "overview.segment.revenue_share", "overview.segment.growth",
        "overview.geography.name", "overview.geography.revenue_share", "financial.roic",
        "valuation.ev_ebitda",
    },
    "MSFT": {
        "overview.segment.name", "overview.segment.revenue_share", "overview.segment.growth",
        "overview.geography.name", "overview.geography.revenue_share", "financial.roic",
        "valuation.ev_ebitda",
    },
    "NVDA": {
        "overview.segment.name", "overview.segment.revenue_share", "overview.segment.growth",
        "overview.geography.name", "overview.geography.revenue_share",
        "overview.customer.revenue_share", "financial.roic", "valuation.ev_ebitda",
    },
}

SEC_DERIVATION_PREFIXES = ("financial.", "valuation.")
SEC_DERIVATION_KEYS = {"summary.improving", "summary.cheap"}


def _sec_derivation(key: str) -> bool:
    capability = CAPABILITY_BY_KEY[key].classification
    return (
        capability in {"DERIVABLE_FROM_EXISTING_DATA", "AVAILABLE_STORED"}
        and (key.startswith(SEC_DERIVATION_PREFIXES) or key in SEC_DERIVATION_KEYS)
    )


def coverage(tickers: list[str]) -> dict[str, Any]:
    audited = metric_audit(tickers)
    output: dict[str, Any] = {
        "version": "research-provider-capability-coverage-v2",
        "metric_count": len(CAPABILITIES),
        "capability_registry": capability_payload(),
        "tickers": {},
    }
    for ticker in tickers:
        detail = audited["tickers"][ticker]
        rows = {row["key"]: row for row in detail["metrics"]}
        current = {key for key, row in rows.items() if row["status"] == "AVAILABLE"}
        stored = {key for key, row in rows.items() if row["status"] in USABLE_STORED}
        stored |= STORED_FORMULA_FIXES.get(ticker, set())

        polygon = set(stored)
        polygon |= {
            key for key in rows
            if CAPABILITY_BY_KEY[key].classification == "AVAILABLE_POLYGON_NOT_INGESTED"
        }
        polygon |= POLYGON_FINANCIAL_UNLOCK.get(ticker, set())

        sec = set(polygon) | SEC_DISCLOSED_FIELDS.get(ticker, set())
        sec |= {key for key, row in rows.items() if row["status"] not in USABLE_STORED and _sec_derivation(key)}

        issuer_not_disclosed = {
            key for key in rows
            if CAPABILITY_BY_KEY[key].classification == "AVAILABLE_SEC_NOT_EXTRACTED" and key not in SEC_DISCLOSED_FIELDS.get(ticker, set())
        }
        remaining = set(rows) - sec
        output["tickers"][ticker] = {
            "source_dates": detail["source_dates"],
            "coverage": {
                "current_payload_non_null": len(current),
                "achievable_existing_stored": len(stored),
                "achievable_after_polygon_ingestion": len(polygon),
                "achievable_after_sec_extraction": len(sec),
            },
            "incremental": {
                "stored_formula_wiring": sorted(stored - current),
                "polygon_ingestion": sorted(polygon - stored),
                "sec_extraction": sorted(sec - polygon),
            },
            "remaining": {
                "plan_gated": sorted(key for key in remaining if CAPABILITY_BY_KEY[key].classification == "PLAN_GATED"),
                "true_external_provider_gap": sorted(key for key in remaining if CAPABILITY_BY_KEY[key].classification == "TRUE_EXTERNAL_PROVIDER_GAP"),
                "model_output_not_ready": sorted(key for key in remaining if CAPABILITY_BY_KEY[key].classification == "MODEL_OUTPUT"),
                "portfolio_context_required_deterministic": sorted(
                    key for key in remaining
                    if rows[key]["status"] == "CONTEXT_REQUIRED"
                    and CAPABILITY_BY_KEY[key].classification != "MODEL_OUTPUT"
                ),
                "issuer_not_disclosed": sorted(issuer_not_disclosed),
            },
        }
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only Polygon/SEC capability coverage audit.")
    parser.add_argument("tickers", nargs="*", default=["AAPL", "MSFT", "NVDA"])
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = coverage([ticker.upper() for ticker in args.tickers])
    if args.summary:
        result.pop("capability_registry", None)
        for item in result["tickers"].values():
            item.pop("incremental", None)
            item["remaining"] = {key: len(value) for key, value in item["remaining"].items()}
    print(json.dumps(result, indent=2, default=str))
