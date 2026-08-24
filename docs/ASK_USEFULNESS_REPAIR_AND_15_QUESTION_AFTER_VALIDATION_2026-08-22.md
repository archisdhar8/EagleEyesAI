# EagleEyes Ask usefulness repair and signed-in browser validation

**Date:** August 22, 2026
**Environment:** signed-in local app at `http://localhost:3000/ask`
**Portfolio:** `d4a0d97e-154e-4b67-b672-e9c05d582952` (57 analytically covered holdings; 61 raw positions before exclusions)
**Branch:** `feat/chat-first-ask-canvas`
**Deployment/migrations:** no deployment and no production migration applied

## Final result

- All 15 exact acceptance questions now produce a useful answer, a useful claim-level partial answer, or the correct clarification.
- 8 are fully useful, 6 are partial but useful, and 1 correctly asks for the missing company ticker.
- 0 answers leak the excluded positions `CASH`, `GLIFX`, `PONPX`, or `PSDTX`.
- 0 answers silently turn missing evidence into a financial claim.
- Missing calculable scenario and optimizer prerequisites enqueue bounded jobs instead of ending at a generic abstention.
- Reload restores the active conversation, History opens saved conversations, an old conversation reopens, and New Chat starts blank without deleting history.
- Correctness/relevance clears the 12-of-15 release target. Latency does not: visible requests still took 7.9–12.4 seconds, not the requested sub-5-second cached target.

**Release judgment: owner-only use is appropriate; private beta is held back by latency and known data-domain gaps.**

## Architecture after the repair

Ask remains a hybrid deterministic/RAG system. Supabase is the durable source of truth; the optional Gemini narrator is disabled for this validation and is not required for the answers below.

```text
Ask UI + durable conversation cache
  -> authenticated POST /api/chat/messages
  -> deterministic intent/entity/context resolution
  -> bounded capability execution (max 3 tools, no open-ended loop)
  -> canonical Supabase read models + owner-scoped retrieval
  -> RequirementResolution
       system data | on-demand computation | user-required context
  -> AnalysisResult verification
  -> SupportedAnswer
       supported claims | partial claims | unavailable claims | pending jobs
  -> excluded-symbol output boundary
  -> persisted message + structured evidence + visible answer
```

The important behavioral change is that verification now narrows claims instead of erasing the whole answer. Missing personal context is never invented. Missing system data is reported as a health gap. Missing calculable artifacts enqueue a canonical job. Available adjacent evidence is returned immediately and labeled as a partial result.

### Dependency classes

| Class | Examples | Behavior |
|---|---|---|
| Always-available system data | prices, fundamentals/history, classifications, events, macro, market, prediction markets, portfolio/score history, cash hurdle | retrieve before abstaining; expose current/partial/stale/missing/failed health |
| On-demand computation | simulation, optimization, backtest, deep research | enqueue one bounded idempotent job and return supported current evidence |
| User-required context | saved thesis, thesis breakers, tax lots, custom constraints | do not fabricate; answer objective subclaims and state the exact input needed |

### New answer contract

`SupportedAnswer` persists and exposes:

- direct answer
- supported and partial claims
- unsupported and pending claims
- evidence/capabilities used
- jobs started
- data gaps and user input needed
- confidence and coverage

### Data health

The new `DataHealthState` domain model covers prices, fundamentals, fundamental history, classifications, events, macro, market state, prediction markets, portfolio history, score history, and the cash hurdle. The read path is cached for 45 seconds to avoid repeating health metadata queries on every question. A Supabase migration is included but intentionally not applied.

### Excluded-position boundary

Excluded pseudo-positions are removed from structural rows and nested outputs immediately after capability execution. A follow-up fix prevents the ordinary English word “cash” from being mistaken for the excluded `CASH` symbol. This was the cause of the former cash-allocation HTTP 500.

## Root-cause map and repair outcome

| # | Previous root cause | Repair |
|---:|---|---|
| 1 | Full eligibility failure erased near matches | Return eligible ranking or strongest partial setups with failed gates |
| 2 | Missing saved thesis ended the answer | Preserve personal-thesis limitation; rank objective stored evidence and show watchlist dominance |
| 3 | Only nightly history was accepted | Use latest compatible prior portfolio snapshot regardless of valid materialization trigger |
| 4 | Full valuation eligibility was all-or-nothing | Return observed relative-valuation comparisons with coverage/peer limitations |
| 5 | Excluded symbols leaked; coverage metadata conflicted with displayed sectors | Enforce output boundary and disclose 48.2% displayed classification versus 96.7% metadata conflict |
| 6 | Missing cached simulation caused a dead-end | Queue canonical simulation and return current weights plus deterministic AI exposure mapping |
| 7 | Recommendation gate suppressed watchlist diagnostics | Return candidate/incumbent dominance, correlation, and concentration effects |
| 8 | Events existed outside the portfolio-event answer | Materialize covered prediction/company events and show per-category completeness |
| 9 | One aggregate gate produced a false-looking 0/57 | Report field/domain coverage and per-holding missing inputs |
| 10 | Missing company identity produced generic prerequisite boilerplate | Ask specifically for a ticker and generate no company-specific claim |
| 11 | Missing saved breakers ended the answer | Preserve personal limitation and return objective risks for the largest positions |
| 12 | Missing optimizer ended the answer | Queue compatible optimizer; return current concentration and tax-lot limitation |
| 13 | Full multifactor gate hid useful evidence | Return exact matches or strongest near matches with failed criteria |
| 14 | Countercase depended on an absent/stale recommendation | Materialization now produces a verified current recommendation; countercase cites its fingerprint |
| 15 | Cash hurdle was absent, then output filtering crashed on “cash” | Source FRED DGS3MO, preserve source/as-of, fix scrubber, and state that factor evidence does not prove excess return over cash |

## Exact 15-question browser results

Times are end-to-end UI observations from fresh conversations. Visible wording is normalized into Markdown, but figures and conclusions are unchanged.

| # | Time | Grade | Visible conclusion |
|---:|---:|---|---|
| 1 | 10.478s | Useful | MSFT 64.1, SBUX 58.2, QCOM 57.5, with supporting and opposing evidence |
| 2 | 9.390s | Partial useful | No personal thesis exists; objective weakest setups and watchlist evidence shown |
| 3 | 10.231s | Useful | TEM momentum +18.2; WMT valuation +9.0; WMT momentum -8.6 |
| 4 | 12.299s | Useful | Ten eligible relative-valuation gaps shown |
| 5 | 12.396s | Useful | Positions, sectors, clusters, dependencies, risk contributions; coverage inconsistency disclosed |
| 6 | 10.275s | Partial useful | Simulation queued; current exposures and 17.0% AI-capex mapping shown |
| 7 | 9.737s | Useful | No watchlist candidate dominates; exact scores/correlations/concentration effects shown |
| 8 | 8.679s | Partial useful | Covered NVDA/GOOG/AMZN events shown; earnings and macro categories labeled missing |
| 9 | 10.541s | Useful | 57/57 price/momentum, 37/57 fundamentals, 34/57 ranking-eligible, per-holding gaps |
| 10 | 7.904s | Correct clarification | Requests a ticker; no company claim generated |
| 11 | 8.932s | Partial useful | No personal breakers; objective risks for ten largest positions shown |
| 12 | 9.442s | Partial useful | Optimizer queued; weights shown; tax-aware claims withheld without tax lots |
| 13 | 11.053s | Useful | SBUX is the one exact improving-fundamentals/value/momentum match |
| 14 | 10.235s | Useful | MSFT countercase covers valuation, modeled risk, and AI dependency |
| 15 | 9.457s | Partial useful | FRED cash hurdle and SPY/QQQ candidates shown; excess-return claim explicitly withheld |

### 1. Strongest opportunities

**Question:** What are the three strongest opportunities in my portfolio today, and what evidence supports each one?

**Answer:** MSFT scores 64.1/100 (improving stored fundamental trend; demanding valuation is the main concern), SBUX 58.2/100 (improving trend and positive price momentum), and QCOM 57.5/100 (declining trend is explicitly shown as the main concern). EagleEyes labels this a current evidence-backed setup ranking, not a return forecast.

### 2. Weakest thesis and replacement

**Question:** Which holding has the weakest investment thesis, and what should I replace it with?

**Answer:** No personal theses are saved, so EagleEyes does not invent or rank them. Objective weakest setups are EPI (54.9), USIG (55.6), SPHY (55.7), SGOV (55.9), and VO (56.9). XLE, XLV, and VTI show no clear replacement dominance. Saving a thesis and breakers is required for a personal replacement claim.

### 3. Material changes

**Question:** What has materially changed in my portfolio since my last review?

**Answer:** TEM momentum crossed the threshold by +18.20. WMT valuation changed +9.00 and momentum -8.60. The answer points to the compatible baseline and evidence date for verification.

### 4. Relative overvaluation

**Question:** Which positions are most overvalued relative to their growth and fundamentals?

**Answer:** The largest eligible relative-value gaps are QCOM +76.2, DLR +73.4, WMT +50.5, BLK +48.4, LHX +32.6, AVGO +28.6, SBUX +22.3, NOC +21.6, IBM +21.5, and TSLA +17.6. The UI states that this is a relative evidence gap, not intrinsic value or a return forecast.

### 5. Hidden concentration

**Question:** Where am I taking hidden concentration risk across sectors, themes, and correlated companies?

**Answer:** Largest visible weights are SPY 10.4%, SGOV 7.5%, PANW 6.9%, RSP 5.9%, AVGO 4.4%, and SPHY 4.2%. The main correlation cluster covers 57.0% combined weight. Shared mapped dependencies include AI infrastructure demand 17.0%, semiconductor export restrictions 8.1%, recession 7.5%, and interest rates 6.5%. PANW (12.6%) and SPY (11.2%) are the largest modeled risk contributors. No excluded symbol appears. The UI now states that displayed sector rows classify 48.2% while stored metadata says 96.7%, flags that inconsistency, and does not pretend both are the same measure.

### 6. Multi-scenario impact

**Question:** What would happen to my portfolio if interest rates rose, the economy entered a recession, or AI spending slowed?

**Answer:** A compatible loss/drawdown/wealth simulation is not cached, so those magnitudes are withheld and the canonical job is queued. The immediate answer shows the eight largest weights and maps AI-capex slowdown exposure to 17.0% across AMD, AMZN, AVGO, GOOG, GOOGL, META, MSFT, and NVDA. It explicitly says exposure mapping is not a modeled loss.

### 7. Watchlist versus holdings

**Question:** Which watchlist stocks now have a stronger risk-adjusted case than my existing holdings?

**Answer:** No new watchlist position proves dominance. XLE scores 66.9 with -0.10 correlation, XLV 64.6 with 0.18, and VTI 64.5 with 0.89; all worsen the stored concentration measure. SPY and QQQ are separately labeled add-to-existing candidates. The composite is explicitly not called a Sharpe ratio or outperformance probability.

### 8. Upcoming events

**Question:** What upcoming earnings reports, economic events, or company catalysts could materially affect my portfolio?

**Answer:** The calendar shows covered NVDA Q2 prediction-market events for August 26, Google Gemini events for August 31, and an AMZN month-end event. It labels earnings `MISSING`, macro `MISSING`, and company catalysts `PARTIAL`, so silence is not presented as a complete calendar.

### 9. Data quality

**Question:** Which holdings are missing reliable data, and how much should I trust their rankings?

**Answer:** Prices/history 57/57, fundamentals/history 37/57, momentum 57/57, and ranking eligibility 34/57. Full opportunity eligibility, classifications, and valuation-input coverage are explicitly labeled as not independently counted by this read model rather than inferred. Method checks separately show fundamental freshness 37/57, fundamental history 37/57, trend 57/57, momentum history 57/57, price freshness 57/57, provider quality 34/57, and required factor scores 57/57. The UI lists affected holdings and exact missing/placeholder fields; examples include BND, CSM, DBEF, EPI, EPP, EQNR, EWJ, IJR, JEPI, MLPX, QQQ, RSP, SGOV, SPHY, SPY, and SPYG.

### 10. Score attribution clarification

**Question:** Why did this company’s EagleEyes score change, and which inputs contributed most to the change?

**Answer:** “Name a holding (for example, `MSFT`) or open that holding's research page.” Score attribution requires one ticker and a compatible prior score snapshot; no company-specific explanation is generated.

### 11. Thesis invalidation

**Question:** What evidence would invalidate the thesis for each of my largest positions?

**Answer:** No personal theses/breakers exist, so the answer does not invent them. It returns objective risks instead: PANW modeled risk 12.6% and valuation 25/100; SPY modeled risk 11.2%; AVGO risk 8.7% and valuation 28/100; MSFT risk 5.2% and valuation 37/100; BX risk 5.8% and momentum 43/100; plus the other largest positions.

### 12. Rebalance

**Question:** How should I rebalance the portfolio while minimizing unnecessary turnover, taxes, and trading costs?

**Answer:** A compatible optimizer job is queued. The immediate answer shows current concentration beginning with SPY 10.9%, SGOV 7.9%, PANW 7.2%, and RSP 6.2%. Exact turnover/cost claims remain pending and tax-aware trades are withheld because tax lots are absent.

### 13. Multifactor screen

**Question:** Which companies combine improving fundamentals, reasonable valuation, and positive momentum?

**Answer:** SBUX is the exact match: improving trend across three stored periods, fundamentals 50, valuation 47, and momentum 62. A high current fundamental level without an improving trend is excluded.

### 14. Recommendation countercase

**Question:** What are the strongest arguments against EagleEyes’ current top recommendation?

**Answer:** The current verified recommendation is MSFT. Counterarguments are demanding/weak stored valuation evidence, 5.2% modeled risk contribution, and exposure to AI-infrastructure demand. The recommendation fingerprint is displayed for compatibility verification.

### 15. New cash versus cash hurdle

**Question:** If I invested new cash today, where should it go—and why is that better than holding cash?

**Answer:** The stored decision is partial deployment. The sourced hurdle is 3.86% annualized from FRED DGS3MO as of August 19, 2026. SPY scores 63.8 and QQQ 63.5 as add-to-existing candidates, with concentration worsening disclosed for both. Crucially, the answer states that this factor comparison does **not** prove a risk-adjusted return above cash because no supported expected-return forecast exists; exact sizing also awaits a risk budget and transaction-cost model.

## Conversation and UI browser checks

- Active chat restored after reload in about 0.85 seconds from the scoped local snapshot, then reconciled with Supabase.
- History opened and contained the saved cash-allocation conversation plus older conversations.
- New Chat immediately rendered the empty prompt state and did not display the old answer.
- Reopening the saved cash-allocation conversation restored both question and answer.
- The Ask surface is widened to 1400px, messages to 1200px/92%, answer body text to 17px, and small labels to 12px.

## Verification

- Backend: **637 passed, 9 skipped** (`pytest -q`)
- Frontend/build: **82 passed** (`npm test`)
- TypeScript: **passed** (`npm run typecheck`)
- Focused Ask suite after final repairs: **49 passed**
- Browser: exact 15 questions entered through the signed-in visible UI
- Gemini narration: disabled/not required
- Production migration: not applied
- Deployment: not performed

## Remaining blockers before private beta

1. **Latency:** every measured answer exceeded five seconds. Data-health metadata is now cached, but request setup, capability execution, and durable persistence still dominate the path.
2. **Classification completeness:** displayed sectors classify 48.2% of weight while stored metadata says 96.7%. The answer is now honest, but the upstream measures must be reconciled.
3. **Event completeness:** earnings and macro categories remain missing; company catalysts are partial.
4. **Scenario/optimizer artifacts:** jobs are correctly queued, but the owner must allow them to finish and verify the resulting compatible artifacts.
5. **User context:** personal thesis/breaker and tax-lot claims remain unavailable until the owner supplies that information.

ASK READY FOR OWNER-ONLY USE
