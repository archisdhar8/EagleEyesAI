# EagleEyes Phase 4 — analytical semantics report

Date: 2026-08-22

## Verdict

Phase 4 replaces ambiguous factor labels with deterministic, versioned decision methodologies in the real capability/read-model/Ask path. It deliberately reduces several technical SUCCESS results where the old result overstated what the evidence supported.

Final Gemini-disabled Ask-15: **6 SUCCESS, 4 PARTIAL, 5 UNAVAILABLE, 0 FAILED**. All 15 answers are deterministic, use CURRENT read models, match the request fingerprint, persist successfully, and use zero legacy adapters.

Nothing was deployed, committed, or pushed.

## Gap matrix

| # | Question/capability | Phase 3 | Root analytical gap | Phase 4 implementation | Phase 4 | Remaining limitation |
|---:|---|---|---|---|---|---|
| 1 | Strongest opportunities / OPPORTUNITY_RANKING | SUCCESS | Holding health was mislabeled as opportunity; no raw eligibility gates | `OpportunityCandidate`, reported trend, raw-history eligibility, portfolio fit, opposing evidence | PARTIAL | Only 3 of 26 raw-history candidates passed every output field; this is not a return forecast |
| 2 | Weakest thesis and replacement / THESIS_REPLACEMENT | UNAVAILABLE | No saved thesis and no incumbent/candidate dominance contract | Typed replacement comparison with factor/risk/fit deltas and no-forced-replacement state | UNAVAILABLE | Portfolio has no saved thesis, so no weakest-thesis claim is possible |
| 3 | Material change / PORTFOLIO_CHANGE | UNAVAILABLE | No compatible previous baseline; no materiality state | Typed `ChangeSet`, thresholds, explicit `NO_BASELINE` versus `NO_MATERIAL_CHANGE` | UNAVAILABLE | No compatible prior snapshot exists |
| 4 | Overvalued relative to growth/fundamentals / VALUATION_RANKING | SUCCESS | Low valuation score was treated as relative overvaluation | Observed-multiple burden minus EPS-growth and quality support; peers only with sufficient sector rows | PARTIAL | 19/57 holdings have all required inputs; intrinsic value is not estimated |
| 5 | Hidden concentration / HIDDEN_RISK | SUCCESS | Existing methodology already supported position, sector, correlation, and dependency risk | Preserved existing verified capability | SUCCESS | ETF look-through remains limited |
| 6 | Rates/recession/AI slowdown / MULTI_SCENARIO | PARTIAL | AI-capex factor unsupported; irrelevant optimizer failure contaminated scenario result | Exact factor registry; rates/recession simulation plus separately labeled AI dependency stress; current-path outcome | SUCCESS | AI mapping provides exposure, not loss magnitude |
| 7 | Watchlist risk-adjusted case / WATCHLIST_COMPARISON | SUCCESS | Raw watchlist factor ordering was not risk adjusted | Defined evidence/risk composite, volatility, portfolio correlation, incremental sector fit, dominance states | SUCCESS | No new watchlist position proves dominance in the current fixture |
| 8 | Upcoming material events / PORTFOLIO_EVENTS | PARTIAL | Category completeness and portfolio materiality absent | Typed events, future-date filter, affected weight, category, materiality, freshness, category completeness | PARTIAL | Earnings, macro, and company-catalyst calendars are missing/incomplete |
| 9 | Ranking trust / DATA_QUALITY | SUCCESS | Symbol presence could look like complete data | HIGH/MEDIUM/LOW/NOT_RANKABLE from raw history, freshness, provider quality, placeholders, lineage | SUCCESS | Many funds lack issuer-style fundamental history and are correctly not rankable by this stock methodology |
| 10 | Score attribution / SCORE_ATTRIBUTION | UNAVAILABLE | No comparable prior component baseline | Weighted component impacts, method-version separation, reconciliation tolerance, unexplained delta | UNAVAILABLE | Current fixture has no comparable component-level baseline |
| 11 | Thesis invalidation / THESIS_INVALIDATION | UNAVAILABLE | No saved theses; generic risks could be mistaken for personalized breakers | Largest-position results use only saved assumptions/breakers and expose missing thesis explicitly | UNAVAILABLE | No saved theses exist |
| 12 | Tax/cost-aware rebalance / PORTFOLIO_ANALYSIS | UNAVAILABLE | Fingerprint, feasibility, costs, tax lots, and actionability were not explicit | `RebalanceDecision` with fingerprint/feasibility/turnover/cost/tax gates; attempted weights withheld | UNAVAILABLE | Cached optimizer is incompatible; tax lots and trading-cost model are absent |
| 13 | Improving fundamentals/value/momentum / MULTIFACTOR_SCREEN | SUCCESS | High current fundamentals were mislabeled as improving | Multi-period reported trend with minimum history; valuation ≥45 and momentum ≥55 gates | SUCCESS | Only SBUX passes in the fixture; sequential periods may still contain seasonality |
| 14 | Countercase / RECOMMENDATION_COUNTERCASE | SUCCESS | No stable recommendation identity; warnings were generic | Stable fingerprinted recommendation ID plus candidate-specific factor, risk, and dependency counterevidence | SUCCESS | Unknowns remain limited by current stored mapping coverage |
| 15 | New cash versus cash / CASH_ALLOCATION | SUCCESS | No cash alternative/hurdle; deployment was implicitly favored | Explicit sourced cash hurdle, `HOLD_CASH`/`NO_CLEAR_EDGE` states, no forced sizing | PARTIAL | No supported cash/risk-free yield is stored, so superiority to cash cannot be claimed |

## Capability semantics

### Opportunity (`opportunity-v2`)

Claim: identifies holdings with the strongest current evidence-backed setup. It combines fundamental quality (25%), measured fundamental trend (20%), observed valuation support (20%), momentum (15%), balance-sheet quality (10%), and incremental portfolio fit (10%). It does **not** estimate expected return or probability of outperformance.

Required inputs: three or more fundamental periods; acceptable provider quality; at least 126 daily price observations; current price evidence; fundamental, valuation, and momentum factors; balance-sheet inputs. Eligibility fails explicitly when any critical gate is missing or a default-shaped factor lacks raw support. Confidence means evidence completeness/reliability, never probability.

PARTIAL: rankable subset exists but coverage/freshness is incomplete. UNAVAILABLE: no holding is eligible or the read model is incompatible.

### Fundamental trend (`reported-period-trend-v2`)

Claim: describes direction of reported fundamentals across at least three stored periods. Signals include acceleration/deceleration in revenue, diluted EPS and free cash flow plus change in operating margin, FCF margin, and debt/assets. At least two signals are required. Direction thresholds are ±8 composite points.

It does **not** infer improvement from a high current score. Missing history produces `UNAVAILABLE`, not neutral. The method reports periods and metric-level support; three sequential periods can retain seasonality, which is a disclosed limitation.

### Relative valuation (`relative-valuation-v2`)

Claim: ranks observed valuation burden after accounting for stored EPS growth and fundamental quality. Valuation burden uses available P/E, price-to-sales, and FCF yield; the gap subtracts 55% growth support and 45% quality support. Sector context appears only with at least two other eligible stored peers.

It does **not** estimate intrinsic value, invent peers, or declare a high-P/E security overvalued solely because its P/E is high. Missing observed multiples/growth/history produces PARTIAL or exclusion.

### Replacement (`replacement-v2`)

Claim: first identifies a saved-thesis incumbent, then tests a non-owned candidate on a comparable evidence/risk composite, fundamental/valuation/momentum deltas, volatility delta, data-quality delta, and before/after sector concentration. `REPLACEMENT_SUPPORTED` requires dominance in at least three of four observed dimensions and no worsened concentration.

It does **not** force a swap, treat an owned security as `NEW_POSITION`, or call the highest watchlist score a replacement. Other states are `ADD_TO_EXISTING_SUPPORTED`, `NO_CLEAR_REPLACEMENT`, and `INSUFFICIENT_DATA`/unavailable.

### Watchlist dominance (`watchlist-dominance-v2`)

Claim: compares candidates with the weakest incumbent comparison set using fundamentals (25%), valuation (20%), momentum (20%), evidence confidence (15%), and observed volatility risk (20%), then checks portfolio correlation and incremental sector concentration. It is a defined decision composite—not a Sharpe ratio or calibrated outperformance probability.

Dominance requires a five-point evidence/risk edge and no worsened incremental concentration. A valid result may correctly conclude that no new candidate dominates.

### Cash allocation (`cash-allocation-v2`)

Claim: invests only when a sourced cash hurdle exists and eligible candidates clear the defined evidence/risk/fit comparison. Supported states are `INVEST`, `PARTIAL_DEPLOYMENT`, `HOLD_CASH`, and `NO_CLEAR_EDGE`.

No cash yield is fabricated. Without a stored/user-supported hurdle, the result is PARTIAL, recommends no sizing, and cannot claim investing is superior to cash. Taxes, expected returns, and transaction costs are not inferred.

### Incremental portfolio fit

New-cash proposals calculate normalized sector weight before and after a hypothetical allocation and observed candidate correlation with weighted portfolio returns. Replacement proposals remove the incumbent weight before adding the candidate. The result explicitly labels concentration as `IMPROVES`, `NEUTRAL`, or `WORSENS`. It does not treat standalone company quality as sufficient portfolio fit.

### Score attribution (`score-attribution-v2`)

Claim: compares current and compatible historical score inputs, weights factor deltas under the recorded health methodology, ranks component impacts, and reports unexplained residual. Methodology-version changes are recorded separately and make direct score reconciliation non-comparable.

Required: baseline timestamp, compatible calculation version, component changes, and total delta. A residual over 0.5 score points fails verification. No baseline means precise UNAVAILABLE.

### Change materiality (`portfolio-change-v2`)

Claim: reports only changes crossing disclosed thresholds: two health-score points, five factor points, or one percentage point of weight/risk where applicable. The result distinguishes `NO_BASELINE`, `NO_MATERIAL_CHANGE`, and `MATERIAL_CHANGE`.

It does not interpret missing history as “nothing changed.”

### Countercase (`countercase-v2`)

Claim: challenges a stable leading eligible opportunity identified by recommendation ID, input fingerprint, source calculation version, ticker, and timestamp. Evidence categories include valuation weakness, measured risk contribution, economic dependencies, concentration, and unresolved missing fields.

It does not repeat unrelated generic warnings or invent a recommendation when none is eligible.

### Scenario compatibility (`scenario-compatibility-v2`)

Each requested factor maps independently through a registry. Rates up and recession use the cached empirical block-bootstrap scenario; AI-capex slowdown uses `AI_INFRASTRUCTURE_DEMAND` dependency exposure and explicitly claims no simulated loss magnitude. The deterministic answer reports the current-path median real wealth, probability of loss, adverse drawdown percentile, and AI-mapped portfolio weight.

SUCCESS requires every requested factor to have an exact compatible method. Unlike methods remain labeled rather than blended into fake precision.

### Events (`portfolio-events-v2`)

Claim: returns future events typed as earnings, macro, company catalyst, thesis review, or prediction-market event, with affected holdings/weight, materiality, source freshness, and evidence confidence. Expired events are excluded. Completeness is independent for earnings, macro, company catalysts, and prediction markets.

An event list cannot claim calendar completeness when a required category is absent.

### Data quality (`data-quality-v2`)

Trust classifications derive from raw factor presence, at least three fundamental periods, fundamental and price freshness, at least 126 prices, provider quality, placeholder detection, trend sufficiency, and lineage. `NOT_RANKABLE` means the stock-oriented ranking methodology lacks prerequisites; it does not mean the security itself is poor.

### Rebalance actionability (`rebalance-actionability-v2`)

An actionable result requires current input fingerprint match, a Balanced compatible alternative, feasible constraints, explicit turnover, and no withheld attempted solution. Trading-cost estimates appear only with a stored cost model. `tax_aware=true` requires actual tax lots; aggregate cost basis is not treated as lot-level tax data.

The current result remains UNAVAILABLE and withholds targets/trades because the optimizer fingerprint and feasibility do not pass. It also explicitly reports missing tax lots and cost model.

## Read-model changes

Schema version remains `1`; calculation and builder versions carry the methodology change. Builder version is now `ask-read-model-builder-v2`.

| Read model | Old calculation | New calculation | Important new fields | Dependency change |
|---|---|---|---|---|
| portfolio_opportunity | portfolio-opportunity-read-v1 | portfolio-opportunity-read-v2 | opportunity candidates, eligibility gates, trend, balance sheet, fit, opposing evidence | Existing holdings/prices/fundamentals/classification/theses |
| portfolio_risk | portfolio-risk-read-v1 | portfolio-risk-read-v2 | stable countercase and recommendation identity | Existing theme/thesis dependencies |
| portfolio_change | portfolio-change-read-v1 | portfolio-change-read-v2 | typed change set, baseline state, thresholds | Existing optional health history |
| portfolio_factor_state | portfolio-factor-state-read-v1 | portfolio-factor-state-read-v2 | fundamental trends, relative valuation, improving screen | Existing prices/fundamentals |
| watchlist_comparison | watchlist-comparison-read-v1 | watchlist-comparison-read-v2 | dominance results, replacement comparisons, cash hurdle result, before/after fit | Existing profile/prices/fundamentals/theses |
| portfolio_events | portfolio-events-read-v1 | portfolio-events-read-v2 | typed future events, affected weight/materiality, category completeness | Existing optional earnings/macro/catalysts |
| portfolio_data_quality | portfolio-data-quality-read-v1 | portfolio-data-quality-read-v2 | trust classifications and raw eligibility | Existing provider state |
| score_attribution | score-attribution-read-v1 | score-attribution-read-v2 | previous/current score, weighted deltas, methodology change, unexplained delta | Existing optional health history |
| thesis_status | thesis-status-read-v1 | thesis-status-read-v2 | per-largest-position explicit breakers and missing thesis | Existing theses/monitor |
| portfolio_scenario | portfolio-scenario-read-v1 | portfolio-scenario-read-v2 | factor registry, empirical/qualitative support types, AI mapped weight | Added optional `theme_mappings` |
| optimizer_compatibility | optimizer-compatibility-read-v1 | optimizer-compatibility-read-v2 | actionable rebalance, feasibility, fingerprint, cost/tax/turnover contract | Existing optional tax lots |

Old append-only results remain interpretable by their calculation version. Phase 4 loaders require the v2 calculation version and therefore do not silently reinterpret v1 rows.

## Verification changes

- Opportunity: every ranked row must be eligible and have an opportunity score.
- Relative valuation: eligible raw inputs and computed relative gap are required.
- Fundamental screen: every returned row must have measured `IMPROVING` trend.
- Watchlist: risk-adjusted dominance computation must exist.
- Replacement: a recommendation requires explicit replacement dominance.
- Cash: a sourced cash hurdle is mandatory for an invest-over-cash claim.
- Attribution: compatible baseline and component reconciliation within 0.5 points.
- Events: category completeness is separately verified and disclosed.
- Data quality: every holding must receive a valid deterministic trust class.
- Rebalance: fingerprint match, feasibility/actionability, and correct tax labeling.
- Scenario: all requested factors must remain present and method-compatible.
- Low screen coverage yields PARTIAL rather than technical failure; low coverage still blocks unsupported whole-portfolio conclusions.

Execution status remains separate from analytical verification. No Gemini step determines any result.

## Tests

Phase 4 focused tests: **30 passed**. These directly route all 15 acceptance questions and test opportunity eligibility, declining-vs-improving trend, relative valuation/growth support, replacement typing/dominance, cash hold/no-edge behavior, before/after fit, scenario factor exactness, events, trust classification, attribution reconciliation, thesis prerequisites, countercase identity, and rebalance tax/fingerprint gates.

Full backend suite: **477 passed, 9 skipped, 0 failed**. Two existing warnings remain: Starlette/httpx deprecation and pandas future concat behavior.

## Ask-15 result comparison

| # | Capability | Phase 3 | Phase 4 | What changed |
|---:|---|---|---|---|
| 1 | OPPORTUNITY_RANKING | SUCCESS | PARTIAL | Real opportunity model and eligibility reveal low eligible coverage |
| 2 | THESIS_REPLACEMENT | UNAVAILABLE | UNAVAILABLE | Exact saved-thesis prerequisite plus real dominance path |
| 3 | PORTFOLIO_CHANGE | UNAVAILABLE | UNAVAILABLE | Exact `NO_BASELINE` state and materiality model |
| 4 | VALUATION_RANKING | SUCCESS | PARTIAL | Raw relative-value methodology reveals 19/57 coverage |
| 5 | HIDDEN_RISK | SUCCESS | SUCCESS | Existing valid method preserved |
| 6 | MULTI_SCENARIO | PARTIAL | SUCCESS | AI factor supported through explicitly qualitative dependency mapping |
| 7 | WATCHLIST_COMPARISON | SUCCESS | SUCCESS | Real risk/fit dominance; result correctly says no new candidate dominates |
| 8 | PORTFOLIO_EVENTS | PARTIAL | PARTIAL | Typed material events; missing categories remain explicit |
| 9 | DATA_QUALITY | SUCCESS | SUCCESS | Real rankability/trust states replace symbol-presence coverage |
| 10 | SCORE_ATTRIBUTION | UNAVAILABLE | UNAVAILABLE | Real attribution path; comparable baseline still absent |
| 11 | THESIS_INVALIDATION | UNAVAILABLE | UNAVAILABLE | Explicit saved-breaker contract; thesis still absent |
| 12 | PORTFOLIO_ANALYSIS | UNAVAILABLE | UNAVAILABLE | Strong actionability contract exposes incompatible optimizer/cost/tax gaps |
| 13 | MULTIFACTOR_SCREEN | SUCCESS | SUCCESS | “Improving” now requires trend; only SBUX passes |
| 14 | RECOMMENDATION_COUNTERCASE | SUCCESS | SUCCESS | Stable recommendation identity and specific counterevidence |
| 15 | CASH_ALLOCATION | SUCCESS | PARTIAL | No sourced cash hurdle; result correctly says `NO CLEAR EDGE` |

The status count declines from 8 SUCCESS to 6 because three previously overbroad claims are now correctly PARTIAL, while exact scenario support improves one PARTIAL to SUCCESS. No scoring or verification threshold was weakened to improve counts.

Detailed deterministic answers and contracts are linked in `artifacts/ask-15-phase4-gemini-disabled.md` and `.json`.

## Manual quality review

| # | Review | Reason |
|---:|---|---|
| 1 | PARTIAL | Answers with three real setups and opposing evidence, but only 11.5% of rankable candidates have complete output fields |
| 2 | NOT_USEFUL | Correctly safe, but no saved thesis means the requested replacement decision cannot be made |
| 3 | NOT_USEFUL | Correctly identifies missing baseline; no actual change comparison is possible |
| 4 | PARTIAL | Useful relative-value ranking for 19 holdings, with explicit non-intrinsic-value and peer limits |
| 5 | USEFUL | Direct concentration, cluster, economic dependency, risk contributor, and coverage answer |
| 6 | USEFUL | Reports empirical current-path outcomes and separately labeled AI exposure without fake precision |
| 7 | USEFUL | Directly concludes no new watchlist candidate proves dominance and explains each fit/risk result |
| 8 | PARTIAL | Future events are materiality-ranked, but only prediction-market coverage exists |
| 9 | USEFUL | Clearly identifies NOT_RANKABLE holdings and exact missing eligibility prerequisites |
| 10 | NOT_USEFUL | Correct prerequisite response, but no attribution can be produced without history |
| 11 | NOT_USEFUL | Correctly refuses invented breakers; no personalized invalidation analysis is possible |
| 12 | NOT_USEFUL | Correct actionability refusal, but no compatible rebalance can be supplied |
| 13 | USEFUL | Directly identifies the sole company passing actual improvement/value/momentum gates |
| 14 | USEFUL | Stable MSFT recommendation identity and specific valuation/risk/AI counterarguments |
| 15 | PARTIAL | Correct `NO CLEAR EDGE` and no forced deployment, but cash comparison cannot complete without a hurdle |

## Remaining missing prerequisites

- A supported cash or risk-free yield source/configuration.
- Saved investment theses and explicit breakers for the selected portfolio.
- Compatible prior portfolio and score-component snapshots.
- A current-fingerprint feasible optimizer result.
- Lot-level acquisition/cost-basis data for tax-aware optimization.
- A stored trading-cost model for precise implementation cost claims.
- Complete earnings, macro, and company-catalyst calendars.
- Raw issuer fundamentals for funds/ETFs where the stock methodology is inappropriate.
- Better seasonally comparable fundamental history for higher-confidence trend claims.
- Broader peer coverage for sector-relative valuation.

## Phase 5 handoff

Phase 5 should own durable simulation refreshes, optimizer computation, backtests, broad company-research rebuilds, and qualitative thesis monitoring. Those heavy/non-cancellable operations were not added to synchronous Ask. Phase 4 only materializes and verifies their compatible completed results.
