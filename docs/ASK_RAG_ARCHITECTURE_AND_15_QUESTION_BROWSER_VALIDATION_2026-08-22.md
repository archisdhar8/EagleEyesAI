# EagleEyes Ask Architecture and 15-Question Browser Validation

**Date:** August 22, 2026  
**Environment:** Signed-in local application at `http://localhost:3000/ask`  
**Branch:** `feat/chat-first-ask-canvas`  
**Starting commit:** `ba7ee57`  
**Test method:** Each acceptance question was entered through the visible Ask EagleEyes browser UI in a new conversation. The results below are the text visible to the signed-in user, not direct unit-test, router, database, or API output.

## Executive conclusion

The current Ask implementation is **not a general RAG-first financial assistant**. It is primarily a deterministic intent router and capability-execution system backed by canonical Supabase/Postgres read models. A compact retrieval function and an optional Gemini narrator exist, but RAG is used selectively and cannot rescue most questions when the chosen canonical capability is missing a prerequisite.

The browser test confirms the user's concern:

- **0 of 15** questions produced a fully satisfactory answer to the question as asked.
- **1 of 15** produced a materially detailed answer, but that answer carried a verification inconsistency because excluded positions reappeared in the tool output.
- **1 of 15** correctly requested missing entity context (the prompt says “this company” without naming one).
- **10 of 15** returned honest but non-useful abstentions because a saved thesis, prior snapshot, scenario, optimizer result, event feed, factor history, or cash hurdle was unavailable.
- **3 of 15** were especially problematic or opaque: watchlist comparison, data quality, and recommendation countercase.
- Typical completed requests took roughly **8–11 seconds**. The first request was observed at **27.0 seconds** during the initial polling run.

This system is strong at preventing unsupported financial claims, but currently over-abstains. It often treats “the perfect capability result is unavailable” as equivalent to “no useful answer can be given,” even when other stored evidence could support a narrower answer.

## Current architecture

### 1. Browser and conversation layer

`app/components/ask/AskPage.tsx` renders the Ask workspace, context toggles, conversation, history, and new-chat controls. `app/Dashboard.tsx` owns the active conversation state and posts the visible question to `POST /api/chat/messages` with:

- workspace (`research` or `portfolio`)
- selected conversation ID
- current route and ticker context
- selected portfolio ID
- enabled evidence, thesis, and portfolio contexts

The backend persists conversations, messages, structured answer metadata, artifacts, portfolio snapshots, and capability read models through `backend/database.py` into Supabase/Postgres.

### 2. Deterministic intent routing

`backend/ask_orchestration.py` performs phrase-based routing. The 15 acceptance prompts map to named intents such as `OPPORTUNITY_RANKING`, `HIDDEN_RISK`, `DATA_QUALITY`, and `CASH_ALLOCATION`.

The router then maps each intent to one or more registered tools. Important runtime constraints are:

- maximum 3 tools
- 0 retries
- 0 replans
- 10-second default overall tool budget, clamped between 4 and 20 seconds

This is a bounded capability router, not semantic retrieval across all available evidence.

### 3. Compositional capability planner

`backend/capability_planner.py` can create a typed multi-capability plan for questions that need composition. The plan resolves entities, portfolio context, required versus optional steps, registry version, and response mode. Gemini planning is optional and, when enabled, receives registry/planning data rather than unrestricted financial data.

Direct high-confidence intents usually stay on the deterministic route. This makes the system reproducible, but it also means a narrowly selected capability can become a single point of failure for the answer.

### 4. Execution graph and deadlines

`backend/ask_execution.py` executes capability nodes under one absolute request deadline. Nodes may run in parallel, have dependencies, and end as completed, timed out, deadline-skipped, or dependency-skipped. `backend/main.py` assembles the execution plan and records timing, cache, verification, and dependency metadata.

The architecture deliberately avoids unlimited agent loops. That is appropriate for predictable latency and financial safety, but there is no fallback planning pass when a chosen capability returns `UNAVAILABLE`.

### 5. Retrieval and RAG

`backend/chat.py::retrieve_evidence` builds a compact evidence bundle containing up to 18 records from:

- current portfolio and holdings
- investor profile and watchlist
- macro factor dashboard
- prediction-market scenario snapshot
- latest cached portfolio-health result
- ticker research selected from mentioned or available securities
- latest optimizer analysis

The evidence bundle is cached for 45 seconds. The optional Gemini narrator can synthesize an answer from evidence and tool results when it has enough remaining deadline and the result passes the relevant gates. Otherwise a deterministic renderer produces the answer.

This is **selective retrieval plus optional narration**, not universal RAG. For most of the 15 prompts, the selected domain capability/read model determines the result before broad retrieved evidence can help.

### 6. Canonical analytical contract and verification

`backend/analytical_contract.py` defines the shared `AnalysisResult` contract:

- status
- calculation version and input fingerprint
- data
- coverage
- freshness
- lineage
- dependencies and prerequisites
- limitations and warnings
- verification result

Domain builders and read models live mainly in `backend/phase4_analytics.py`, `backend/phase6_domains.py`, `backend/ask_portfolio.py`, `backend/portfolio_intelligence.py`, and `backend/read_models.py`.

This contract is the strongest part of the architecture. It prevents the narrator from inventing data. The current weakness is that the validation outcome frequently suppresses all useful synthesis instead of narrowing the claim.

### Request flow

```text
Ask UI
  -> POST /api/chat/messages
  -> authenticate + load conversation/portfolio context
  -> deterministic intent router
  -> optional compositional capability planner
  -> bounded execution graph
       -> canonical Supabase/read-model capabilities
       -> selective stored-evidence retrieval
  -> AnalysisResult verification (coverage/freshness/dependencies)
  -> deterministic renderer OR optional Gemini narration
  -> persist message + structured metadata
  -> render answer, citations, actions, and optional canvas
```

## What “RAG validation” should mean here

The desired architecture should remain hybrid; pure free-form RAG would be a regression for portfolio math. A better target is:

1. **Retrieve first:** Build an owner-scoped evidence bundle for every question from Supabase, canonical read models, live provider caches, theses, prior conversations, and the current page context.
2. **Validate retrieval:** Resolve named entities, portfolio scope, freshness, source provenance, and minimum coverage before making claims.
3. **Calculate when needed:** Use deterministic capabilities for rankings, weights, correlations, scenarios, optimizer constraints, and score attribution.
4. **Validate calculations:** Apply the existing `AnalysisResult` contract and claim-level verification.
5. **Synthesize the best supported answer:** Let the narrator answer from all validated evidence, not only the primary capability result. If the ideal result is unavailable, provide a narrower supported answer and clearly label what could not be concluded.
6. **Cite each important claim:** Preserve source, as-of date, calculation version, and coverage close to the claim.
7. **Ask a clarification only when necessary:** Missing entity identity (question 10) is a legitimate clarification; missing perfect factor coverage should not automatically prevent a useful qualitative answer.

The key product change is: **validation should constrain the answer, not erase every answer.**

## Browser test summary

| # | Capability | Time | Outcome | Assessment |
|---:|---|---:|---|---|
| 1 | Opportunity ranking | 27.0s | No eligible security | Honest abstention; did not provide three opportunities |
| 2 | Thesis replacement | 10.2s | No saved thesis | Honest prerequisite failure |
| 3 | Portfolio change | 10.9s | No prior snapshot | Honest prerequisite failure |
| 4 | Valuation ranking | 8.8s | No eligible comparison | Honest evidence-gap response |
| 5 | Hidden concentration | 9.6s | Detailed result | Substantive, but verification inconsistency |
| 6 | Multi-scenario | 9.6s | No cached simulation | Honest prerequisite failure; no on-demand calculation |
| 7 | Watchlist comparison | 10.3s | Recommendation withheld | Opaque and non-actionable |
| 8 | Portfolio events | 9.5s | All categories missing | Honest event-data failure |
| 9 | Data quality | 10.2s | 0/57 coverage | Likely broken/inconsistent with other available portfolio output |
| 10 | Score attribution | 10.3s | Asked for holding | Correct clarification for an underspecified prompt |
| 11 | Thesis invalidation | 8.1s | No saved thesis | Honest prerequisite failure |
| 12 | Rebalance | 9.5s | No optimizer run | Honest prerequisite failure; no on-demand optimization |
| 13 | Multifactor screen | 10.3s | No eligible company | Honest evidence-gap response |
| 14 | Recommendation countercase | 9.6s | No recommendation | Broken/meaningless countercase and verification inconsistency |
| 15 | Cash allocation | 11.0s | No clear edge | Defensible abstention, but missing cash hurdle blocks the question |

## Full visible answers

The browser exposes source labels and dates separately in the answer UI. Text below is normalized into paragraphs for readability without changing the substantive content.

### 1. Strongest opportunities

**Question:** What are the three strongest opportunities in my portfolio today, and what evidence supports each one?

**Visible answer:**

> Verification limitation: No security passed every opportunity eligibility gate.
>
> No holding currently passes every opportunity-v2 eligibility gate. EagleEyes will not rank low-quality or placeholder-driven factor records as opportunities.
>
> What to verify: refresh raw fundamentals and price history, then rebuild the opportunity read model.
>
> Evidence used (1): Canonical `portfolio_overview` analysis. As of Aug 19, 2026.

**Assessment:** Honest, but it does not answer the request. A RAG fallback could still summarize the strongest supported holdings while explicitly saying they are not eligible “opportunities.”

### 2. Weakest thesis and replacement

**Question:** Which holding has the weakest investment thesis, and what should I replace it with?

**Visible answer:**

> No saved thesis exists for this portfolio, so EagleEyes cannot identify a weakest thesis or claim that a replacement invalidates it.
>
> What to verify: confirm the selected portfolio and complete the missing saved-data prerequisite.
>
> Evidence used (1): Canonical `thesis_replacement` analysis. As of Aug 19, 2026.

**Assessment:** Correctly refuses to invent a user thesis. It could still distinguish “weakest stored evidence” from “weakest user thesis.”

### 3. Material portfolio change

**Question:** What has materially changed in my portfolio since my last review?

**Visible answer:**

> No previous portfolio snapshot exists, so material change cannot be calculated.
>
> What to verify: confirm the selected portfolio and complete the missing saved-data prerequisite.
>
> Evidence used (1): Canonical `portfolio_change` analysis. As of Aug 19, 2026.

**Assessment:** Correct prerequisite failure. The product should create periodic snapshots automatically if this is a flagship question.

### 4. Overvaluation ranking

**Question:** Which positions are most overvalued relative to their growth and fundamentals?

**Visible answer:**

> Verification limitation: No eligible relative-value comparison is available.
>
> These eligible holdings have the largest observed valuation burden after accounting for stored growth and fundamental quality: No holding has sufficient raw valuation and growth inputs for this comparison.
>
> This is a relative evidence gap, not an intrinsic-value estimate or return forecast.
>
> What to verify: inspect each underlying multiple, EPS comparison period, peer count, and freshness.
>
> Evidence used (1): Canonical `valuation_ranking` analysis. As of Aug 19, 2026.

**Assessment:** Safe but empty. The phrase “These eligible holdings” followed by no holdings is awkward and should be rendered as a direct unavailable state.

### 5. Hidden concentration risk

**Question:** Where am I taking hidden concentration risk across sectors, themes, and correlated companies?

**Visible answer:**

> Verification limitation: Excluded positions reappeared in tool output: CASH, GLIFX, PONPX, PSDTX.
>
> **Conclusion:** The portfolio's visible concentration starts with SPY at 10.4%, and its weights are equivalent to roughly 25.4 equally sized holdings. The more important risk concentration is the overlap between the largest positions, correlated clusters, and shared economic drivers below.
>
> **Capital concentration:** SPY 10.4%; SGOV 7.5%; PANW 6.9%; RSP 5.9%; AVGO 4.4%; SPHY 4.2% of portfolio value.
>
> **Largest classified sectors:** Unclassified 51.8%; Information Technology 26.3%; Financials 5.6%; Communication Services 4.5%; Consumer Discretionary 3.2%.
>
> **Largest classified industries:** Unclassified 51.8%; Systems Software 10.7%; Semiconductors 8.1%; Interactive Media & Services 4.5%.
>
> **Return-correlation clusters:**
>
> 1. AAPL, AMD, AMZN, AVGO, AXP, BLK, BRK.B, BX, CSM, DBEF, EPP, EWJ, GOOG, GOOGL, IJR, JEPI, META, MSFT, NVDA, QCOM, QQQ, RPG, RSP, SPHY, SPY, SPYG, VO, VTV — 57.0% combined weight; strongest measured pair correlation 1.00.
> 2. BND, PONPX, USIG — 4.9% combined weight; strongest measured pair correlation 0.95.
> 3. GLD, IAU — 4.4% combined weight; strongest measured pair correlation 1.00.
>
> **Shared economic dependencies:** AI Infrastructure Demand 17.0%; Semiconductor Export Restriction 8.1%; Recession 7.5%; Interest Rates 6.5% mapped exposure.
>
> **Largest modeled risk contributors:** PANW 12.6%; SPY 11.2%; AVGO 8.8%; BX 5.8%; RSP 5.4%; MSFT 5.2%; GOOGL 4.3%; AMZN 3.6% modeled risk contribution.
>
> **Coverage limits:** Sector and dependency classifications cover 96.7% of portfolio weight. ETF holdings are shown at the fund level unless look-through constituent data is explicitly present, so direct holdings may overlap with an index fund more than these totals reveal.
>
> What to verify: inspect ETF look-through, the covariance date and sample size, and whether the largest shared economic dependencies match how you understand the businesses.
>
> Evidence used (1): Canonical `portfolio_intelligence` analysis. As of Aug 19, 2026.

**Assessment:** This is the only materially detailed response. It is not fully trustworthy as presented because the verifier says excluded positions reappeared, while PONPX is still included in a displayed correlation cluster. The renderer should suppress or recompute affected claims when verification fails.

### 6. Multi-scenario portfolio impact

**Question:** What would happen to my portfolio if interest rates rose, the economy entered a recession, or AI spending slowed?

**Visible answer:**

> No cached portfolio simulation exists yet. Queue the canonical scenario refresh before relying on this comparison.
>
> What to verify: confirm the selected portfolio and complete the missing saved-data prerequisite.
>
> Evidence used (2): Canonical `portfolio_scenario` analysis. As of Aug 19, 2026; Canonical `portfolio_scenario` analysis.

**Assessment:** The system can only read a cached simulation here; it does not calculate or queue one on demand. Duplicate evidence labels are also visible.

### 7. Watchlist versus current holdings

**Question:** Which watchlist stocks now have a stronger risk-adjusted case than my existing holdings?

**Visible answer:**

> A valid actionable portfolio recommendation could not be produced. The verified diagnostics are still available, but attempted optimizer weights and trades have been withheld.
>
> Watchlist dominance includes risk and portfolio-fit evidence.
>
> What to verify: resolve the listed coverage, constraint, or portfolio-state issue before using a rebalance.
>
> Evidence used (1): Canonical `watchlist_comparison` analysis. As of Aug 19, 2026.

**Assessment:** Opaque. It says diagnostics are available but does not show them or identify the actual blocking issue.

### 8. Upcoming events and catalysts

**Question:** What upcoming earnings reports, economic events, or company catalysts could materially affect my portfolio?

**Visible answer:**

> Verification limitation: One or more event categories are incomplete.
>
> The stored event calendar contains these upcoming portfolio-relevant events: No covered upcoming event is stored.
>
> Category completeness: earnings MISSING; macro MISSING; company catalysts MISSING.
>
> What to verify: confirm event dates and missing categories before assuming silence means no catalyst exists.
>
> Evidence used (1): Canonical `portfolio_events` analysis. As of Aug 19, 2026.

**Assessment:** Accurate representation of missing event ingestion. This flagship question requires a live or regularly refreshed events provider.

### 9. Missing data and ranking trust

**Question:** Which holdings are missing reliable data, and how much should I trust their rankings?

**Visible answer:**

> I evaluated 0 of 57 requested entities (0.0% coverage), so I cannot reliably characterize the requested securities. No unsupported comparison was generated.
>
> 0 of 57 requested entities have every required field. Coverage is too low for a whole-portfolio conclusion. Analytical coverage is 0/57 (0.0%).
>
> What to verify: refresh the missing stored evidence and rerun the analysis.
>
> Evidence used (1): Canonical `data_quality` analysis. As of Aug 19, 2026.

**Assessment:** This appears inconsistent with question 5, which produced classifications for 96.7% of portfolio weight and detailed modeled results. The two capabilities may use different required-field contracts, but the UI does not explain that. At minimum it should list which fields are missing per holding.

### 10. Score attribution

**Question:** Why did this company’s EagleEyes score change, and which inputs contributed most to the change?

**Visible answer:**

> Name a holding or open its research page before asking why its score changed.
>
> What to verify: confirm the selected portfolio and complete the missing saved-data prerequisite.
>
> Evidence used (1): Canonical `score_attribution` analysis. As of Aug 19, 2026.

**Assessment:** Correct. The exact acceptance prompt is underspecified when opened in a fresh `/ask` conversation without ticker context.

### 11. Thesis invalidation

**Question:** What evidence would invalidate the thesis for each of my largest positions?

**Visible answer:**

> No saved thesis exists. EagleEyes can show evidence risks, but it cannot invent the user's thesis or its invalidation conditions.
>
> What to verify: confirm the selected portfolio and complete the missing saved-data prerequisite.
>
> Evidence used (1): Canonical `thesis_monitor` analysis. As of Aug 19, 2026.

**Assessment:** Correct refusal to invent user theses. The requested fallback—showing evidence risks—is mentioned but not actually shown.

### 12. Rebalancing

**Question:** How should I rebalance the portfolio while minimizing unnecessary turnover, taxes, and trading costs?

**Visible answer:**

> No saved portfolio optimizer run exists.
>
> What to verify: confirm the selected portfolio and complete the missing saved-data prerequisite.
>
> Evidence used (2): Canonical `portfolio_analysis` analysis. As of Aug 19, 2026; Canonical `portfolio_analysis` analysis.
>
> Continue in EagleEyes: Open portfolio intelligence.

**Assessment:** Does not run or queue the optimizer and does not explain how to create the prerequisite. Duplicate evidence labels are visible.

### 13. Multifactor screen

**Question:** Which companies combine improving fundamentals, reasonable valuation, and positive momentum?

**Visible answer:**

> Verification limitation: No company has sufficient evidence for an improving fundamental trend.
>
> These holdings have a genuinely improving stored fundamental trend plus available valuation and positive momentum: No holding passes all three deterministic requirements with sufficient historical evidence.
>
> A strong current fundamental score without an improving trend is excluded.
>
> What to verify: inspect the reported periods and metric-level trend evidence.
>
> Evidence used (1): Canonical `multifactor_screen` analysis. As of Aug 19, 2026.

**Assessment:** Safe but empty. A useful fallback would show near-matches and which specific criterion each one fails.

### 14. Countercase to top recommendation

**Question:** What are the strongest arguments against EagleEyes’ current top recommendation?

**Visible answer:**

> Verification limitation: Excluded positions reappeared in tool output: CASH, GLIFX, PONPX, PSDTX.
>
> Countercase for no eligible recommendation (recommendation `unavailable`): No stable eligible recommendation exists to challenge.
>
> Unknowns: none recorded.
>
> What to verify: confirm the recommendation fingerprint and calculation version still match the current portfolio.
>
> Evidence used (1): Canonical `recommendation_countercase` analysis. As of Aug 19, 2026.

**Assessment:** This should simply state that no current recommendation exists. “Unknowns: none” conflicts with the unavailable recommendation and verification warning.

### 15. New cash allocation

**Question:** If I invested new cash today, where should it go—and why is that better than holding cash?

**Visible answer:**

> Verification limitation: No sourced cash hurdle is available; investing cannot be claimed superior to cash.
>
> **Decision: NO CLEAR EDGE.**
>
> Cash hurdle: unavailable — no supported stored cash/risk-free yield.
>
> No candidate has a verified edge over the available comparison set.
>
> None.
>
> EagleEyes does not force deployment and does not invent expected returns, taxes, or trading costs.
>
> Evidence used (1): Canonical `cash_allocation` analysis. As of Aug 19, 2026.

**Assessment:** The abstention is defensible. The missing cash hurdle should be straightforward to source from a Treasury/cash benchmark feed; without it the flagship allocation question cannot work.

## Conversation UI persistence checks

These checks were also performed through the browser after the 15 prompts:

- **History:** The history drawer opened successfully and showed the new acceptance-test conversations plus older chats. Approximately 90 history controls were present.
- **Open old chat:** Selecting the new-cash conversation from History restored its two messages successfully.
- **New chat:** After closing History, New chat cleared the active conversation and returned the empty prompt state.
- **Reload:** Navigating back to `/ask` while a conversation was active did **not** automatically restore its messages during the observed 2.2-second window. The conversation remained available in History and could be restored manually. This reproduces the user's complaint that reload behavior feels broken.

## Priority fixes

1. **Make retrieval universal and claim-level.** Always retrieve the current owner-scoped evidence bundle before deciding that no answer is possible.
2. **Add graceful cross-capability fallback.** When a primary capability is unavailable, synthesize a narrower answer from other verified capabilities instead of returning only a prerequisite message.
3. **Refresh or compute flagship prerequisites on demand.** Scenario, portfolio-change, events, optimizer, opportunity, and cash-hurdle questions should queue or run the missing canonical calculation when safe.
4. **Fix verification/rendering coupling.** If excluded holdings reappear, suppress affected rows or mark exactly which claims are invalid; do not show a detailed conclusion as if verification passed.
5. **Explain coverage at field level.** Replace “0 of 57” with a per-holding list of missing required inputs and a separate confidence score for data that is present.
6. **Improve unavailable-state copy.** Remove empty lead-ins, duplicate source cards, unexplained “None,” and statements such as “diagnostics are available” when no diagnostics are displayed.
7. **Restore the active chat on reload.** Persist and reload the active conversation ID reliably; keep History and New chat behavior as tested.
8. **Retest the same 15 questions as an end-to-end release gate.** Route-selection unit tests are necessary but do not demonstrate useful answers.

## Release assessment

The Ask experience is **not ready to be presented as a broad portfolio question-answering assistant**. It is suitable as a constrained beta for verified canonical outputs if the UI clearly labels supported capabilities and missing prerequisites. Before a wider release, EagleEyes needs the retrieval-first fallback layer, reliable prerequisite refreshes, and a browser acceptance threshold based on answer usefulness—not merely successful routing or HTTP completion.
