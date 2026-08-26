# Research Capability Implementation Validation — 2026-08-26

## Scope and invariants

- No provider was added and no paid plan was upgraded or assumed.
- The Research UI was not changed.
- Deterministic calculations live in `backend/research_metrics.py` and are consumed by both the Research read model and Ask `company_analysis`.
- Historical valuation samples require `filing.filed_at <= price.date`. Current fundamentals are never backfilled into historical dates.
- Polygon/Massive 403/plan-gated capabilities remain explicit `PLAN_GATED` fields.
- SEC dimensions come from Inline XBRL contexts/axes. Company Facts is used only for non-dimensional point-in-time filing history.

## Live ingestion completed

| Source | Live rows written | Scope |
|---|---:|---|
| Polygon/Massive news | 150 | AAPL, MSFT, NVDA; provider insights/reasoning preserved |
| Polygon/Massive Research observations/documents | 1,814 | Ticker Details, daily open/close plus pre/after, short interest/volume, float, Form 4, 10-K sections, risk factors |
| SEC Inline XBRL facts | 11,670 across the two validation passes | Recent filings with contexts, dimensions, units, periods, accessions and source URLs |
| SEC Company Facts history | 1,081 normalized reporting periods returned; canonical filing facts stored set-wise | Non-dimensional point-in-time denominator history |

The 13-F endpoint is wired with a verified-CUSIP guard. It does not fuzzy-match issuer names. The current security master has no canonical CUSIP for these issuers, so institutional percentage/change remain unavailable instead of risking a false match.

## 148-field staged coverage

Counts are cumulative. “Post SEC” excludes model-output fields; “with models” includes defensible model outputs whose inputs are present. Current is the pre-implementation live payload measured by the completed audit.

| Ticker | Current | Post-derived | Post-Polygon | Post-SEC | With model outputs |
|---|---:|---:|---:|---:|---:|
| AAPL | 43 / 148 (29.1%) | 58 (39.2%) | 68 (45.9%) | 83 (56.1%) | 102 (68.9%) |
| MSFT | 43 / 148 (29.1%) | 62 (41.9%) | 72 (48.6%) | 82 (55.4%) | 101 (68.2%) |
| NVDA | 43 / 148 (29.1%) | 48 (32.4%) | 61 (41.2%) | 85 (57.4%) | 104 (70.3%) |

Nineteen of the registry’s 28 model-output fields are populated when inputs are present (67.9% of model fields). Every emitted model value carries inputs, assumptions, methodology/model version, evidence links and as-of date.

For all three tickers, 24 / 148 fields (16.2%) remain plan-gated and 2 / 148 (1.4%) remain true external-provider gaps: founding date and earnings-call transcript content.

## Verified deterministic outputs

The live models now calculate aligned revenue/EPS growth, gross/operating/net margin, same-duration FCF/FCF margin, net cash/debt, dilution, ROIC, TTM values, P/E, P/S, EV, EV/EBITDA, FCF yield, historical percentiles/ranges, peer medians, benchmark returns, beta, volatility, drawdown, moving averages, RSI and deterministic support/resistance.

Point-in-time P/E histories contain 67 AAPL, 61 MSFT and 67 NVDA monthly samples. These samples use only fundamentals public by each sampled price date.

Inline XBRL produced product/segment and geography breakdowns for all three issuers. NVDA also exposes four anonymous sales-revenue customer concentration members (16%, 16%, 15%, 13% in the latest stored context). AAPL and MSFT do not disclose equivalent customer-revenue identities/percentages in the inspected facts; no substitute is emitted.

## Section outcomes

Fully populated displayed-field contracts:

- Financial Health: AAPL, MSFT, NVDA.
- Thesis: AAPL, MSFT, NVDA.
- Company Overview: NVDA. AAPL/MSFT remain partial solely on issuer-disclosed customer revenue fields.
- Market & Technical values: AAPL and NVDA. MSFT has no resistance level above the current price under the disclosed 75th/90th-percentile rule, so the deterministic null is preserved.

Cards that remain incomplete:

- Header: founding date only (true external-provider gap).
- Valuation: forward P/E and PEG only (plan-gated consensus inputs); current/historical/peer multiples, fair-value cases and implied expectations are populated.
- Earnings: consensus, revisions, next-event/session, expected move and surprise comparisons are plan-gated; call highlights require the transcript gap. Reported period history is populated.
- Catalysts & Risks: verified filing risks are populated, but confirmed future catalyst dates depend on the gated event calendar; severity/thesis linkage stays null without explicit evidence.
- Ownership & Sentiment: Form 4, short interest/change/days-to-cover, float and Polygon news sentiment are populated. Institutional percentage/change await a verified CUSIP-to-13-F mapping; analyst/options/put-call fields are plan-gated.
- Portfolio Fit: deterministic correlation/overlap/beta/stress calculations run when a selected portfolio and proposed weight are supplied. The global AAPL/MSFT/NVDA validation intentionally had no portfolio/policy context, so no weight, sector limit or opportunity-cost assumption was invented.
- Decision: thesis, rating, confidence, entry range, invalidation and primary risk are populated; key catalyst/next review remain dependent on the gated event calendar.
- Sources: verified and market/model provenance are populated; forecast provider remains plan-gated.

## Ask parity and verification

Ask `company_analysis` embeds the exact `research-read-model-v2.0.0` capability payload and 148-field map produced for Research. A parity test compares the field map from both paths; deterministic formulas are not duplicated.

Backend verification: **668 passed, 9 skipped**. New coverage includes formula invariants, point-in-time look-ahead rejection, Inline XBRL dimensions, registry-driven section status shape, Polygon news insight preservation and Research/Ask payload parity.

