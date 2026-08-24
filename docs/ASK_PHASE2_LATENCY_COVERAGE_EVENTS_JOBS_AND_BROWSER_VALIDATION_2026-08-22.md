# EagleEyes Ask Phase 2 latency, coverage, events, jobs, and browser validation

**Date:** August 22, 2026
**Environment:** signed-in local app at `http://localhost:3000/ask`, Supabase-backed API at `http://127.0.0.1:8000`
**Portfolio:** `d4a0d97e-154e-4b67-b672-e9c05d582952`
**Portfolio context fingerprint:** `185ffe91a9b60dcdb13a`
**Gemini narration:** disabled; every acceptance answer was deterministic
**Deployment/migrations:** no deployment and no migration applied

## Executive result

- The exact signed-in browser 15 remain 8 fully useful, 6 partial but useful, and 1 correct clarification.
- There were 0 misleading answers and 0 excluded-position leaks.
- Median visible latency fell from 10.231 seconds to 3.379 seconds. Mean fell from 10.070 seconds to 3.707 seconds, a 62.5% reduction.
- 14 of 15 questions rendered in under 5 seconds. All 15 rendered in under 8 seconds. The one 6.306-second DB outlier repeated immediately in 3.669 seconds.
- Normal requests used 9 DB queries with no duplicate query signatures. The clarification path used 11.
- Sector/classification semantics now use one explicit contract instead of treating security-master presence as sector coverage.
- Earnings, forward macro-calendar, and structured catalyst feeds remain genuinely unavailable from configured adapters. Ask now states that limitation. Prediction-market events are current.
- A real scenario and optimizer job completed, persisted compatible results, invalidated/rebuilt dependent read models, deduplicated correctly, and were recoverable through follow-up and conversation reopen.

## A. Latency breakdown

### Before versus after

| Measure | Before Phase 2 | After Phase 2 |
|---|---:|---:|
| Mean browser-visible latency | 10.070s | 3.707s |
| Median browser-visible latency | 10.231s | 3.379s |
| Minimum | 7.904s | 3.109s |
| Maximum | 12.396s | 6.306s |
| Questions under 5s | 0/15 | 14/15 |
| Questions under 8s | 1/15 | 15/15 |
| Mean reduction | — | 62.5% |

The first exact request was 4.202 seconds versus a 3.672-second mean for the remaining fourteen. That small cold/warm difference includes the first remote auth verification and connection/cache initialization. It is no longer an 8–12 second cold-start penalty.

### Measured request path

Instrumentation covers the real signed-in path:

```text
browser dispatch
  -> Supabase token validation (or 15-second verified-token cache hit)
  -> request reservation + conversation/portfolio context
  -> direct router/planner
  -> concurrent capability/read-model work and data-health lookup
  -> deterministic requirement resolution/composition
  -> transactional message/request persistence
  -> API response parse
  -> visible assistant article
```

The backend now publishes component timing through response metadata and `Server-Timing`. The frontend records dispatch, response receipt, JSON parse, state commit, and visible render. The `frontend` values below are browser-visible elapsed time minus backend completion time; they include transport, parse, React state work, and paint.

| # | Visible | Auth | Backend | Persistence | Frontend |
|---:|---:|---:|---:|---:|---:|
| 1 | 4.202s | 599ms | 4,036ms | 873ms | 166ms |
| 2 | 3.155s | <1ms | 2,890ms | 641ms | 265ms |
| 3 | 4.200s | 828ms | 4,040ms | 662ms | 160ms |
| 4 | 3.150s | <1ms | 3,044ms | 707ms | 107ms |
| 5 | 3.160s | <1ms | 2,888ms | 706ms | 272ms |
| 6 | 3.166s | <1ms | 2,969ms | 634ms | 197ms |
| 7 | 3.418s | <1ms | 3,150ms | 638ms | 268ms |
| 8 | 3.155s | <1ms | 3,050ms | 706ms | 105ms |
| 9 | 3.936s | <1ms | 3,759ms | 947ms | 177ms |
| 10 | 4.176s | 166ms | 3,894ms | 639ms | 282ms |
| 11 | 3.109s | <1ms | 3,046ms | 742ms | 63ms |
| 12 | 3.665s | <1ms | 3,392ms | 710ms | 273ms |
| 13 | 6.306s | <1ms | 6,237ms | 696ms | 69ms |
| 14 | 4.464s | <1ms | 4,345ms | 898ms | 119ms |
| 15 | 3.379s | <1ms | 3,105ms | 734ms | 274ms |

Question 13's execution/DB work spiked once. An immediate exact repeat took 3.669 seconds, so this was a remote DB latency outlier rather than a deterministic slow path. No deadline was increased.

## B. Query-count analysis

All query statistics were captured from request-scoped DB tracing on the signed-in API path.

| # | DB queries | Duplicate signatures | Rows fetched | DB latency | Response bytes |
|---:|---:|---:|---:|---:|---:|
| 1 | 9 | 0 | 83 | 1,501ms | 12,237 |
| 2 | 9 | 0 | 83 | 931ms | 10,886 |
| 3 | 9 | 0 | 81 | 1,292ms | 8,735 |
| 4 | 9 | 0 | 81 | 1,195ms | 13,865 |
| 5 | 9 | 0 | 83 | 1,050ms | 16,492 |
| 6 | 9 | 0 | 83 | 1,117ms | 10,957 |
| 7 | 9 | 0 | 83 | 1,276ms | 10,568 |
| 8 | 9 | 0 | 82 | 1,038ms | 12,363 |
| 9 | 9 | 0 | 82 | 1,888ms | 16,761 |
| 10 | 11 | 0 | 82 | 1,655ms | 8,777 |
| 11 | 9 | 0 | 81 | 1,201ms | 12,398 |
| 12 | 9 | 0 | 82 | 1,398ms | 12,269 |
| 13 | 9 | 0 | 81 | 4,195ms | 9,422 |
| 14 | 9 | 0 | 83 | 2,300ms | 10,468 |
| 15 | 9 | 0 | 83 | 1,157ms | 9,939 |

The ordinary path is stable at nine round trips. Question 10's two additional queries are the bounded security/entity resolution needed to determine that the user omitted the ticker. There are no repeated query signatures inside any request. Payloads are now 8.5–16.4 KiB rather than the earlier representative 125.6 KiB response.

## C. Latency fixes

1. **Safe auth reuse.** A remotely verified exact token is cached for at most 15 seconds and never past JWT expiry. Owner checks and Supabase RLS are unchanged. A fresh/cold verification remains visible in the timing data.
2. **Concurrent independent work.** Data-health derivation starts while the capability DAG executes. Optional read-model probes no longer block direct routes. Dependent writes remain ordered.
3. **Fewer persistence round trips.** Request reserve/bind/complete operations and assistant result persistence were consolidated where transactionally safe. Replay/idempotency state is still written before completion is returned.
4. **Asynchronous telemetry outbox.** Operational events are queued and written in bounded batches instead of adding a DB write to the user-visible path.
5. **Request-scoped query tracing and duplicate removal.** Context, model compatibility, source metadata, and health work no longer repeat within a request. The resulting trace shows zero duplicate signatures.
6. **Compact responses.** Duplicate canonical result blobs and broad evidence serialization were removed from the chat response. Result IDs and compact provenance remain.
7. **Direct deterministic routing retained.** Known portfolio risk, quality, valuation, multifactor, events, scenario, and optimizer requests do not invoke Gemini or an open-ended planner loop.
8. **Frontend render instrumentation.** The loading state ends when the persisted deterministic response commits. Render overhead is 63–282ms in this run and is not the remaining bottleneck.

A representative hidden-risk request moved from 12.739 seconds backend/125.6 KiB (auth 800ms, setup about 2.4s, tools 2.7s, persistence 4.3s) to 2.888 seconds backend/16.5 KiB (warm auth, execution 856ms, persistence 706ms).

## D. Classification reconciliation

### Why 48.2% and 96.7% disagreed

- The old **96.7%** meant only that a canonical security record existed. It did not prove that the position had an issuer sector, an industry, a fund classification, or ETF look-through.
- The old displayed **48.2%** was `1 - Unclassified` in the sector rows. That included approximately 2.2% cash as a non-`Unclassified` row.
- The claim actually needed for issuer-sector charts is **46.0% of portfolio weight across 34 directly classified issuers**.

The UI/read-model contract now names each measure instead of comparing unlike percentages.

| Coverage claim | Entity coverage | Portfolio-weight coverage | Meaning |
|---|---:|---:|---|
| Holding universe | 61/61 | 100.0% | Raw saved positions used by the classification contract |
| Security metadata | 59/61 (96.7%) | 96.7% | Canonical security record exists; not sector coverage |
| Direct issuer classification | 34/61 | 46.0% | Observed issuer sector and industry |
| Rendered issuer-sector rows | 34/61 | 46.0% | Weight assigned to displayed issuer sectors |
| Fund-level identity | 19/61 | 44.3% | ETF/mutual/bond/cash-like/commodity fund identity; not issuer fundamentals |
| Look-through available | 1 fund | 10.4% | Stored constituent look-through is usable |
| Look-through unavailable | 18 funds | 33.9% | Fund-level classification only |
| Unknown | 8/61 | 9.7% | No supported issuer/fund classification claim |
| Rendered unclassified weight | — | 54.0% | Funds without look-through plus unknown positions |

Unknown tickers are `CASH`, `EQNR`, `GLD`, `GLIFX`, `IAU`, `PONPX`, `PSDTX`, and `TEM`. Fund holdings are not mislabeled as companies missing fundamentals.

The affected read models were advanced and rebuilt outside Ask:

- `portfolio-risk-read-v3`, current, fingerprint `185ffe91a9b60dcdb13a`
- `portfolio-data-quality-read-v3`, current, same fingerprint
- classification contract `classification-coverage-v2`

The hidden-risk and data-quality acceptance questions then read these current models.

## E. Event ingestion and health

The existing configured providers were inspected before considering any provider expansion. The database has zero structured `market_events`; therefore no earnings or macro date was fabricated.

| Domain | Source/cadence | Current state | Coverage/freshness | Ask behavior |
|---|---|---|---|---|
| Earnings calendar | No configured adapter; no schedule can produce it | `MISSING` | 0% entity/weight coverage | States that no configured adapter supplies an earnings calendar |
| Macro release calendar | FRED/ALFRED supply observations, not forward release dates | `MISSING` | 0 events | States that FRED observations are not a forward calendar |
| Company catalysts | Only stored structured events are eligible; arbitrary news is not promoted | `MISSING` | 0 structured events | States the limitation rather than turning headlines into guaranteed catalysts |
| Prediction-market events | Existing Polymarket ingestion; configured hourly in GitHub Actions and Render, with 15-minute read-model reconciliation after dependency changes | `CURRENT` | 8 mapped events; latest stored observation Aug 17, 2026 | Shows sourced NVDA, GOOGL, and AMZN events with mapped weight, confidence, and freshness |

`portfolio-events-v3` and `portfolio-events-read-v3` track earnings, macro calendar, company catalysts, and prediction markets independently with `CURRENT/PARTIAL/STALE/MISSING/FAILED`. The current event model is `CURRENT` for its fingerprint but correctly `complete: false` because three categories are missing.

Configured cadences are source configuration, not a claim that production schedules ran during this local test. No deployment occurred.

## F. Scenario job lifecycle

The full durable lifecycle was exercised against Supabase:

1. The scenario request found no compatible simulation and queued job `bdd77e6d-ed30-4b43-a5ba-61122e47560e`.
2. Input fingerprint: `c95336506faa284ff8477a747f789a9469e85f92bea62dcc679c3d5a7819d4d3`.
3. Repeating the request did not create a duplicate active job; the durable dedupe count remained one.
4. The worker completed with `PARTIAL`, preserving a real result rather than treating warnings as total failure.
5. Simulation result `f826a0aa-dea4-411b-9149-bc4fe81970cd` was persisted with the job fingerprint and portfolio context version.
6. The run used 500 paths and 303 monthly observations. It disclosed proxy-history and robust-optimizer limitations; unsupported AI-loss magnitude was not invented.
7. Completion advanced the scenario dependency, invalidated dependent models, and rebuilt `portfolio-scenario-read-v2` as current for fingerprint `185ffe91a9b60dcdb13a`.
8. The same conversation answered “is it done?” with the completed simulation, without requiring a job ID.
9. After reopening that conversation from History, the messages restored in about 2.5 seconds and the same follow-up returned the completed simulation in 3.678 seconds.

Specific failure UX is also regression-tested: simulation failure says the simulation failed safely, while preserving deterministic evidence; worker absence says the worker is temporarily unavailable.

## G. Optimizer job lifecycle

1. The rebalance request queued optimizer job `df12d8cf-b933-4d32-be91-219d883b5055`.
2. Input fingerprint: `dc09…` (persisted full fingerprint); duplicate active/result rows remained one.
3. The worker completed `PARTIAL` and persisted analysis run `f8533241-d54e-4cfd-ba1b-26741ce38305`.
4. All three stored alternative weight sets sum to approximately one (`0.9999`, `1.0001`, `1.0000`); infeasible weights are not exposed as recommendations.
5. `optimizer-compatibility-read-v2` rebuilt as `CURRENT` for `185ffe91a9b60dcdb13a`.
6. The current decision is `actionable: true`, `feasibility: SATISFIED`, `portfolio_fingerprint_match: true`, expected turnover `0.7031`, and confidence `MEDIUM`.
7. The answer remains partial because tax lots and the trading-cost model are unavailable. It explicitly reports `tax_aware: false`, `tax_data_available: false`, and no exact cost claim.
8. A structural “show optimizer now” follow-up resolves the compatible result without a job ID.

Specific failure UX distinguishes optimizer failure from simulation failure and worker unavailability. The initial concentration/risk evidence remains available if heavy computation fails.

During lifecycle testing, two dependent overview rebuilds initially failed a DB trigger check because a new rebuild reason was passed where the audit trigger accepts only its existing enum. The rebuild mapping was corrected to use the allowed `MATERIAL_EVENT` trigger while preserving the original reason separately. A subsequent rebuild succeeded. No database constraint was weakened.

## H. Data-health remediation and import readiness

`DataHealthState` now maps each domain to an exact repair action. Regression tests cover:

| Condition | Status | Repair action |
|---|---|---|
| Fundamentals older than 120 days | `STALE` | `refresh_fundamentals` |
| Classification coverage below 100% | `PARTIAL` | `reconcile_security_master` |
| General events missing | `MISSING` | `refresh_event_feeds` |
| Earnings events missing | `MISSING` | `refresh_earnings_events` |
| Macro events missing | `MISSING` | `refresh_macro_event_calendar` |
| Company catalysts missing | `MISSING` | `refresh_company_catalysts` |
| Prediction events stale/missing | `STALE/MISSING` | `refresh_prediction_market_events` |
| Cash hurdle older than 8 days | `STALE` | `refresh_cash_hurdle` |

Portfolio import invalidates `portfolio_holdings` and queues the existing overview initialization. That lightweight path initializes the portfolio snapshot/read models, historical baseline, risk/data quality/factor state, event mapping, cash hurdle, and scenario exposure mappings. It does not automatically run an expensive simulation or optimizer.

## I. Exact signed-in browser 15

The table uses the original exact question order. “Jobs” is zero in the final acceptance pass because the previously queued compatible scenario and optimizer results were already complete; their enqueue/completion evidence is in sections F and G.

| # | Grade | Before | After | Jobs | Result/coverage and remaining limitation |
|---:|---|---:|---:|---:|---|
| 1 | Fully useful | 10.478s | 4.202s | 0 | MSFT, SBUX, QCOM ranked from eligible evidence; PARTIAL only for disclosed evidence warnings |
| 2 | Partial useful | 9.390s | 3.155s | 0 | No personal thesis; objective weakest holdings and watchlist comparison returned |
| 3 | Fully useful | 10.231s | 4.200s | 0 | Compatible baseline exists; no current change crosses materiality thresholds; final status `SUCCESS` |
| 4 | Fully useful | 12.299s | 3.150s | 0 | Ten eligible relative-valuation gaps; not intrinsic value/return forecast |
| 5 | Fully useful | 12.396s | 3.160s | 0 | Positions, correlations, dependencies, risk contribution, and reconciled classification contract |
| 6 | Partial useful | 10.275s | 3.166s | 0 | Completed compatible simulation returned; proxy/conditioning limits remain explicit |
| 7 | Fully useful | 9.737s | 3.418s | 0 | No new watchlist name proves dominance; owned names labeled add-to-existing |
| 8 | Partial useful | 8.679s | 3.155s | 0 | Eight current prediction events; three missing provider domains stated explicitly |
| 9 | Fully useful | 10.541s | 3.936s | 0 | Field-level coverage and exact unreliable holdings; no false aggregate 0/57 claim |
| 10 | Correct clarification | 7.904s | 4.176s | 0 | Requests a ticker; creates no company-specific claim |
| 11 | Partial useful | 8.932s | 3.109s | 0 | No saved breakers; objective risks for largest positions returned |
| 12 | Partial useful | 9.442s | 3.665s | 0 | Compatible feasible optimizer returned; tax/cost claims withheld |
| 13 | Fully useful | 11.053s | 6.306s | 0 | SBUX is the only exact match; immediate repeat 3.669s after DB outlier |
| 14 | Fully useful | 10.235s | 4.464s | 0 | MSFT countercase cites valuation, risk contribution, and AI dependency |
| 15 | Partial useful | 9.457s | 3.379s | 0 | Partial deployment, sourced 3.86% FRED DGS3MO hurdle; no unsupported excess-return proof |

### Normalized visible answers

1. **Strongest opportunities:** MSFT 64.1, SBUX 58.2, and QCOM 57.5, each with supporting/opposing evidence. The ranking is not a return forecast.
2. **Weakest thesis/replacement:** no saved personal theses exist. Objective weakest evidence is EPI, USIG, SPHY, SGOV, and VO; XLE, XLV, and VTI do not prove replacement dominance.
3. **Material changes:** a compatible current baseline exists, but no change now crosses the disclosed materiality thresholds. This valid zero-change result is `SUCCESS`, not failed coverage.
4. **Relative overvaluation:** QCOM, DLR, WMT, BLK, LHX, AVGO, SBUX, NOC, IBM, and TSLA have the largest eligible relative-value gaps. This is not intrinsic value.
5. **Hidden concentration:** direct issuer sector coverage is 46.0%; fund-level weight is 44.3%; only 10.4% has stored look-through; 54.0% remains unclassified in issuer-sector rendering. Correlation/dependency/risk-contribution evidence remains visible.
6. **Scenarios:** the completed compatible scenario result is available for rising rates and recession. It discloses conditioning/proxy limitations and does not invent an AI-spending loss magnitude where no calibrated mapping exists.
7. **Watchlist:** no new watchlist position proves a stronger risk-adjusted case. SPY/QQQ remain add-to-existing, not new positions.
8. **Events:** eight sourced prediction-market events map to NVDA, GOOGL, and AMZN. Earnings, forward macro calendar, and structured company catalysts are missing for explicit provider reasons.
9. **Data quality:** reliability is field-specific; the answer lists coverage and exact missing/placeholder inputs for each lower-trust holding.
10. **Score attribution:** “Name a holding (for example, `MSFT`) or open that holding’s research page.”
11. **Thesis invalidation:** no personal breakers are saved; objective modeled risks for the largest positions are returned without being called the user's thesis.
12. **Rebalance:** the compatible optimizer is feasible and fingerprint-matched, with target deltas and expected turnover. It is not tax-aware and does not estimate trading costs.
13. **Multifactor:** SBUX is the exact improving-fundamentals, available-valuation, positive-momentum match.
14. **Countercase:** MSFT’s strongest counterarguments are demanding valuation, modeled risk contribution, and AI-infrastructure dependency.
15. **Cash allocation:** partial deployment is compared with a 3.86% annualized FRED DGS3MO hurdle as of August 19, 2026. No expected-return model proves superiority to cash.

### Conversation behavior

- Reload/history/new-chat behavior remains functional.
- History displays saved conversations; New Chat starts blank without deleting them.
- A completed scenario conversation reopened from History after its Supabase load and accepted a structural completion follow-up.
- Reopen took about 2.5 seconds in this local session. This is functional but remains a UX optimization opportunity.

## J. Remaining blockers and limitations

These are the remaining real limitations; none was hidden to improve the verdict:

1. **Provider domains:** no configured earnings calendar, forward macro release calendar, or structured catalyst adapter currently populates `market_events`. Private-beta users must see these categories as missing.
2. **ETF look-through:** 33.9% of portfolio weight has fund-level identity but no stored look-through. Issuer-sector concentration is therefore not full economic look-through.
3. **User-owned context:** saved theses/breakers, tax lots, custom risk budget, and a trading-cost model are absent. Personal thesis and tax-aware claims remain unavailable.
4. **Remote DB variance:** normal warm latency meets the target, but one request experienced a 4.2-second DB spike and rendered in 6.306 seconds. The immediate repeat was normal. Production monitoring should retain the query/phase telemetry.
5. **Optimizer usefulness:** the result is feasible and compatible, but expected turnover is high (70.31%) and costs/taxes are unavailable. It is research output, not an execution instruction.
6. **Deployment proof:** all evidence here is local + real Supabase. Scheduler heartbeats, staging topology, multi-user production isolation, and provider cadence still require their separate deployment gate. No deployment was authorized or performed.

## Verification

- Backend: **643 passed, 9 skipped** (`pytest -q`)
- Frontend contracts: **82 passed** (`node --test tests/*.test.mjs`)
- TypeScript: **passed** (`npm run typecheck`)
- Production build: **passed** (`npm run build`); one non-blocking bundle-size warning
- Focused Ask/jobs/read-model/data-health suite before full run: **159 passed**
- Browser: exact 15 questions entered through the signed-in visible UI; targeted exact retests for questions 3 and 8 after final fixes
- Duplicate DB signatures: **0 across all 15**
- Excluded-position leakage: **0**
- Misleading answers: **0**
- Deployment/migrations: **not performed**

## K. Verdict

ASK READY FOR PRIVATE BETA
