# Ask EagleEyes — bounded correctness repair

Date: 2026-08-28  
Environment: signed-in local browser at `http://localhost:3001/ask`, using the existing Supabase data through its session pooler  
Deployment: not performed  
Refreshes/providers/migrations: none

## Gate result

- USEFUL: 21
- PARTIAL_BUT_USEFUL: 14
- NOT_USEFUL: 0
- MISLEADING: 0
- Status-only visible answers: 0
- Contradictory downside labels: 0
- Expired upcoming events: 0
- Routing gaps in the four repaired families: 0
- Browser messages with `answer_validation.substantive=true`: 34/34 typed-answer messages; Q35 is a verified dashboard action and does not use the typed-answer contract.
- Jobs started: 0
- Bounded fallback used in this run: 0 (the guard remained armed but no repaired answer needed it).

Stored user-to-assistant latency was 357–3,189 ms, median 458 ms. The browser-visible chart action completed in 4,019 ms including rendering.

## Root causes for the ten prior insufficient answers

| Q | Prior failure | Root cause | Repair and observed result |
|---:|---|---|---|
| 1 | Unsupported capability | Opportunity wording missed the existing `OPPORTUNITY_RANKING` direct route and fell into generic composition. | Added semantic aliases; routed only to `portfolio_overview`. Browser returned MSFT, SBUX, and QCOM with scores, factors, concerns, confidence, method, and as-of date. |
| 3 | Visible `SUCCESS` | The component summarizer treated status as content even though `portfolio_change` had a typed result. | Status text is no longer a summary. The answer contract rejects enum-only output. Browser stated that a compatible baseline exists and no disclosed threshold was crossed. |
| 4 | Both capabilities reported failed | The exact valuation wording missed the direct route, so the generic planner unnecessarily required both `valuation_ranking` and `portfolio_risk`. The stored legacy trace proves both nodes actually completed (`valuation_ranking` PARTIAL and `portfolio_risk` SUCCESS), but composition/verification collapsed them into a FAILED answer. This was not a database, calculation, or stale-read-model failure. | Direct route now calls only `valuation_ranking`; composition also preserves any successful sibling if another component fails. Live trace: node SUCCESS, read model CURRENT, fingerprint match true, schema `1`, calculation `relative-valuation-v2`. Browser returned 19 eligible valuation rows led by QCOM, DLR, and WMT. |
| 6 | Unsupported capability | Macro wording did not consistently select the existing multi-factor scenario route; several factor paraphrases were absent. | Added rate, recession/growth, AI-capex, and hyperscaler variants. Parser preserved all three requested factors. Browser explicitly separated empirical rate/growth simulation from qualitative AI-capex exposure. |
| 8 | Status-only answer | Broad event wording used generic composition and leaked component status instead of typed events. | Added direct event aliases and the answer contract. Browser returned three future Aug. 31 events plus explicit missing-category health. |
| 9 | Unsupported capability | Reliability wording was not mapped to `DATA_QUALITY`. | Added reliability, missing-data, trust, and completeness variants. Browser returned 57/57 price, 37/57 fundamental, 57/57 momentum, and 34/57 rankability coverage with per-holding missing fields. |
| 12 | Status-only answer | “Lower-risk version” did not reliably use the existing portfolio-analysis route, and composition preferred status prose. | Added direct portfolio-analysis language and enum rejection. Browser returned feasibility, turnover, target changes, and missing tax/cost limitations. |
| 14 | Unsupported capability | Counterargument/bear-case paraphrases were absent from the direct countercase route. | Added semantic variants. Browser returned the MSFT recommendation countercase with valuation, risk-contribution, and AI-dependency evidence. |
| 21 | Apparently contradictory metrics | `probability_of_loss` and a signed drawdown percentile were rendered under generic “loss/downside” labels. | Introduced explicit terminal-return and path-drawdown names and labels. Browser stated 0.0% probability of ending below start and a -40.3% 10th-percentile signed maximum-drawdown result, then explained why they can coexist. |
| 31 | Expired events called upcoming | Selection used date-level filtering and the cached event read model could retain expired rows; closed/resolved state was not a complete boundary. | Capability/read-model selection now uses strict instants, local end-of-day for date-only rows, canonical timezone conversion, and closed/resolved exclusion. Browser showed only Aug. 31 events; no Aug. 26 row survived. |

## Routing repair

The direct router now covers semantic variants for:

- Opportunity: best/strongest opportunities, best ideas, attractive holdings, current setups.
- Scenario: rates stay high/higher rates, recession or weaker growth, AI spending/capex slowdown, hyperscaler slowdown.
- Data quality: reliability, missing data, trust in rankings, evidence completeness.
- Countercase: strongest argument/counterargument, bear case, recommendation wrong, challenge recommendation.

Existing precedence and capability boundaries are preserved. No new planner capability or duplicate ranking/scenario engine was added.

## Composition and validation repair

`_component_summary` no longer treats `SUCCESS`, `PARTIAL`, or `UNAVAILABLE` as substantive content. `AnswerValidation` records:

```text
substantive
status_only
contradictory_labels
expired_items
missing_required_claims
```

Before persistence/rendering, typed answers must be non-empty, non-status-only, free of contradictory downside labels and expired events, and contain an intent-relevant claim. If validation fails, one deterministic, non-recursive pass renders successful typed component data and names only the unavailable portion. A failed sibling can no longer erase a successful component.

Failed required capabilities now retain `failing_node`, exception class, input fingerprint, read-model type/state, schema version, calculation version, and query/calculation stage. The prior Q4 record had no exception because its nodes succeeded; the failure occurred in result composition/verification.

## Downside semantics

| Before | After |
|---|---|
| `probability_of_loss` | `terminal_loss_probability`: probability terminal value is below starting value. |
| Generic terminal downside percentile | `terminal_return_p05` / `terminal_return_percentiles`: percentile of terminal return distribution. |
| Generic `drawdown`/`downside` | `simulated_max_drawdown_p95`: adverse percentile of maximum simulated peak-to-trough path drawdown; always non-positive. |
| Historical and simulated drawdown could be conflated | `historical_max_drawdown` is separate and never labeled as simulation output. |
| Threshold risk implicit/ambiguous | `drawdown_breach_probability` is separate and remains unavailable unless actually computed. |

The existing cached legacy simulation was not recomputed. Its old `p10` signed maximum-drawdown field is rendered with that exact definition instead of being relabeled as terminal loss or a 95th percentile.

## Event/time policy

- Precise events: `event_time > current_time` after UTC normalization.
- Date-only events: upcoming through local end-of-day in `timezone_name`; invalid/missing zones fall back to UTC.
- Closed, resolved, settled, cancelled, expired, or ended rows: never upcoming.
- The same policy is enforced in the event capability, database query, cached read-model boundary, and final answer validator.

## 35-question browser matrix

`Status` is the stored capability execution state, not the usefulness grade. Latency is stored user-message to assistant-message time; browser UI added roughly one second of polling/rendering to ordinary answers.

| # | Resolved intent → capability/status | Visible answer (condensed from browser) | Latency | Grade |
|---:|---|---|---:|---|
| 1 | OPPORTUNITY_RANKING → portfolio_overview/PARTIAL | Ranked MSFT 64.1, SBUX 58.2, QCOM 57.5 with drivers, concerns, confidence, methodology. | 1,533 ms | USEFUL |
| 2 | THESIS_REPLACEMENT → thesis_replacement/UNAVAILABLE | Correctly said no personal theses are saved; ranked objective weak setups and supplied a focused thesis follow-up. | 883 ms | PARTIAL_BUT_USEFUL |
| 3 | PORTFOLIO_CHANGE → portfolio_change/SUCCESS | Compatible baseline; no change crossed disclosed materiality thresholds. | 379 ms | USEFUL |
| 4 | VALUATION_RANKING → valuation_ranking/PARTIAL | Ranked eligible valuation burden led by QCOM, DLR, WMT; included growth, quality, peer context, confidence, caveat. | 465 ms | USEFUL |
| 5 | HIDDEN_RISK → portfolio_intelligence/SUCCESS | Capital, sector, correlation-cluster, dependency, risk-contribution, and look-through coverage detail. | 424 ms | USEFUL |
| 6 | MULTI_SCENARIO → portfolio_scenario/SUCCESS | Preserved rates up, AI capex down, growth down; separated simulation from exposure mapping. | 386 ms | USEFUL |
| 7 | WATCHLIST_COMPARISON → watchlist_comparison/SUCCESS | XLE/XLV/VTI showed no clear dominance; SPY/QQQ add-to-existing cases and concentration effects disclosed. | 391 ms | USEFUL |
| 8 | PORTFOLIO_EVENTS → portfolio_events/PARTIAL | Three future Aug. 31 prediction events; earnings/macro/company-calendar gaps explicitly marked missing. | 357 ms | USEFUL |
| 9 | DATA_QUALITY → data_quality/SUCCESS | Field coverage and per-holding missing/rankability details; provider/version remain inspectable in lineage rather than fully summarized. | 404 ms | PARTIAL_BUT_USEFUL |
| 10 | SCORE_ATTRIBUTION → score_attribution/UNAVAILABLE | Correct ticker clarification plus available ticker examples and promised component delta contract. | 454 ms | PARTIAL_BUT_USEFUL |
| 11 | THESIS_INVALIDATION → thesis_monitor/UNAVAILABLE | No saved breakers; showed objective risks for largest positions and one focused next input. | 393 ms | PARTIAL_BUT_USEFUL |
| 12 | PORTFOLIO_ANALYSIS → portfolio_analysis/PARTIAL | Feasible lower-risk rebalance, turnover, largest changes, and missing tax/trading-cost evidence. | 470 ms | USEFUL |
| 13 | MULTIFACTOR_SCREEN → multifactor_screen/SUCCESS | SBUX qualified across improving trend, valuation availability, and positive momentum. | 402 ms | USEFUL |
| 14 | RECOMMENDATION_COUNTERCASE → recommendation_countercase/SUCCESS | MSFT countercase: demanding valuation, 5.2% risk contribution, AI-infrastructure dependency. | 446 ms | USEFUL |
| 15 | CASH_ALLOCATION → cash_allocation/SUCCESS | Partial deployment into SPY/QQQ, 3.86% cash hurdle, sizing limits; stale evidence called out. | 463 ms | PARTIAL_BUT_USEFUL |
| 16 | PORTFOLIO_PERFORMANCE → portfolio_backtest/SUCCESS | Current-weight portfolio 24.6% vs SPY 20.2% and QQQ 25.2%; clearly not realized account performance. | 542 ms | USEFUL |
| 17 | GAIN_LOSS_ATTRIBUTION → portfolio_risk/SUCCESS | Unrealized gain/loss table led by PANW/AVGO/MSFT and NKE/SPHY/CRM, with scope caveat. | 509 ms | USEFUL |
| 18 | RISK_EFFICIENCY → portfolio_risk+portfolio_backtest/SUCCESS | Saved tolerance, same-window return/volatility/drawdown ratios, risk leaders; expected-return optimum unsupported. | 498 ms | PARTIAL_BUT_USEFUL |
| 19 | DIVERSIFICATION → portfolio_intelligence/SUCCESS | 25.4 effective holdings plus company, sector, correlation and economic-driver overlap. | 396 ms | USEFUL |
| 20 | OVERLAP_RISK → portfolio_intelligence/SUCCESS | Same-bet clusters and mapped shared drivers with combined weights/correlations. | 390 ms | USEFUL |
| 21 | DOWNSIDE_CAPACITY → portfolio_scenario/SUCCESS | 0.0% terminal-loss probability and -40.3% signed max-drawdown percentile explicitly defined as different concepts. | 392 ms | USEFUL |
| 22 | POSITION_SIZING → portfolio_risk/SUCCESS | No holding breaches approved 20% limit; ETF look-through caveat. | 477 ms | USEFUL |
| 23 | CASH_RESERVE → portfolio_risk/SUCCESS | $10,000 minimum and 10% target with withdrawal/income context. | 486 ms | USEFUL |
| 24 | SECTOR_SHOCK → portfolio_intelligence/SUCCESS | 26.3% mapped tech exposure × -20% = about -5.3% first-order effect; spillover/look-through limits. | 379 ms | USEFUL |
| 25 | DECISION_VS_INDEX → decision context/UNAVAILABLE + backtest/SUCCESS | Gross SPY/QQQ gaps shown; exact ledger/tax/fee inputs required for realized after-tax comparison. | 1,598 ms | PARTIAL_BUT_USEFUL |
| 26 | THESIS_STRENGTH → thesis_monitor/UNAVAILABLE | Objective strength ranking substituted honestly; requested one ownership claim to draft a reviewable thesis. | 418 ms | PARTIAL_BUT_USEFUL |
| 27 | THESIS_INVALIDATION → thesis_monitor/UNAVAILABLE | Objective breaker-like risks shown; no personal thesis breakers fabricated. | 391 ms | PARTIAL_BUT_USEFUL |
| 28 | POSITION_ACTION_REVIEW → portfolio_overview/PARTIAL | Research queue (hold/verify) with scores/reasons; refused automatic trade instructions. | 522 ms | USEFUL |
| 29 | AVERAGING_DOWN_REVIEW → portfolio_risk/SUCCESS | Listed actual losing positions, then requested ticker and proposed add size for the deterministic review. | 458 ms | PARTIAL_BUT_USEFUL |
| 30 | TARGET_PRICE_REVIEW → company_analysis/UNAVAILABLE + portfolio_overview/PARTIAL | Relative valuation starting table and targeted ticker/method clarification; no false price target. | 1,117 ms | PARTIAL_BUT_USEFUL |
| 31 | PORTFOLIO_EVENTS → portfolio_events/PARTIAL | Only Aug. 31 future events; expired Aug. 26 and closed/resolved rows absent. | 370 ms | USEFUL |
| 32 | OPTIONS_COSTS → portfolio_risk/SUCCESS | Named missing contract data, showed formulas and paste-ready ticket; no invented option cost. | 505 ms | PARTIAL_BUT_USEFUL |
| 33 | OPTIONS_EXPIRY → portfolio_risk/SUCCESS | Named missing DTE/catalyst/IV inputs, timing checks, and paste-ready schema. | 566 ms | PARTIAL_BUT_USEFUL |
| 34 | TRADE_PLAN_METRICS → portfolio_risk/SUCCESS | Named missing legs/fills/rules and showed exact max-loss/breakeven/exit formulas. | 470 ms | PARTIAL_BUT_USEFUL |
| 35 | CREATE_WIDGET → verified dashboard action/SUCCESS | Rendered portfolio/SPY/QQQ line chart: 23.2%, 20.2%, 25.2%; 12.0% volatility; 252 observations; Polygon+Tiingo; calculation v1.4.0. | 3,189 ms stored / 4,019 ms UI | USEFUL |

## Verification

- Focused Ask tests: 131 passed.
- Full backend: 685 passed, 9 skipped; one upstream Starlette/httpx deprecation warning.
- Frontend contracts: 82 passed.
- TypeScript: passed.
- Next production build: passed.
- Browser: 35/35 completed in the real signed-in UI.
- Refresh jobs started: 0.
- Other jobs started: 0.

## Remaining genuine limitations

1. No saved personal theses/breakers, so thesis-strength/replacement/invalidation answers remain objective substitutes plus targeted clarification.
2. No transaction/cash-flow/tax-lot/fee ledger, so actual realized and after-tax benchmark performance remains unavailable.
3. No contract-level option/trade ledger, so option cost, expiry fit, and trade-plan questions remain formulas plus input requests.
4. No versioned ticker-specific intrinsic-value assumptions in the question context, so dollar target bands require a ticker and methodology.
5. Event coverage currently has prediction-market rows but no configured forward earnings, macro-release, or company-catalyst calendar adapter.
6. Data-quality lineage contains provider and calculation metadata, but Q9's main prose still emphasizes coverage/rankability; those metadata are inspectable through evidence lineage rather than repeated inline.
7. Some portfolio research domains are partial because only eligible stored entities are ranked; the answer does not invent coverage for ineligible holdings.

No deployment or production migration was performed.
