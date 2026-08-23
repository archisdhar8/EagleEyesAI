# EagleEyes Phase 6 — Unified Domain Analytics

Date: 2026-08-22

## A. Unified domain architecture

```text
provider / user data
        ↓
versioned datasets and immutable observations
        ↓
out-of-request capability builders
        ↓
company / macro / market / prediction read models
        ↓
bounded deterministic Ask DAG (fast reads only)
        ↓
canonical AnalysisResult
        ↓
deterministic capability renderer
        ↓
optional Gemini presentation
```

Phase 6 extends the existing `capability_read_models` and `analytical_dataset_versions` stores. Domain models use narrow scopes such as `company:MSFT`, `global:macro_state`, `global:market_state`, and `portfolio:<id>`. Builders consume stored provider observations and run outside Ask. Deep company research remains a Phase 5 durable job.

## B. New read models

| Read model | Schema | Calculation | Required dependencies | Optional dependencies | Freshness / coverage / fingerprint |
|---|---|---|---|---|---|
| `company_analysis` | `1` | `company-analysis-v1` | prices, fundamentals, security metadata | earnings, news, score model, thesis state | Required-input freshness; domain coverage and missing fields; fingerprint is stable over type+ticker |
| `macro_state` | `1` | `macro-state-v1` | macro observations | regime labels, macro calendar | Oldest/newest observed series date; five-factor coverage; fingerprint is stable over global macro scope |
| `market_state` | `1` | `market-state-v1` | market prices | volatility, breadth, sector data | Oldest/newest stored bar; indicator coverage; fingerprint is stable over global market scope |
| `prediction_market_state` | `1` | `prediction-market-state-v1` | prediction-market observations | calibration, portfolio mappings | Venue observation times; probability/mapping quality; fingerprint is stable over global or portfolio scope |
| historical projection | existing append-only read-model history | `historical-comparison-v1` | current and selected prior compatible model | genuine review timestamp where requested | Explicit `BaselineReference`; schema/calculation compatibility must pass before a delta is computed |

All models store upstream versions, calculated time, effective-through time, coverage/quality, calculation version, schema version, builder version, and input fingerprint. The generated additive index migration is `202608220004_phase6_domain_read_model_indexes.sql`; it was not applied.

## C. Company architecture

Fast company analysis is a compact derived projection: identity/classification, price/performance, fundamental state and trend, profitability, balance sheet, valuation, momentum, structured earnings, news state, EagleEyes score/components, optional thesis state, quality, freshness, and lineage. It deliberately excludes raw price bars, filings, and article collections.

`COMPANY_RESEARCH_BUILD` remains the deep path. On completion, the worker materializes only the requested ticker's fast model. A running deep job does not hide the last compatible fast model.

Company comparison loads compatible company models concurrently, then creates a typed `CompanyComparisonResult`. Portfolio fit is optional. Missing news or fit makes the result partial without discarding growth, profitability, valuation, balance-sheet, momentum, or earnings fields. Funds/ETFs are explicitly marked ineligible for issuer-fundamental methodology.

## D. Macro architecture

`MacroStateResult` contains observed rates, inflation, growth, labor, liquidity/credit, factor evidence, deterministic regime labels, material changes, risks, quality, freshness, and lineage. `observed_state.type` is `OBSERVED`; forecast is a separate, null field in this capability.

Materiality uses series-specific deterministic thresholds. Portfolio macro exposure composes the macro model with saved holdings and the compatible portfolio risk model. It reports mapped holdings and mapped weight, never an unstated loss estimate.

## E. Market-state architecture

`MarketStateResult` uses only stored broad-index and sector-price inputs already supported by EagleEyes. It derives broad trend, realized-volatility state, breadth, sector leadership, risk-on/risk-off state, a categorical regime, material state changes, and quality. Missing breadth or volatility yields a partial model rather than total failure.

Market state remains distinct from macro state. Portfolio fit is a descriptive match/mismatch enrichment based on current holdings and leadership; it is not a return forecast.

## F. Prediction markets

`PredictionMarketResult` preserves provider markets independently. Probability values retain one of `MARKET_IMPLIED`, `MODEL`, `USER_DEFINED`, or `COMPOSITE`; venue observations default only to `MARKET_IMPLIED`. No provider disagreement is silently aggregated.

Changes use percentage points, not relative-percent language. Each market can expose current/previous probability, delta, observation time, provider, quality, status, direct/factor mappings, mapped holdings, mapped portfolio weight, mapping methodology/confidence, and relevance. Calibration and liquidity remain unavailable when unsupported. Market-implied odds are labeled evidence, never truth.

## G. Historical/change architecture

`BaselineReference` records baseline id/time, calculation version, schema version, fingerprint, compatibility, selection, and incompatibility reason. `HistoricalComparison` distinguishes:

- `NO_BASELINE`
- `NO_MATERIAL_CHANGE`
- `MATERIAL_CHANGE`
- `INCOMPATIBLE_BASELINE`

`last_review` resolves only genuine thesis-review or saved-decision timestamps. It never substitutes a model snapshot. One-week/one-month selection chooses the latest compatible model at or before the requested time. Version mismatch blocks deltas.

Every future company materialization persists score/component state, so score attribution begins accumulating now without fabricated retroactive history. Existing portfolio read models and health snapshots remain capability-level portfolio history; Phase 6 does not duplicate one giant portfolio payload.

## H. Old normal-Ask paths removed

Removed from normal Ask routing:

- synchronous `security_research()` for company comparison
- synchronous `security_research()` for holdings research ranking
- synchronous structured earnings assembly for ordinary company earnings questions
- synchronous `forecasting.build_intelligence()` for prediction questions
- raw evidence-bundle reconstruction for known historical-change questions
- forecast+thesis over-fetch for prediction questions
- score-derived SPY outperformance claims when no compatible benchmark model exists

Known company, comparison, macro, market, prediction, and historical questions now load versioned models. Generic stored evidence remains only for genuinely general questions until Phase 7. Explicit Research/Today/provider endpoints still own their page-specific stored-data or provider workflows; they are not executed by the Phase 6 Ask routes. Explicit deep research still queues the durable Phase 5 job.

## I. Tests

Phase 6 adds 31 focused tests covering:

- company analysis, valuation/trend/score, stale prices, missing news, funds, and deep-job coexistence
- concurrent company comparison, optional portfolio fit, full-data preservation, and the MSFT/AMZN regression
- complete/partial/stale macro state, deterministic changes, regime handling, forecast separation, and portfolio exposure
- normal/partial market state, leadership, volatility, breadth, regime change, and portfolio fit
- prediction probability types, percentage-point deltas, provider disagreement, stale/closed/disappeared markets, calibration, and portfolio mapping
- no baseline vs no material change vs material change vs incompatible methodology
- normal Ask read-only behavior with live builders patched to fail

Final full backend result: **541 passed, 9 skipped, 2 warnings, 0 failed**. The warnings are the existing Starlette/httpx deprecation and pandas future behavior warning.

## J. Phase 6 acceptance suite

Artifact: `artifacts/phase6-acceptance.json`

Twenty representative questions cover company, comparison, macro, market, prediction markets, portfolio compositions, and history. Results:

- 14 SUCCESS
- 4 PARTIAL (company answers disclosed optional thesis/coverage limitations)
- 2 UNAVAILABLE (no genuine AMZN review baseline; no month-old macro projection)
- 20/20 deterministic answers
- 20/20 quality verdict PASS

Each record includes capability, dependencies, status, coverage, freshness, local latency, deterministic answer, and quality verdict.

## K. Ask-15 regression

Artifacts:

- `artifacts/ask-15-phase6-gemini-disabled.json`
- `artifacts/ask-15-phase6-gemini-disabled.md`

Phase 5 → Phase 6 is unchanged:

| Status | Phase 5 | Phase 6 |
|---|---:|---:|
| SUCCESS | 6 | 6 |
| PARTIAL | 4 | 4 |
| UNAVAILABLE | 5 | 5 |
| FAILED | 0 | 0 |

Phase 6 also retained 15/15 deterministic answers, 15/15 persistence success, 15/15 CURRENT models, 15/15 fingerprint matches, and zero legacy adapters.

## L. Performance

Artifact: `artifacts/phase6-read-model-benchmark.json`

Local SQLite synthetic materialized-model benchmark (100 samples each):

| Capability | Median | p95 |
|---|---:|---:|
| company analysis | 0.7547 ms | 1.0892 ms |
| two-company comparison | 1.9555 ms | 2.5248 ms |
| macro state | 0.6494 ms | 0.7845 ms |
| market state | 0.6328 ms | 0.7985 ms |
| prediction-market state | 0.6241 ms | 0.7617 ms |
| mixed three-capability concurrent boundary | 5.0772 ms | 5.3580 ms |

These are local read-boundary measurements, not production SLOs; network, authentication, and remote-database latency are excluded.

## M. Remaining gaps

- tax lots remain incomplete for actionable tax-aware rebalancing
- no validated trading-cost model
- no supported cash/risk-free yield source
- saved thesis/review coverage is incomplete across companies
- historical baselines begin only when compatible models are persisted; no history was fabricated
- event, earnings-consensus, guidance, estimate-revision, macro-calendar, and company-catalyst coverage remains incomplete
- issuer fundamentals remain inappropriate or missing for funds
- comparable multi-period fundamentals and broader peer histories remain incomplete
- market breadth and valuation series are limited to existing stored inputs
- prediction-market calibration/liquidity and event-to-portfolio mappings remain incomplete
- survivorship/security-master history remains insufficient for stronger backtests

## N. Phase 7 handoff

Phase 7 should build the general compositional financial query planner on the stable typed capability registry. It should select and compose these canonical results without granting Gemini calculation authority or reintroducing live analytical work into Ask. Phase 7 was not started.

## O. Verdict

Company analysis/comparison now uses versioned fast models; macro, market, and prediction states are typed and deterministic; compatible historical baseline semantics exist; portfolio compositions distinguish exposure from impact; deterministic answers work without Gemini; normal known-domain Ask paths do not run broad live analytical builds; and Phase 5 remains green.

PHASE 6 COMPLETE
