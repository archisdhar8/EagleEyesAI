from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .research_metric_registry import REGISTRY


CapabilityClass = Literal[
    "AVAILABLE_STORED",
    "AVAILABLE_POLYGON_NOT_INGESTED",
    "AVAILABLE_SEC_NOT_EXTRACTED",
    "DERIVABLE_FROM_EXISTING_DATA",
    "PLAN_GATED",
    "TRUE_EXTERNAL_PROVIDER_GAP",
    "MODEL_OUTPUT",
]


@dataclass(frozen=True)
class ProviderCapability:
    key: str
    classification: CapabilityClass
    basis: str
    endpoint_or_source: str
    entitlement_evidence: str

    def payload(self) -> dict[str, str]:
        return asdict(self)


POLYGON_NOT_INGESTED = {
    "header.after_hours_change",
    "header.employees",
    "header.headquarters",
    "summary.what_it_does",
    "overview.business_description",
    "ownership.institutional_percent",
    "ownership.institutional_change",
    "ownership.insider_net",
    "ownership.insider_count",
    "ownership.short_percent",
    "ownership.short_change",
    "ownership.days_to_cover",
    "sentiment.news_score",
}

SEC_NOT_EXTRACTED = {
    "overview.segment.name",
    "overview.segment.revenue_share",
    "overview.segment.growth",
    "overview.geography.name",
    "overview.geography.revenue_share",
    "overview.customer.name",
    "overview.customer.revenue_share",
    "financial.roic",
    "valuation.ev_ebitda",
}

PLAN_GATED = {
    "valuation.forward_pe",
    "valuation.peg",
    "earnings.estimate.period",
    "earnings.estimate.revenue",
    "earnings.estimate.eps",
    "earnings.estimate.revenue_revision",
    "earnings.estimate.eps_revision",
    "earnings.next.date",
    "earnings.next.session",
    "earnings.next.days",
    "earnings.next.expected_move",
    "earnings.surprise.revenue",
    "earnings.surprise.eps",
    "earnings.surprise.price_response",
    "catalyst.date",
    "ownership.analyst_consensus",
    "ownership.analyst_counts",
    "ownership.revision_signal",
    "ownership.iv_30d",
    "ownership.iv_rank",
    "ownership.event_premium",
    "ownership.put_call",
    "decision.next_review",
    "sources.forecast.provider",
}

TRUE_EXTERNAL_GAP = {
    "header.founded",
    "earnings.call_highlight",
}

MODEL_WITH_EXTERNAL_INPUT = {"earnings.call_highlight"}


def _classify(key: str, metric_class: str) -> CapabilityClass:
    if key in POLYGON_NOT_INGESTED:
        return "AVAILABLE_POLYGON_NOT_INGESTED"
    if key in SEC_NOT_EXTRACTED:
        return "AVAILABLE_SEC_NOT_EXTRACTED"
    if key in PLAN_GATED:
        return "PLAN_GATED"
    if key in TRUE_EXTERNAL_GAP:
        return "TRUE_EXTERNAL_PROVIDER_GAP"
    if metric_class == "MODEL" and key not in MODEL_WITH_EXTERNAL_INPUT:
        return "MODEL_OUTPUT"
    if metric_class == "DERIVED":
        return "DERIVABLE_FROM_EXISTING_DATA"
    return "AVAILABLE_STORED"


def _details(classification: CapabilityClass, key: str) -> tuple[str, str, str]:
    if classification == "AVAILABLE_POLYGON_NOT_INGESTED":
        if key == "header.after_hours_change":
            return (
                "Configured key returned afterHours and preMarket values, but the repo only ingests daily bars/snapshots.",
                "Polygon/Massive GET /v1/open-close/{ticker}/{date}", "HTTP 200 with configured key",
            )
        if key in {"header.employees", "header.headquarters", "summary.what_it_does", "overview.business_description"}:
            return (
                "Ticker Details returned total_employees, address, and description for all audited tickers.",
                "Polygon/Massive GET /v3/reference/tickers/{ticker}", "HTTP 200 with configured key",
            )
        if key.startswith("ownership.institutional"):
            return (
                "13F holdings are accessible and can be identifier-mapped and aggregated against outstanding shares.",
                "Massive GET /stocks/filings/vX/13-F", "HTTP 200 early-access beta",
            )
        if key.startswith("ownership.insider"):
            return (
                "Normalized Form 4 transactions are accessible but not ingested.",
                "Massive GET /stocks/filings/vX/form-4", "HTTP 200 early-access beta",
            )
        if key.startswith("ownership.short"):
            return (
                "Short-interest history, average volume, days-to-cover, and float are accessible but not ingested.",
                "Massive GET /stocks/v1/short-interest and /stocks/vX/float", "HTTP 200 with configured key",
            )
        return (
            "Polygon news insights include ticker sentiment and reasoning; current ingestion discards insights.",
            "Polygon/Massive GET /v2/reference/news", "HTTP 200; insights present in 20/20 sampled articles per ticker",
        )
    if classification == "AVAILABLE_SEC_NOT_EXTRACTED":
        if key in {"financial.roic", "valuation.ev_ebitda"}:
            return (
                "Company Facts and Inline XBRL contain tax and D&A concepts for all audited issuers; current SEC_TAGS omit them.",
                "SEC Company Facts plus issuer Inline XBRL", "Public SEC source; verified in latest 10-Ks",
            )
        return (
            "Latest issuer Inline XBRL contains segment, ProductOrService, geography, and/or MajorCustomers axes.",
            "SEC filing Inline XBRL contexts and footnotes", "Public SEC source; verified in latest 10-Ks",
        )
    if classification == "PLAN_GATED":
        if key.startswith("ownership.iv") or key in {"ownership.put_call", "earnings.next.expected_move"}:
            return (
                "Polygon offers chain snapshots with IV, Greeks, OI, quotes, and trades, but the configured key is not entitled.",
                "Polygon/Massive Options snapshots, trades, and quotes", "HTTP 403 NOT_AUTHORIZED",
            )
        if key in {"valuation.forward_pe", "valuation.peg", "ownership.analyst_consensus", "ownership.analyst_counts", "ownership.revision_signal", "sources.forecast.provider"} or key.startswith("earnings.estimate"):
            return (
                "Massive exposes Benzinga earnings/ratings/consensus or gated Fundamentals ratios; the configured key is not entitled.",
                "Massive Benzinga/Fundamentals expansion endpoints", "HTTP 403 NOT_AUTHORIZED",
            )
        return (
            "Massive exposes earnings/corporate-event data through Benzinga or TMX expansion endpoints; the configured key is not entitled.",
            "Massive /benzinga/v1/earnings or /tmx/v1/corporate-events", "HTTP 403 NOT_AUTHORIZED",
        )
    if classification == "TRUE_EXTERNAL_PROVIDER_GAP":
        if key == "header.founded":
            return (
                "Ticker Details provides list_date, not company founding date; SEC filings do not provide a reliable normalized founding field.",
                "No reliable existing normalized provider field", "Absent from inspected provider schemas",
            )
        return (
            "Neither the repo nor the inspected Polygon/Massive and SEC endpoints provide earnings-call transcript content.",
            "Transcript ingestion/provider required", "No transcript endpoint found; no stored transcript rows",
        )
    if classification == "MODEL_OUTPUT":
        return (
            "This is a versioned EagleEyes analytical/policy output, not a provider fact.",
            "Existing evidence plus approved EagleEyes model/policy", "No external provider required for the output itself",
        )
    if classification == "DERIVABLE_FROM_EXISTING_DATA":
        return (
            "The registry defines a deterministic formula over existing prices, fundamentals, classifications, or portfolio data.",
            "Existing EagleEyes normalized tables/read models", "No provider upgrade required; null when required inputs are absent",
        )
    return (
        "The source value is already stored in an existing normalized EagleEyes table/read model.",
        "Existing EagleEyes normalized tables/read models", "Stored",
    )


CAPABILITIES: tuple[ProviderCapability, ...] = tuple(
    ProviderCapability(metric.key, category, *_details(category, metric.key))
    for metric in REGISTRY
    for category in [_classify(metric.key, metric.classification)]
)

CAPABILITY_BY_KEY = {item.key: item for item in CAPABILITIES}


def capability_payload() -> dict[str, object]:
    return {
        "version": "research-provider-capability-audit-v2",
        "classifications": [
            "AVAILABLE_STORED", "AVAILABLE_POLYGON_NOT_INGESTED", "AVAILABLE_SEC_NOT_EXTRACTED",
            "DERIVABLE_FROM_EXISTING_DATA", "PLAN_GATED", "TRUE_EXTERNAL_PROVIDER_GAP", "MODEL_OUTPUT",
        ],
        "metrics": [item.payload() for item in CAPABILITIES],
    }

