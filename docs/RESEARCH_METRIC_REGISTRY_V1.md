# EagleEyes Research Metric Registry v1

Date: 2026-08-26

> Provider-capability classifications were re-audited after this base contract was written. Use `backend/research_provider_capability_registry.py` and `docs/RESEARCH_PROVIDER_CAPABILITY_AUDIT_2026-08-26.md` for the authoritative distinction between storage absence, entitled Polygon data, SEC extraction, plan gates, and true external gaps.

## Canonical contract

The complete field-by-field contract is implemented in `backend/research_metric_registry.py`. It contains 148 displayed fields. Every field has all of the following machine-readable attributes:

- stable key, section, and display label;
- classification: `SOURCE`, `DERIVED`, `MODEL`, or `UNAVAILABLE`;
- existing EagleEyes tables, exact columns, and providers;
- deterministic formula or explicit model/ingestion requirement;
- required inputs and freshness policy;
- null behavior and evidence type;
- section-status role (`CORE`, `SUPPORTING`, `INFORMATIONAL`, or `CONDITIONAL`);
- implementation state and current Research payload path.

`registry_payload()` serializes the contract without coupling it to the UI. The live audit is `scripts/audit_research_metric_registry.py`.

## Registry inventory

| Dimension | Count |
|---|---:|
| Total displayed fields | 148 |
| SOURCE | 20 |
| DERIVED | 59 |
| MODEL | 29 |
| UNAVAILABLE | 40 |
| Mapped to current payload behavior | 37 |
| Deterministic wiring contract | 39 |
| Existing evidence, model/policy logic required | 17 |
| Existing portfolio capability, user context required | 8 |
| New ingestion required | 47 |

The 47 `NEW_INGESTION` fields include seven fields classified as derived/model outputs whose prerequisite source is not stored. Therefore `NEW_INGESTION` is intentionally larger than the 40 fields classified `UNAVAILABLE`.

| Section | Fields |
|---|---:|
| Header | 15 |
| Five-question summary | 5 |
| Company overview | 10 |
| Financial health | 19 |
| Valuation | 14 |
| Earnings | 14 |
| Thesis | 4 |
| Catalysts and risks | 8 |
| Market and technical data | 18 |
| Ownership and sentiment | 16 |
| Portfolio fit | 9 |
| Decision | 9 |
| Sources and freshness | 7 |

## Classification rules

- `SOURCE`: a stored value can be displayed without analytical transformation other than normalization or selection.
- `DERIVED`: an exact deterministic formula is specified and every input must be evidence-backed.
- `MODEL`: the result depends on versioned analytical judgment, assumptions, thresholds, or portfolio policy. It must be labeled opinion/forecast as specified.
- `UNAVAILABLE`: EagleEyes does not currently store the required source. The UI must return null; no synthetic sample, zero, neutral score, or unsupported prose is allowed.

## Section status policy

- `SUCCESS`: every fresh `CORE` field is non-null.
- `PARTIAL`: at least one `CORE` field is usable, but another is missing or stale.
- `UNAVAILABLE`: no `CORE` field is usable.
- `FAILED`: a source or calculation error prevents evaluation. This is distinct from a legitimate null.

`SUPPORTING`, `INFORMATIONAL`, and `CONDITIONAL` fields do not independently fail a section. Their absence is still reported in field coverage and evidence metadata.

The live audit reports two statuses:

- `current_status`: what the current Research payload actually emits.
- `maximized_existing_status`: what can be emitted after deterministic wiring and approved model logic, without a new source/provider.

## Existing source map

| Capability | Existing storage | Principal fields/providers |
|---|---|---|
| Security identity/classification | `securities`, `security_master`, `security_coverage_snapshots` | ticker, company name, sector, industry, exchange; stored security master / Polygon reference |
| Market prices | `price_bars`, limited `market_observations` | timestamps, close, adjusted close, volume, snapshot metadata; Polygon and Tiingo |
| Fundamentals | `fundamental_periods` | normalized revenue, income, EPS, cash flow, balance sheet, diluted shares; SEC |
| Raw normalized facts | `fundamental_observations` | intended fact-level store; currently empty for the audited securities |
| News/evidence | `news_documents` and Research read model | title, summary, timestamps, URL, event/catalyst/risk metadata, sentiment; news ingestion |
| Events | `market_events` | event timestamp/type/metadata; zero matching rows in this audit |
| Documents/transcripts | `documents`, `document_chunks` | filing/transcript evidence; zero matching transcript rows in this audit |
| Thesis/model evidence | `investment_theses`, `thesis_factors`, Research read model | bull/bear statements, factors, invalidations |
| Portfolio analytics | saved holdings/read models and price history | exposure, correlations, beta, overlap and stress logic; authenticated portfolio context required |
| Macro/prediction markets | `market_observations` and existing market adapters | FRED/Kalshi/Polymarket where mapped; not a substitute for company events or consensus |

## Deterministic safeguards

- Period comparisons require the same fiscal period in different fiscal years; incomplete or balance-sheet-only duplicates are excluded.
- Free cash flow is operating cash flow minus capex for identical reporting duration. Quarterly and year-to-date values may not be mixed.
- Historical valuation ranges are point-in-time, monthly sampled, and require at least 24 observations; current fundamentals must not be backfilled across history.
- Peer medians require at least three eligible same-industry securities, with same-sector fallback disclosed.
- Price-derived metrics use adjusted closes and explicit observation windows.
- Missing inputs return null and contribute to `PARTIAL`/`UNAVAILABLE`; they never become zero.
- Every model output must carry its model/version, assumptions, evidence type, and calculation timestamp.

## Reproducible audit

```bash
PYTHONPATH=. .venv/bin/python scripts/audit_research_metric_registry.py --summary AAPL MSFT NVDA
```

Remove `--summary` to emit all 148 per-field audit rows and the full registry payload.
