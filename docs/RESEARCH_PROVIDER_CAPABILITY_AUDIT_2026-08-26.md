# Research Provider Capability Audit

Date: 2026-08-26  
Scope: read-only inspection of EagleEyes code/configuration, Supabase normalized storage and lineage, configured Polygon/Massive entitlements, public SEC Company Facts, and latest issuer Inline XBRL.

## Corrected capability classification

Every one of the 148 Research Registry fields is assigned to exactly one requested class in `backend/research_provider_capability_registry.py`.

| Classification | Fields |
|---|---:|
| AVAILABLE_STORED | 20 |
| AVAILABLE_POLYGON_NOT_INGESTED | 13 |
| AVAILABLE_SEC_NOT_EXTRACTED | 9 |
| DERIVABLE_FROM_EXISTING_DATA | 52 |
| PLAN_GATED | 24 |
| TRUE_EXTERNAL_PROVIDER_GAP | 2 |
| MODEL_OUTPUT | 28 |
| **Total** | **148** |

The earlier audit conflated storage absence with provider absence. In particular, headquarters, employees, company description, after-hours values, insider transactions, institutional filings, short interest, float, and genuine Polygon news sentiment are available under the configured key but are not ingested.

## What the repo currently implements

`backend/ingestion.py` currently calls only:

- `/v3/reference/tickers` for the broad security catalog, retaining name, exchange and a small identifier mapping;
- `/v2/aggs/ticker/...` for daily stock bars;
- `/v2/reference/news`, but it discards the `insights` array and writes sentiment as `unknown`/`0.0`;
- SEC `/api/xbrl/companyfacts/CIK....json` for fourteen normalized tags.

`backend/market_context.py` implements `/v2/snapshot/locale/us/markets/stocks/tickers`, but it runs only when `MARKET_SNAPSHOT_MODE=polygon`. That setting and `POLYGON_REALTIME_ENTITLED` are both unset in the inspected environment.

The repo does not implement Polygon Ticker Details, Polygon/Massive financial statements, options contracts/snapshots/trades/quotes, 13F, Form 4, short interest, float, 10-K sections, risk factors, Benzinga, or TMX corporate events.

## Configured Polygon/Massive entitlement results

The exact subscription name is not stored in the repo and is not returned by these APIs. Endpoint-level probes are therefore the reliable entitlement evidence.

| Endpoint/capability | Result | Classification effect |
|---|---|---|
| Ticker Details `/v3/reference/tickers/{ticker}` | HTTP 200 | Address/HQ, description, employees and reference shares are available but not ingested. |
| Legacy financials `/vX/reference/financials` | HTTP 200 | Historical standardized statements are available today, but the endpoint is deprecated/sunset. |
| Fundamentals v1 statements/ratios | HTTP 403 | PLAN_GATED replacement endpoints. |
| News `/v2/reference/news` | HTTP 200; 20/20 sampled articles per ticker had insights | Sentiment and reasoning are available but discarded. |
| Stock snapshot | HTTP 200; aggregates only | Snapshot adapter is configured off; last trade/quote were not returned. |
| Daily open/close | HTTP 200 with `afterHours` and `preMarket` | After-hours value is available but not ingested. |
| Stock trades and quotes | HTTP 403 | PLAN_GATED for tick-level stock data. |
| Options contracts | HTTP 200 | Contract reference universe is available but not ingested. |
| Option chain/single-contract snapshots | HTTP 403 | PLAN_GATED IV, Greeks, OI, quotes and trades. |
| Option trades and quotes | HTTP 403 | PLAN_GATED; put/call trade/quote calculations cannot run. |
| Short interest, short volume and float | HTTP 200 | Available but not ingested. |
| Form 4 | HTTP 200 | Insider purchases/sales/counts are available but not ingested. |
| 13F | HTTP 200 | Institutional holdings are available but require identifier mapping and aggregation. |
| 10-K sections and risk factors | HTTP 200 | Filing narrative/risk data are available but not ingested. |
| Benzinga Earnings/Ratings/Consensus | HTTP 403 | PLAN_GATED. |
| TMX Corporate Events | HTTP 403 | PLAN_GATED. |

Polygon/Massive's option chain documentation explicitly lists IV, Greeks, open interest, quotes and trades in the response. The configured key's HTTP 403—not lack of provider support—is the blocker.

## Raw-response and storage audit

- No current Polygon price/news or SEC parquet cache exists under `data/raw` or `data/processed`.
- `provider_fetches` retains run status and row counts, but the inspected Polygon/SEC runs have no raw payload archive; `payload_hash` is null in the sampled rows.
- `fundamental_periods` retains only normalized metric JSON. `fundamental_observations` has no rows for AAPL, MSFT or NVDA.
- Current Polygon news rows preserve article fields but not Polygon's `insights` sentiment/reasoning.
- `market_events` and matching transcript documents remain empty for the audited tickers.

This means a source field can be provider-available yet unrecoverable from Supabase without calling the endpoint again. The capability registry now represents that distinction explicitly.

## SEC extraction findings

The current SEC adapter uses Company Facts, which intentionally aggregates entity-wide standard-taxonomy facts. The SEC documentation states that Company Facts includes facts applying to the entire filing entity; segment/geographic/customer dimensions must be taken from the Inline XBRL filing contexts or filing footnotes.

All three inspected filings contain structured axes for products/business segments, geography, and major customers. They also contain standard Company Facts tags for:

- revenue and capex;
- D&A/amortization;
- income-tax expense and effective tax rate;
- common/diluted shares.

Therefore segments, geography, D&A, tax, ROIC and EV/EBITDA are `AVAILABLE_SEC_NOT_EXTRACTED`, not provider gaps. Customer revenue concentration remains issuer-conditional, and legal customer names remain null when the issuer anonymizes them.

## Internally generated metrics

| Metric | Deterministic formula / policy |
|---|---|
| Revenue growth | `revenue(current aligned fiscal period) / revenue(prior-year same fiscal period) - 1` |
| EPS growth | `diluted EPS current / prior-year diluted EPS - 1`; when prior EPS ≤ 0, show values and leave percent null |
| Gross margin | `gross profit / revenue` for identical duration |
| Operating margin | `operating income / revenue` for identical duration |
| Net margin | `net income / revenue` for identical duration; derivable although not a separate displayed v1 registry field |
| FCF | `operating cash flow - capex` for identical duration |
| FCF margin | `FCF / revenue` for identical duration |
| Net cash | `cash and equivalents - total debt` |
| Share dilution | `diluted shares current / prior-year aligned diluted shares - 1` |
| ROIC | `NOPAT / average invested capital`; `NOPAT = operating income × (1-effective tax rate)`; `invested capital = debt + equity - cash` |
| P/E | `current adjusted price / TTM diluted EPS` |
| P/S | `market cap / TTM revenue` |
| EV/EBITDA | `(market cap + debt - cash) / (TTM operating income + TTM D&A)` |
| FCF yield | `TTM FCF / market cap` |
| Historical valuation range | Point-in-time trailing multiple sampled monthly; 10th/90th percentiles, minimum 24 observations |
| Peer median | Median current multiple for ≥3 eligible same-industry peers; same-sector fallback disclosed |
| Benchmark performance | `adjusted close end / adjusted close start - 1` over aligned sessions |
| Beta | `cov(asset daily returns, SPY daily returns) / var(SPY daily returns)`, minimum 30 overlaps |
| Volatility | Sample standard deviation of daily returns × `sqrt(252)` |
| Drawdown | Minimum of `adjusted close / running maximum - 1` |
| Support/resistance | 10th/25th and 75th/90th percentiles of latest 126 adjusted closes, filtered around current price |
| Portfolio correlation | Pearson correlation of overlapping daily adjusted-price returns, minimum 60 overlaps in current portfolio clustering |
| Portfolio overlap | Highest candidate/holding return correlation plus explicit sector/industry/ETF look-through where stored |
| Portfolio beta | Weighted sum of holding betas; after-buy beta recomputed with normalized post-trade weights |
| Stress-test impact | Revalue existing and candidate weights under the same versioned scenario shock; `after loss - before loss` is the incremental impact |

Every row except stress-test impact is deterministic once its named inputs and portfolio context exist. Stress impact is internally generated but remains `MODEL_OUTPUT` because the scenario definition and shock assumptions are policy/model inputs.

## Sources consulted

- Polygon/Massive Ticker Overview: <https://massive.com/docs/rest/stocks/tickers/ticker-overview>
- Polygon/Massive News: <https://massive.com/docs/rest/stocks/news>
- Polygon/Massive Options Chain Snapshot: <https://massive.com/docs/rest/options/snapshots/option-chain-snapshot>
- Massive Stocks endpoint catalog: <https://massive.com/docs/rest/stocks>
- Massive Partners endpoint catalog: <https://massive.com/docs/rest/partners/overview>
- SEC EDGAR APIs: <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- SEC Inline XBRL: <https://www.sec.gov/data-research/structured-data/inline-xbrl>
