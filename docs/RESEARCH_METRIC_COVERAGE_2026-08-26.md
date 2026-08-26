# Research Metric Coverage v2: AAPL, MSFT, NVDA

Audit date: 2026-08-26  
Registry: `research-metric-registry-v1` (148 fields)  
Capability audit: `research-provider-capability-audit-v2`

This report supersedes the earlier storage-only coverage report. It distinguishes data absent from Supabase from data available through the configured Polygon/Massive account or public SEC filings.

No provider was added, no ingestion was executed, and no UI file was changed.

## Coverage ceilings

Coverage is cumulative from left to right.

| Ticker | Current payload non-null | Existing stored data | + entitled Polygon ingestion | + SEC extraction | True external-provider gaps |
|---|---:|---:|---:|---:|---:|
| AAPL | 43 / 148 (29.1%) | 70 (47.3%) | 92 (62.2%) | 103 (69.6%) | 2 (1.4%) |
| MSFT | 43 / 148 (29.1%) | 84 (56.8%) | 96 (64.9%) | 103 (69.6%) | 2 (1.4%) |
| NVDA | 43 / 148 (29.1%) | 67 (45.3%) | 92 (62.2%) | 104 (70.3%) | 2 (1.4%) |

The remaining fields after the SEC ceiling are not all provider gaps:

| Remaining class | Fields | Meaning |
|---|---:|---|
| PLAN_GATED | 24 | Polygon/Massive exposes the endpoint, but the configured key returned HTTP 403. |
| MODEL_OUTPUT not ready | 11 | An EagleEyes model/policy must be approved and versioned. |
| Portfolio context required, deterministic | 6 | Existing capability needs the signed-in user's holdings/policy context. |
| TRUE_EXTERNAL_PROVIDER_GAP | 2 | Founding date and earnings-call transcript content. |
| Issuer did not disclose the requested customer field | AAPL 2; MSFT 2; NVDA 1 | A valid null, not a provider failure. |

These rows reconcile exactly to 148 per ticker. Two context-dependent model outputs are counted under `MODEL_OUTPUT`, not counted twice under portfolio context.

## Incremental coverage by layer

### Existing stored data

The stored-data ceiling includes current non-null fields, deterministic formulas whose inputs are already stored, and evidence-backed model outputs already supported by the Research read model. It also corrects two audit-token omissions: RSI interpretation is directly derivable for all three, and MSFT resistance is derivable from its stored 126-session history.

It excludes portfolio-only fields because this three-ticker audit did not impersonate a real user's holdings.

### Additional entitled Polygon/Massive ingestion

| Ticker | Incremental fields | Main sources |
|---|---:|---|
| AAPL | +22 | Ticker Details, open/close after-hours, legacy financials, 13F, Form 4, short interest/float, news insights |
| MSFT | +12 | Ticker Details, open/close after-hours, 13F, Form 4, short interest/float |
| NVDA | +25 | Same sources as AAPL; legacy financials also repair currently missing normalized revenue fields |

Polygon news sentiment is a quality upgrade rather than an additional field count: `sentiment.news_score` is currently non-null, but the ingestion writes `unknown` and `0.0` while discarding Polygon's supplied `insights.sentiment` and `sentiment_reasoning`.

The configured key returned the legacy `/vX/reference/financials` endpoint for all three securities. The provider has officially deprecated/sunset that endpoint and the replacement Fundamentals v1 endpoints returned HTTP 403. The Polygon ceiling therefore describes what the key returned during this audit, with explicit deprecation risk; SEC remains the durable primary source for filing facts.

### Additional SEC extraction

| Ticker | Incremental fields | Filing result |
|---|---:|---|
| AAPL | +11 | Segment/product and geography data, D&A/tax facts, ROIC/EV-EBITDA inputs, remaining FCF calculations |
| MSFT | +7 | Segment/geography and D&A/tax extraction |
| NVDA | +12 | Segment/geography, disclosed anonymous customer revenue concentration, D&A/tax, and remaining FCF calculations |

Latest inspected 10-Ks:

- AAPL: filed 2025-10-31, period ended 2025-09-27.
- MSFT: filed 2026-07-29, period ended 2026-06-30.
- NVDA: filed 2026-02-25, period ended 2026-01-25.

All three Inline XBRL filings contain `ProductOrServiceAxis`/business-segment axes, `StatementGeographicalAxis`, `MajorCustomersAxis`, D&A concepts, tax concepts, capex, revenue, and share facts. However:

- AAPL's customer concentration facts concern receivables/vendors, not customer revenue share.
- MSFT's customer-axis facts concern remaining performance obligations, not a named customer's revenue share.
- NVDA discloses revenue concentration for anonymous `CustomerOne`/`CustomerTwo` members.
- None of the three filings identifies a material customer by legal name for this card.

Those issuer-level nulls must remain null even after a correct SEC extractor.

## Remaining plan-gated fields

The configured key returned HTTP 403 for each source below:

- Options chain/contract snapshots, option trades and option quotes: expected move, IV, Greeks-dependent calculations, open interest, IV rank, event premium and put/call ratio.
- Benzinga Earnings: earnings calendar, consensus actual-versus-estimate data and surprise history.
- Benzinga Ratings/Consensus: analyst consensus/counts and revision signals.
- TMX Corporate Events: confirmed earnings/corporate event dates and sessions.
- Fundamentals v1 ratios/statements: current replacement for the deprecated legacy financials endpoint.

These are `PLAN_GATED`, not external-provider gaps: they are sold through the already configured Polygon/Massive provider surface.

## True external-provider gaps

Only two registry fields remain in this class:

1. `header.founded`: Polygon Ticker Details returns `list_date`, which is not the founding date; SEC does not expose a reliable normalized founding field.
2. `earnings.call_highlight`: no earnings-call transcript content exists in Supabase, SEC filing APIs, or the inspected Polygon/Massive endpoint catalog.

## Reproduce

```bash
PYTHONPATH=. .venv/bin/python scripts/audit_research_provider_capabilities.py --summary AAPL MSFT NVDA
```

Remove `--summary` for every field, its exact capability classification, basis, endpoint/source, entitlement evidence, and the incremental field lists for each ticker.

