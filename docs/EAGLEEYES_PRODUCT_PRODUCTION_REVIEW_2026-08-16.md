# EagleEyes product and production-readiness review

**Review date:** August 16, 2026
**Verdict:** A coherent and differentiated investing decision-memory product, but not ready for external beta today.
**Overall score:** **6.4/10**

## Evidence inspected

This review is based on the current implementation, not the product description alone:

- Authenticated desktop flows for Today, Portfolio, Research, Decisions, Ask EagleEyes, Learn, and Advanced.
- The published Sites project and its runtime configuration.
- Frontend routes, responsive CSS, loading/error/empty states, and primary interaction contracts.
- FastAPI endpoints, authentication, authorization, RLS migrations, caching, retries, rate limits, background work, observability, and AI orchestration.
- Current Supabase migration state and aggregate provider coverage.
- The full local regression matrix.

Verification results:

- Production frontend build: passed, with a bundle-size warning over 500 kB.
- Frontend/static contracts: **64 passed**.
- TypeScript: passed.
- Backend tests: **298 passed, 9 skipped**. The skips are the live-provider and deployed-production smoke tests.
- Authenticated browser journeys with deterministic fixtures: **16 passed**.
- Supabase connection: passed; all **32 migrations** are applied.
- Current shared data: 1,037,498 price bars; 606 provider-symbol histories (534 Polygon, 72 Tiingo, with overlap possible); 515 securities with fundamental periods; 3,109 documents mapped across 2,092 securities; 10,998 prediction-market snapshots; 146,386 macro observations.
- Critical absent coverage: **0 market events, 0 transcript documents, 0 fundamental periods with consensus, 0 with guidance, and 0 with estimate revisions**.
- Current local rendered state: authenticated UI, but research engine offline; Today and Provider Health can remain in loading/awaiting states; Research initially reports zero securities even though data exists.
- Published Sites state: owner-only and live, but no hosted environment variables, no backend tunnel/binding, and no deployable API in the Worker. The client defaults to `http://127.0.0.1:8000/api`.

The working tree contains a large uncommitted refactor. This does not invalidate the product review, but it is not a release artifact that should be treated as reproducible until committed and built in CI.

---

## 1. Executive product verdict

| Dimension | Score | Short explanation |
|---|---:|---|
| Core value proposition | 7.6 | Persistent theses, evidence changes, portfolio context, and decision history solve a real problem that brokerages largely ignore. |
| Product coherence | 7.2 | The five primary destinations now tell a coherent story. Secondary builders, Learn, Plan, and Advanced still make the total product feel broader than the core loop. |
| Research usefulness | 6.5 | The decision-question framing and missing-data disclosure are strong. Current earnings expectations, transcripts, historical valuation, and event coverage are too weak. |
| Portfolio intelligence | 7.5 | Effective holdings, risk contribution, shared drivers, scenarios, thesis health, and event exposure are meaningfully beyond brokerage analytics. Some mappings are heuristic. |
| Decision support | 7.8 | “Do nothing” is valid, alternatives are compared on common paths, and decision context is captured. This is one of the strongest areas. |
| Thesis monitoring | 7.9 | Structured assumptions, breakers, evidence mapping, immutable versions, reviews, and Today integration form a real product differentiator. The evidence supply is the constraint. |
| Forecasting / prediction markets | 7.0 | The architecture correctly separates venue, market, model, and user beliefs. The live market dataset is substantial, but relevance mapping and calibration are not yet mature enough to lead the product. |
| AI usefulness | 6.3 | Tool routing is bounded and calculations are deterministic. Current runtime availability, context contamination seen in a saved conversation, prompt-injection hardening, and lack of model fallback weaken trust. |
| Daily usefulness | 5.2 | Today has the right philosophy but insufficient event coverage, no external notification loop, and a dangerous risk of saying “nothing material changed” when coverage is incomplete. |
| Trust / explainability | 8.1 | The fact/model/market/belief/interpretation vocabulary, lineage, point-in-time snapshots, immutable decisions, and missing-data rules are unusually strong. |
| UX clarity | 6.9 | Primary navigation is much clearer. Dense research tables, duplicated chat surfaces, many Research tabs, and loading states still demand too much product knowledge. |
| Differentiation | 7.4 | The persistent decision system is genuinely different from a finance dashboard or a generic chatbot. Generic research and Learn are not differentiated. |
| Data quality / coverage | 5.3 | Prices, macro, SEC fundamentals, news, and prediction snapshots have useful breadth. Earnings expectations, events, transcripts, and valuation history are launch-significant gaps. |
| Production readiness | 3.1 | The deployed frontend has no production API path, uses a second auth system internally, and has not passed live/deployed smoke tests. Runtime jobs and rate limiting are single-process. |

### Would I launch today?

**NO — important issues remain.**

I would not invite external beta users to the currently published product. The most important reason is not polish: the deployed frontend has no production data plane. It is protected by Sites/ChatGPT sign-in, then the application separately expects Supabase login and a FastAPI service that defaults to the user’s own loopback address. The current local UI also demonstrates that authenticated shell availability can be mistaken for research-engine availability.

After the top three launch blockers are fixed—deployable API/auth architecture, coverage-aware Today behavior, and minimum event/earnings data—I would launch a small, free, instrumented beta to 10–25 target users.

---

## 2. What EagleEyes is actually for

In plain English:

> EagleEyes helps a serious self-directed investor remember why they own something, detect evidence that changes that reasoning, understand the portfolio consequences, and learn whether their past decisions were well reasoned.

It is not primarily a stock screener, a brokerage, or a market-news app. It is an investing **decision-memory and monitoring layer**.

### Strongest real-world workflows

#### 1. Review whether a holding’s thesis changed

- **Trigger:** New fundamentals, news, a probability shift, a scheduled review, or earnings.
- **User question:** “Did anything happen that strengthens, weakens, or breaks what I believed?”
- **Workflow:** Today or Research → What Changed → Thesis Monitor → review mapped assumptions/breakers → confirm a review or record a decision.
- **Output:** Evidence change set, monitor status, source lineage, and an immutable reviewed state.
- **Why it matters:** It prevents price movement and recency bias from silently replacing the original investment case.

This is the best conceptual workflow, although current earnings/event data prevents it from reaching its potential.

#### 2. Diagnose hidden portfolio dependence

- **Trigger:** Portfolio review, a proposed addition, or a macro event.
- **User question:** “What am I actually exposed to beyond ticker weights?”
- **Workflow:** Portfolio → deterministic diagnostics → risk contribution, correlation clusters, shared economic dependencies, thesis health, scenario and prediction-market exposure.
- **Output:** Ranked concentrations, effective holdings, factor mechanisms, affected holdings, coverage, and methodology.
- **Why it matters:** A portfolio with many tickers can still be one bet on rates, AI capital spending, consumer demand, or another shared driver.

#### 3. Prepare for and record an investment decision

- **Trigger:** Buy, add, hold, reduce, sell, avoid, or watch.
- **User question:** “What do I believe, what evidence supports it, and what would prove me wrong?”
- **Workflow:** Research/Portfolio → guided thesis draft → user confirmation → Decision Lab where relevant → immutable decision record.
- **Output:** Thesis version, assumptions, risks, catalysts, breakers, confidence, price/evidence/portfolio context, and review date.
- **Why it matters:** It creates a usable record before hindsight changes the story.

#### 4. Compare personal expectations with market-implied expectations

- **Trigger:** A macro, regulatory, political, or company event matters to a holding.
- **User question:** “What is the market pricing, why do I disagree, and what does that disagreement expose?”
- **Workflow:** Market Expectations → grouped contracts and quality → relevant holding/thesis mapping → user forecast → scenario impact → later calibration.
- **Output:** Market probability, user belief, change in percentage points, mapped exposure, and forecast history.
- **Why it matters:** It makes an assumption explicit and scoreable instead of leaving it as vague conviction.

#### 5. Review decision quality after the outcome

- **Trigger:** A review horizon, closed position, or repeated mistake.
- **User question:** “Was my process good even if the return was bad, and what do I repeatedly misjudge?”
- **Workflow:** Decision Journal → reconstruct decision-time context → compare outcomes and assumptions → retrospective → pattern and calibration view.
- **Output:** Process-versus-outcome assessment, assumption review, forecast accuracy, and recurring patterns.
- **Why it matters:** This is how the product compounds in value over years rather than only answering today’s question.

---

## 3. Why use this instead of ChatGPT?

### Strong differentiation from ChatGPT

1. **Immutable, point-in-time decision memory.** A user can upload a note to ChatGPT, but ChatGPT does not automatically preserve thesis versions, decision-time evidence, review boundaries, later outcomes, and calibration as one queryable system.
2. **Continuous evidence-to-thesis monitoring.** ChatGPT can analyze a supplied packet. It does not natively determine what changed since a specific prior review, map it to saved assumptions, suppress immaterial price noise, and maintain review state.
3. **Deterministic portfolio calculations with persistent holdings.** A spreadsheet upload can reproduce one analysis, but EagleEyes can consistently apply the same calculation versions, coverage rules, current holdings, historical paths, and lineage across Today, Research, Ask, and retrospectives.
4. **User-versus-market forecast history.** ChatGPT can discuss market odds; EagleEyes can store the user belief and contemporaneous market/model state, resolve it later, and measure calibration.
5. **Cross-time learning.** The decision journal can identify patterns across decisions without the user repeatedly curating and uploading the complete history.

### Moderate differentiation

- Portfolio-aware company research and fit analysis.
- Prediction-market evidence mapped to holdings and theses.
- Earnings-to-thesis interpretation, once the missing expectations/guidance/transcript data exists.
- Source lineage and explicit missing-data states.
- A persistent, editable research board built from approved tools.

ChatGPT could approximate each with a carefully prepared data package. EagleEyes’ advantage is lower repeated setup and stronger consistency, not uniquely superior prose.

### Weak or no differentiation

- Generic “explain this stock” research.
- Macro explanations and scenario narratives without portfolio/thesis context.
- Standalone investing education.
- News summarization.
- A configurable terminal by itself.
- One-off stock comparisons when the user has no saved thesis or portfolio.

### The paying reason

The strongest reason to pay is: **“EagleEyes remembers my investment reasoning and watches the evidence and portfolio consequences continuously, so I do not have to reconstruct the case every time.”**

If EagleEyes is only a better-formatted AI answer, ChatGPT wins. If it reliably becomes the memory and monitoring system for the user’s actual decisions, EagleEyes has a structural advantage.

---

## 4. Why use this instead of finance apps?

| Category | They are better at | EagleEyes is better at | Remaining gap |
|---|---|---|---|
| Robinhood / brokerages | Execution, positions, tax lots, live prices, account truth, deposits, notifications | Reasoning history, thesis breakers, shared dependencies, decision retrospectives | No read-only broker sync; current holdings and transaction history require maintenance |
| Yahoo Finance | Broad quotes, calendars, simple watchlists, news breadth, low-friction discovery | Personalized thesis relevance and evidence history | EagleEyes has zero validated events today and narrower low-friction quote coverage |
| Seeking Alpha | Contributor research, earnings transcripts, estimates/revisions, company coverage | User-specific thesis monitoring and process learning | EagleEyes lacks exactly the earnings/estimate/transcript data that makes event review credible |
| Morningstar | Fund data, style analysis, portfolio allocation, long-standing methodology | Decision memory, user beliefs, prediction markets, thesis monitoring | ETF holdings and look-through coverage are provider-dependent and less mature |
| Koyfin | Market dashboards, financial statements, estimates, charting, breadth | Persistent investment workflow and personal decision context | EagleEyes should not compete on terminal breadth; current UI sometimes still tries to |
| TradingView | Charts, alerts, technical workflow, community, speed | Long-horizon reasoning, portfolio/thesis monitoring | Technical analysis and real-time alerting are not competitive |
| Finviz | Fast screening and market overview | Evidence-to-decision continuity | Screening breadth and speed are weaker |
| Bloomberg-style tools | Data breadth, timeliness, estimates, auditability, workflows, reliability | Simpler self-directed decision memory at a radically lower complexity | EagleEyes is not remotely comparable on data or operations and should not position that way |

EagleEyes is primarily **an additional layer on top of a brokerage and one or more research/data products**. It should not claim to replace the system of record for holdings, execution, quotes, transcripts, estimates, or broad discovery. Over time it may replace a spreadsheet, note-taking system, investment journal, and several manual monitoring routines.

---

## 5. Ideal user

The strongest initial customer is a serious, long-horizon self-directed investor who:

- Owns roughly 8–25 individual equities/ETFs, often with meaningful concentration.
- Has a multi-year horizon but makes several buy/add/trim/sell/watch decisions each quarter.
- Reads earnings, company filings, investor letters, or paid research.
- Uses a brokerage plus Yahoo/Seeking Alpha/Koyfin/TradingView and a spreadsheet or notes app.
- Worries about forgetting the original thesis, reacting to noise, hidden factor overlap, and repeating decision mistakes.
- Is comfortable writing or confirming a short thesis and reviewing it at earnings or a set cadence.
- Values process and evidence more than trade ideas.
- Has enough at stake that avoiding one poorly reasoned decision is worth meaningful time and a subscription.

Portfolio dollar value matters less than behavior, but the likely early paid segment has approximately $100k–$2m in self-directed assets. Below that, the maintenance cost and willingness to pay fall; far above that, professional workflow/data requirements rise.

### Not a good fit

- Complete beginners who need a simple savings/investing path rather than an evidence terminal.
- Passive index investors who rarely make security-level decisions.
- Day traders and options scalpers who need real-time execution, charting, and microstructure.
- Institutional PMs who require entitlements, compliance, team workflows, full estimates, and enterprise data.
- Users unwilling to confirm a thesis, decision, or review date.
- Users primarily looking for stock picks or autonomous trading.

---

## 6. Daily, weekly, and event-driven use

### Daily

Today could justify a 2–5 minute daily check if it consistently shows only:

- a breaker or weakening thesis;
- a material forecast-probability change linked to exposure;
- a high-risk-contribution change;
- a verified upcoming event;
- a due review.

The ranking model is directionally strong: it combines materiality, thesis/portfolio relevance, evidence quality, urgency, and exposure, and price movement alone does not create an alert. The current product is not ready to earn daily trust because events are empty, market snapshots are disabled, in-app alerts provide no reason to open the app, and “nothing material changed” can appear while the research engine is offline or evidence coverage is missing.

### Weekly

A credible weekly ritual exists: review Today, inspect due theses, scan portfolio dependencies/risk contribution, compare watchlist changes, and close or snooze items. It is not yet packaged as one explicit weekly review with completion state.

### Earnings and events

This should be EagleEyes’ highest-frequency high-value moment. Structurally, actuals → expectations/guidance/revisions → What Changed → Thesis Monitor → Decision is excellent. In practice, zero consensus, guidance, revisions, transcripts, and market events makes it incomplete.

### Decision time

Yes. Research links into thesis/decision context, the guided thesis workflow is relatively light, and Decision Lab keeps comparisons consistent. Users will open it before a consequential add/reduce/sell only after data availability and latency become dependable.

### Retention verdict

The product has the foundations of retention, but not enough dependable recurring value today. Retention will come from a trusted attention feed, event-driven reviews, due-decision reminders, and accumulated decision history—not from adding more research tabs.

---

## 7. Core loop review

| Transition | Verdict |
|---|---|
| Research → Thesis | Supported by contextual links and an assisted, user-confirmed thesis draft. Still feels like moving into a different module. |
| Thesis → Evidence Change | Strong data model and snapshot semantics. The user’s baseline is preserved. |
| Evidence Change → Thesis Monitor | Strong logic, weak input breadth. Missing earnings expectations/events can make “insufficient” too common. |
| Thesis Monitor → Forecasting | Conceptually linked through relevant markets, but company/event mapping depends partly on explicit static rules and stored contracts. |
| Forecasting → Portfolio Impact | Useful where holdings map to event factors; should disclose mapping coverage more prominently. |
| Portfolio Impact → Decision | Strong. Alternatives, “do nothing,” and decision capture coexist. |
| Decision → Today Monitoring | Strong architecture, but Today needs a completeness gate and reliable scheduled inputs. |
| Monitoring → Retrospective | Durable and differentiated, but benefits arrive only after months and require capture discipline. |

**Weakest transition:** real-world evidence/earnings → What Changed → Thesis Monitor. The workflow exists, but the current data cannot reliably answer what changed after an earnings event.

The system now feels more like one workflow than separate products, but the user still needs to understand Research subproducts, Thesis Monitor, Market Expectations, Decision Lab, Journal, and multiple chat/board concepts. The application should explain the next action contextually and stop teaching the module architecture.

---

## 8. Today review

Today’s product philosophy is correct. It prioritizes thesis and portfolio relevance, caps the main attention list, treats no change as valid, distinguishes upcoming events, and suppresses price-only noise.

What works:

- Explicit ranking inputs and deterministic materiality.
- Thesis-breaker override.
- Portfolio-weight/risk relevance.
- Read/dismiss/snooze/resolve states.
- “Nothing material changed” as an intended valid outcome.
- Separation of broad market context from action-worthy evidence.

What prevents trust:

1. **No completeness gate.** “Nothing material changed” must never be shown as a confident conclusion when the engine is offline or essential event/earnings/market coverage is unavailable. The correct state is “No material change detected in the evidence currently available,” with a visible coverage score.
2. **Zero validated events.** Upcoming event coverage is not useful today.
3. **No push/digest loop.** In-app-only alerts cannot create daily behavior if users must open the app to learn whether anything happened.
4. **Current loading behavior.** Provider Health can remain on “Checking…” and Today can simultaneously show an empty conclusion. Every request needs a bounded timeout and terminal error/fallback state.
5. **Portfolio reconciliation.** The initial Today experience said no saved portfolio while Portfolio displayed the five default holdings. Even if transient, source-of-truth reconciliation must be atomic before attention is displayed.

Would the ideal user trust Today now? **No.** They may like the ranking, but they cannot yet trust the absence of an alert.

---

## 9. Research review

The company-research page is framed around the correct six questions: business trend, balance-sheet risk, expectations, valuation, story changers, and portfolio fit. It also correctly separates quality, valuation, price behavior, sentiment, macro sensitivity, and fit rather than collapsing everything into a magic score.

The current product has the right amount of *categories* but too much visible implementation detail. Detailed cards are useful; broad tables and eleven Research tabs create cognitive load. Expert-only numeric components are appropriately hidden by default.

Material missing information, in priority order:

1. Consensus revenue/EPS and estimate revisions.
2. Management guidance and prior-guidance comparison.
3. Earnings transcript excerpts with cited speaker/context.
4. Historical valuation ranges and peer-relative valuation history.
5. Reliable earnings and catalyst calendar.
6. Clear company-specific market-expectation mapping coverage.

More technical indicators or more ratios would not materially improve decisions. Data that captures **expectations and changes in expectations** would.

---

## 10. Thesis Monitor review

Thesis Monitor is now a real differentiator. It includes:

- versioned thesis summaries and cases;
- structured assumptions with importance and optional deterministic conditions;
- catalysts, risks, and breakers;
- evidence mapping and evidence-quality/freshness states;
- deterministic evaluation before qualitative AI synthesis;
- immutable review history and explicit baselines;
- Today ranking and decision-journal integration.

The main risk is user effort. Most self-directed investors will not maintain a long formal thesis template for every holding.

### Minimum viable thesis workflow

Capture only five things:

1. One sentence: why this belongs in the portfolio.
2. Two or three “must remain true” assumptions.
3. One breaker.
4. One review cadence or next event.
5. Confidence and decision type.

EagleEyes can suggest risks/catalysts and metrics from current evidence, but the user must confirm beliefs. Maintenance should be a review of diffs—confirm, edit, or dismiss—not repeated form entry.

---

## 11. Prediction markets and forecasting

Prediction markets are a **real but secondary differentiator**, not a novelty, because EagleEyes does more than display odds:

- keeps Kalshi and Polymarket separate;
- groups genuinely comparable contracts;
- calculates probability changes in percentage points;
- records market quality and provider disagreement;
- maps events to theses and holdings;
- lets a user record a separate belief;
- preserves contemporaneous market/model/user probabilities;
- supports later resolution and calibration.

The current dataset is meaningful: 6,892 Kalshi snapshots across 4,185 stored markets and 4,106 Polymarket snapshots across 167 markets, fresh on the review date. However, provider-health ingestion logging says both venues are “awaiting data,” revealing a monitoring-contract bug despite fresh underlying data.

High-value workflows:

- Rate-cut expectations linked to duration-sensitive holdings.
- Regulatory/export events linked to a semiconductor thesis.
- Election/policy outcomes linked to sectors or company catalysts.
- Macro recession/inflation states used as scenario weights, not as truth.
- User probability disagreement recorded before the outcome.

Risks:

- Market liquidity and contract wording vary sharply.
- Static company/sector rules can overstate relevance.
- Multiple contracts may not share resolution criteria.
- A probability is a price-derived belief, not an objective forecast.
- Calibration needs enough resolved, comparable forecasts before it is meaningful.

Do not add prediction-market trading or a generic odds feed. Improve relevance, resolution tracking, quality filters, and calibration.

---

## 12. Portfolio intelligence

The strongest outputs are:

1. Risk contribution versus weight.
2. Effective holdings and concentration.
3. Shared economic dependencies with explicit mechanisms.
4. Correlation clusters with sample counts.
5. Thesis-health coverage and holdings without theses.
6. Upcoming event/forecast exposure by portfolio weight.
7. Scenario contributors where attribution is genuinely available.

These meaningfully exceed standard brokerage analytics.

The most complex outputs for the target user are covariance conditioning, shrinkage intensity, effective rank, regime models, and promotion gates. They belong in Expert/Advanced, not the decision surface.

Trust caveats:

- Pearson historical correlation is unstable and is not causal.
- Shared economic dependencies are explicit company/sector/industry rules, not estimated betas.
- Risk contribution depends on available price history and covariance methodology.
- Sparse scenario estimates shrink to proxies/priors.
- “Current-weight historical performance” is hypothetical, not account performance.
- Current classification and fundamental coverage must be shown as portfolio-weight coverage, not merely record counts.

The methodology is honest enough for beta if these caveats remain close to the result.

---

## 13. Earnings intelligence

The implemented experience has the correct contract: actual versus consensus, aligned period changes, margins, guidance changes, revisions, transcript evidence, and mapped thesis impact. Missing fields are explicitly marked unavailable rather than unchanged.

The current data makes the feature largely skeletal:

- 143,925 stored fundamental periods.
- 0 periods with consensus fields.
- 0 with guidance.
- 0 with estimate revisions.
- 0 transcript documents.
- 0 validated market events.

Therefore, EagleEyes cannot yet reliably answer “What actually changed this quarter?” It can report historical filings and deterministic deltas, but not the expectation gap, management outlook change, post-report revision, or transcript evidence.

**Improved earnings/event data is a top-three product priority and a beta gate for positioning EagleEyes around thesis change.**

---

## 14. Decision Journal and retrospectives

The Journal can create significant long-term value because it stores:

- an append-only decision;
- the exact thesis version;
- decision-time evidence and portfolio context;
- confidence and expected horizon;
- user and market forecasts;
- later deterministic outcomes;
- assumption-by-assumption review;
- process versus outcome distinction;
- recurring patterns and calibration.

Normal investors will not write lengthy retrospectives. Capture should be triggered and prefilled:

- “You expected X; Y happened.”
- “These two assumptions strengthened; one is unresolved.”
- “Was the decision process good? Confirm/edit.”
- one optional free-text lesson.

This is a potential moat, but only after enough users accumulate high-quality decisions over 6–18 months. The schema is not the moat; the longitudinal, trusted user dataset and review habit are.

---

## 15. Ask EagleEyes

Ask is closer to **B: a conversational interface to a persistent investment-decision system** than a generic finance chatbot. Intent routing includes change, thesis, earnings, portfolio risk, scenario, forecast, Today, and retrospective tools. Tool calls are allowlisted and capped at three with no replans; deterministic outputs and sources remain separate from narrative.

Strengths:

- Persistent conversations and page context.
- Bounded tools, time budgets, and explicit tool success states.
- Direct actions back to Research, Decisions, and Portfolio.
- Evidence-only prompts and deterministic answer review.
- Template narrative fallback for dashboard boards.
- Partial-result preservation.

Weaknesses:

- The live/local research engine was offline during review, so the primary experience was not usable end to end.
- A saved conversation about a Balanced alternative displayed a response about Micron/memory prices, suggesting prior-context contamination or an incorrect saved summary. This needs a targeted regression test.
- The general chat has no useful model fallback when Gemini is absent; some board narration does.
- The prompt says to use only evidence, but untrusted news/transcript text is not clearly wrapped as hostile content and stripped of embedded instructions.
- Authentication validation calls Supabase Auth on every request, adding latency and making Auth availability a dependency for every tool.
- Follow-up context uses recent messages plus a summary, but there is no displayed “context boundary” when an old entity is carried into a new question.

Conceptual question support:

| Question | Current support |
|---|---|
| What changed with MSFT? | Strong routing; usefulness depends on stored changes and earnings data. |
| Why is my portfolio risky? | Strong deterministic portfolio tool. |
| Which thesis is weakening? | Strong monitor tool if theses and current evidence exist. |
| What markets matter most to NVDA? | Moderate; explicit mapping exists but relevance coverage must be disclosed. |
| What changed after earnings? | Structurally supported, currently data-starved. |
| Why did I originally buy this? | Strong when a decision snapshot exists. |
| What assumptions do I repeatedly get wrong? | Differentiated, but only after sufficient journal history. |

---

## 16. Learn

Learn is well bounded: repository-versioned lessons, deterministic labs, private progress, no leaderboard, and contextual explanations. It should remain **both contextual and secondary**:

- Keep a small standalone learning hub for onboarding and foundational concepts.
- Make most education appear beside a live concept: risk contribution, estimate revisions, thesis breaker, probability percentage points, drawdown, and scenario limitations.
- Do not expand into a broad consumer financial-education product.

Learn is useful for comprehension and trust, but it is not a reason the ideal initial customer will choose or pay for EagleEyes.

---

## 17. Prioritized feature gaps

| Priority | Feature | User problem and example workflow | Why current product is insufficient | Impact | Complexity |
|---|---|---|---|---|---|
| MUST | Coverage-aware attention completeness gate | User opens Today and needs to know whether “no change” means no change or no data | Current Today can show no material change while the engine/events are unavailable | Prevents false reassurance; essential trust | Medium |
| MUST | Production earnings and event evidence | After earnings, user needs actual vs consensus, guidance change, revisions, transcript evidence, and event timing | Contracts exist but every critical field is currently empty | Makes the core thesis-change loop real | High; mostly provider/data work |
| SHOULD | One-screen review diff | User sees changed evidence, mapped assumptions, prior status, and confirms the new review without opening several modules | Current components exist but the loop still feels modular | Higher thesis maintenance and retention | Medium |
| SHOULD | Opt-in material-change digest | User should not need to open the app to discover whether there is an alert | Alerts are in-app only | Creates event-driven return behavior | Medium, after attention trust is proven |
| LATER | Read-only broker synchronization | Holdings and transaction truth drift when maintained manually | CSV/manual import works but creates ongoing effort | Better activation and account performance | High due integrations/security |
| DO NOT BUILD | Trade execution, social feed, stock-pick marketplace, autonomous portfolio manager | These attract different jobs and materially increase regulatory/trust scope | They do not improve the decision-memory loop | Negative focus and risk | Very high |

---

## 18. Remove, hide, or consolidate

| Area | Recommendation | Reason |
|---|---|---|
| Today | KEEP PRIMARY | Core retention surface. |
| Portfolio | KEEP PRIMARY | Persistent context and differentiated analysis. |
| Research | KEEP PRIMARY | Required evidence workspace, but reduce visible sub-tab count. |
| Decisions | KEEP PRIMARY | Owns thesis, monitoring, journal, and retrospective moat. |
| Ask EagleEyes | KEEP PRIMARY | Conversational interface to the system, if reliability improves. |
| Plan & profile | KEEP SECONDARY | Useful constraints, not daily work. |
| Learn | KEEP SECONDARY | Supports comprehension; not core PMF. |
| Advanced terminal, diagnostics, validation, lineage | MOVE TO EXPERT | Important for auditability, distracting for most users. |
| Provider Health | MOVE TO EXPERT | Operational/debug surface. User-facing freshness should appear contextually. |
| Research chat + global Ask + Portfolio Assistant | CONSOLIDATE | They should be contextual entry points into one conversation system with explicit workspace context, not three assistant products. |
| Sectors, Themes, Compare, Watchlist | CONSOLIDATE | Present as discovery filters/saved views rather than separate top-level Research products. |
| ETF Builder, Stock Basket, Model Portfolio Builder | KEEP SECONDARY / EXPERT | Useful, but they pull the product toward portfolio construction rather than monitoring. Do not lead onboarding with them. |
| Generic market terminal widgets | MOVE TO EXPERT | Finance apps do this better; retain for audit/power use. |
| Duplicate Simple/Detailed concepts in docs | REMOVE | Current UI correctly has Detailed default and Expert override; documentation still contains outdated three-level language. |

---

## 19. Data coverage review

| Gap | User impact | Current fallback / honesty | Better source needed? | Priority |
|---|---|---|---|---|
| Consensus estimates | Cannot distinguish reported growth from an expectations beat/miss | Explicitly unavailable; feature remains honest but incomplete | Yes | MUST |
| Estimate revisions | Cannot answer how the market’s forward view changed after an event | Explicitly unavailable | Yes | MUST |
| Guidance | Cannot compare management’s outlook with its prior outlook | Explicitly unavailable | Yes, plus structured extraction | MUST |
| Earnings calendar | Today cannot prepare users for events; current stored count is zero | “No validated events” is honest, but not useful | Yes | MUST |
| Transcripts | No cited management explanations or qualitative change evidence | Empty transcript evidence | Yes | MUST/SHOULD |
| Historical valuation | “What am I paying?” lacks a robust through-cycle anchor | Current/peer metrics where present; partial fields disclosed | Prefer provider or versioned derived history | SHOULD |
| Fundamentals | 515 securities, deep period count; freshness currently July 3 for the aggregate status | SEC/stored fallback is useful, but quarter recency and normalized metrics vary | Improve normalization/refresh before broadening | SHOULD |
| News | 3,109 documents across 2,092 mapped securities; freshness is good | Stored evidence with source/freshness | Breadth and deduplication matter more than raw count | SHOULD |
| Prediction markets | Fresh and substantial snapshots, but health logs incorrectly say awaiting data; relevance mapping varies | Market quality and missing comparison disclosed | Fix monitoring first; selective provider improvements later | SHOULD |
| Macro | Strong depth and point-in-time design | Honest proxy/vintage labeling | No immediate provider change needed | KEEP |
| Price history | Strong recent breadth; only a smaller subset has long Tiingo history | Coverage contract and proxy/shrinkage warnings are good | Extend long-history coverage selectively | SHOULD |
| Historical portfolio | Actual performance unavailable without transactions/cash flows | Clearly labeled hypothetical; optional ledger exists | Broker/transaction import later | LATER |

**Is data coverage a bigger problem than missing product features? Yes.** The system already has more features than it can reliably feed. The highest-value work is data and reliability, not another module.

---

## 20. Production readiness — backend

### What is strong

- FastAPI endpoints are organized around typed Pydantic contracts.
- Private routes require a validated Supabase bearer token.
- User rows are filtered by user ID in server queries; direct tables have RLS and anonymous grants revoked.
- New thesis, evidence, decision, review, and forecast records are append-only where appropriate.
- All migrations are applied; migration validation and status tooling exist.
- Provider calls generally have timeouts and bounded retries.
- Cache entries are versioned/expiring; missing results are not silently neutral.
- Request IDs, latency metrics, structured logs, cache-control, body limits, and basic security headers exist.
- Scheduled ingestion has concurrency controls and timeouts.

### Launch blockers and material risks

1. **No deployed API architecture.** The Sites Worker serves only the frontend. Hosted environment variables are empty, no tunnel exists, and the client defaults to loopback. Hosted cross-origin API would also be rejected because CORS only allows localhost unless the architecture is changed to same-origin/proxy.
2. **Two unintegrated authentication systems.** Sites requires ChatGPT sign-in; the app then uses a separate client-side Supabase login. The SIWC helper exists but is unused. External users would face double authentication and identity mapping is undefined.
3. **In-process job execution.** Dashboard jobs are persisted, but execution uses local thread pools. A process restart can leave jobs in nonterminal states with no startup recovery/lease/heartbeat worker.
4. **In-memory rate limiting.** It is per process and trusts the forwarded IP header. It will not provide consistent protection across replicas.
5. **No demonstrated deployed smoke.** The production test exists but is skipped without a deployed API token/URL. Live-provider tests are also skipped in the normal suite.
6. **No CI quality gate.** Repository workflows ingest data but do not run build, typecheck, backend, E2E, migration validation, or a deploy smoke on changes.
7. **Backup/recovery not proven.** SQLite backup exists for migration, but Supabase backup/PITR assumptions, restore targets, and an actual restore drill are not documented.
8. **Provider-health inconsistency.** Fresh prediction snapshots coexist with “awaiting data” because ingestion status is incomplete. Monitoring cannot yet be treated as authoritative.

---

## 21. Production readiness — AI

### Positive controls

- Allowlisted tool routing; maximum three Ask tools, no automatic replans.
- Overall tool budget capped at 20 seconds; default 10 seconds.
- Calculations remain in deterministic code.
- Source IDs and claim types are included in prompts.
- Required-evidence verification blocks unsupported narration.
- Missing, stale, or partial evidence is explicitly handled.
- Dashboard narratives have a deterministic template fallback.

### Remaining issues

- Saved conversation context showed an apparent entity/topic carryover. Add conversation-isolation and summary-reset tests using the exact failing pattern.
- General Ask has no production fallback when Gemini is unavailable; it returns an error rather than a useful deterministic summary.
- No robust prompt-injection boundary for untrusted documents/news/transcripts. Content should be tagged as quoted evidence, stripped of active instructions where possible, and the model told that embedded instructions are hostile data.
- No explicit model outage/fallback policy for chat, thesis drafting, and learning tutor as separate capabilities.
- Tool timeouts cancel waiting, not necessarily underlying thread work.
- Per-request token/cost budgets exist in configuration but no user-level cost quota or anomaly control is evident.
- Privacy policy, retention/deletion behavior for prompts and provider/model logging, and model-training terms are not surfaced to the user.

Ask is safe enough for a controlled beta **after** runtime reliability and injection/context tests are added. It is not safe enough to frame as personalized financial advice or as a production decision authority.

---

## 22. Production readiness — frontend

### Strengths

- Clear five-destination primary navigation.
- Responsive rules exist for the shell and dense workspaces; primary nav becomes a bottom bar under 850px.
- Reduced-motion support.
- Good empty-state and stale/partial-state vocabulary.
- Consistent evidence/method/lineage design.
- Browser tests cover login, import, research, analysis, builders, Decision Lab, thesis creation, boards, partial failure, and user isolation.

### Gaps

- The real authenticated runtime can remain indefinitely in loading states when API/auth dependencies fail.
- The build emits a >500 kB chunk warning. Dashboard and workspace implementations need code splitting before wider use.
- Browser E2E is desktop-only and fixture-backed. There is no mobile device project, keyboard-only/a11y audit, or real API E2E.
- Dense horizontal tables deliberately scroll; several are 650–1,450px minimum widths. This is survivable on mobile, not a good mobile decision workflow.
- The bottom navigation hides the sidebar footer, so connection state and safety messaging disappear on mobile.
- Many controls use tiny 7–9px supporting text, which is a readability/accessibility concern.
- Primary actions and secondary menus change by workspace; deep-link and back-button behavior is contract-tested but the app remains a large client-side state surface.
- Landing/Sites auth and Supabase auth are not one continuous experience.

Desktop is beta-quality with fixtures. Mobile is responsive, but not product-quality for dense analysis and has not been verified in device E2E.

---

## 23. Financial-product trust and risk

Key risks and safeguards:

| Risk | Safeguard |
|---|---|
| AI interpretation mistaken for advice | Keep trade execution disabled; label interpretation and show alternatives. Add a first-run acknowledgment and contextual “research, not a recommendation” near decision outputs. |
| Market probability treated as objective truth | Always show venue, liquidity/quality, contract wording, resolution criteria, and disagreement. Use “market-implied.” |
| Scenario estimate mistaken for forecast | Use ranges, historical sample counts, shrinkage/proxy details, and “association, not forecast” close to the number. |
| False precision | Prefer qualitative states by default; round probabilities/portfolio outcomes appropriately; show uncertainty and coverage. |
| Stale or partial data | Add a decision-surface coverage gate, not only an expandable methodology panel. Never render “nothing changed” without coverage status. |
| Provider error | Retain last validated snapshot with explicit timestamp; never merge partial data into a neutral conclusion. |
| LLM overstatement | Deterministic evidence gate, sentence-level citations, unsupported-claim review, and a “report a problem” control attached to the exact answer/tool run. |
| Personalized-advice boundary | Avoid “you should buy/sell”; explain tradeoffs and user-defined constraints. Obtain legal review before paid personalized guidance. |

Disclosures should be short and contextual. A giant footer disclaimer does not fix an overconfident output.

---

## 24. Production launch checklist

### Must fix before any external users

1. Deploy a reachable API/data plane, configure same-origin routing or correct CORS, and remove the loopback fallback from production builds.
2. Choose and implement one external identity model: Sites/ChatGPT mapped to application users, or a deployment surface where Supabase is the only gate. Eliminate double login.
3. Add a Today completeness gate and bounded terminal failure states; never show “nothing material changed” while required sources are unavailable.
4. Populate and verify a minimum event/earnings dataset for the beta universe, or remove earnings-change claims from beta positioning.
5. Run deployed production smoke plus live provider/RLS tests using dedicated test users.
6. Add CI for build, typecheck, backend tests, E2E, migration validation, and deploy smoke.
7. Add job recovery/expiry for interrupted nonterminal Ask/board jobs.
8. Commit and version the release candidate; deploy only the exact CI-tested commit.

### Can launch in beta with these limitations

- Manual/CSV holdings rather than broker sync.
- In-app-only alerts, if users are told to use weekly/event reviews.
- Limited supported security universe with disclosed coverage.
- Partial ETF holdings and historical valuation.
- No actual performance without transactions/cash flows.
- Heuristic economic-dependency mapping with visible method.
- No mobile-first dense analysis; support desktop/tablet as the beta target.
- Small-sample forecast calibration labeled unavailable.

### Post-launch improvements

- Read-only broker connections.
- Email/mobile digest after alert precision is proven.
- Broader consensus/transcript/ETF data.
- Durable queue workers and horizontal scaling.
- Faster bundles and route-level code splitting.
- Contextual Learn expansion.
- Team/collaboration only if individual PMF is established.

---

## 25. Pricing and value test

There is enough differentiated *potential* to charge, but not enough production reliability or recurring evidence quality to charge today.

Users would pay for:

- reliable thesis-breaker/evidence-change monitoring;
- portfolio-specific event and hidden-risk attention;
- a durable decision journal and retrospective pattern engine;
- user-versus-market forecast tracking;
- not having to reconstruct context across a brokerage, spreadsheet, notes, research sites, and ChatGPT.

The current product is better suited to a free, invite-only beta. Before paid launch it needs dependable Today accuracy, production earnings/events, a real hosted runtime, low-friction onboarding, and evidence that target users complete multiple thesis reviews and return around events.

---

## 26. Competitive positioning

### Positioning statement

For serious self-directed investors who manage individual holdings, EagleEyes is the decision-memory and monitoring workspace that connects each holding’s thesis to changing evidence, portfolio consequences, market-implied expectations, and later outcomes.

### One-sentence value proposition

**Know what changed, whether it changes your thesis, and what it means for the rest of your portfolio—without losing the reasoning behind the decision.**

### 30-second explanation

Your brokerage tells you what you own and what moved. Research apps give you data and opinions. EagleEyes remembers why you made each investment decision, monitors the evidence and assumptions that matter, maps changes to portfolio risk and market expectations, and later helps you distinguish a good process from a lucky outcome. Calculations are deterministic and the AI explains sourced results rather than inventing financial numbers.

### Why not ChatGPT?

ChatGPT can analyze a packet you prepare. EagleEyes persistently maintains the holdings, thesis versions, decision-time evidence, review history, forecast history, and portfolio consequences so the user does not rebuild context every time.

### Why not Yahoo or Robinhood?

They are better for quotes, news, account truth, and execution. EagleEyes is for the reasoning those products do not preserve or monitor.

### Why not Seeking Alpha or Koyfin?

They are better for research breadth, estimates, transcripts, and market terminals. EagleEyes applies evidence to the user’s own thesis, portfolio dependencies, decisions, and retrospectives.

### What EagleEyes should never try to be

A brokerage, day-trading terminal, generic market homepage, autonomous stock picker, social investing network, or substitute for professional tax/legal advice.

---

## 27. Ranked priorities

| Rank | Priority | Impact | Effort | Why | Blocks launch? |
|---:|---|---|---|---|---|
| 1 | Deploy and test one production API/auth architecture | Very high | High | Without it, external users cannot use the research system | Yes |
| 2 | Add coverage-aware Today gating and terminal failure states | Very high | Medium | Prevents false reassurance and endless loading | Yes |
| 3 | Acquire/ingest earnings expectations, guidance, revisions, transcripts, and events for the beta universe | Very high | High | Feeds the central evidence-change loop | Yes for current positioning |
| 4 | Add CI plus deployed/live smoke monitoring | High | Medium | Converts a strong local test suite into release confidence | Yes |
| 5 | Commit a release candidate and add interrupted-job recovery/expiry | High | Medium | Makes builds reproducible and Ask jobs operationally safe | Yes |
| 6 | Run 10–15 target-user tests focused on one holding review and one weekly review | Very high | Low/Medium | Validates willingness to maintain theses and what users return for | No, immediately after blockers |
| 7 | Simplify Research and consolidate assistant entry points | High | Medium | Reduces “multiple products” feeling without a redesign | No |
| 8 | Optimize thesis maintenance around a one-screen diff review | High | Medium | Turns the differentiator into a repeatable habit | No |
| 9 | Fix monitoring truth and expose weighted coverage | Medium/High | Medium | Provider Health currently contradicts fresh stored data | Yes if used operationally |
| 10 | Add desktop performance/code splitting, mobile E2E, and accessibility review | Medium | Medium | Required before broad public use | Beta limitation, not initial invite blocker |

### Top three before beta

1. Production API/auth architecture.
2. Coverage-aware Today plus bounded failure states.
3. Minimum viable events/earnings evidence.

### Top three after beta

1. Observe real thesis-review and decision-journal behavior; simplify based on drop-off.
2. Consolidate Research/Portfolio/global assistant experiences.
3. Add a material-change digest only after alert precision is validated.

### Things to stop building

- New workspace modules.
- More generic market/terminal widgets.
- Additional optimizers or “best portfolio” variants.
- Broad education content disconnected from a live decision.
- Execution, social, and stock-pick features.

---

## Final verdict

1. **Is EagleEyes now a coherent product?** Yes. The center is thesis-aware investment decision memory and monitoring.
2. **Is it differentiated?** Yes, moderately to strongly for serious self-directed investors; weakly for users without saved context.
3. **Single strongest differentiator?** Persistent, point-in-time thesis and decision history connected to changing evidence and portfolio impact.
4. **Biggest remaining weakness?** The real evidence and production runtime are less mature than the feature surface—especially events and earnings expectations.
5. **What would make users return?** A trusted, quiet attention feed around thesis changes, earnings/events, due reviews, and hidden portfolio risk.
6. **Why instead of ChatGPT?** EagleEyes preserves and monitors the structured context over time; ChatGPT requires the user to reassemble it.
7. **Why alongside another finance app?** The finance app supplies quotes, research breadth, account truth, or execution; EagleEyes supplies reasoning continuity and learning.
8. **Is it production-ready?** No.
9. **Would I launch a beta now?** Not the current deployed build. Fix the top three blockers, run live/deployed smoke tests, then launch a small free beta immediately.
10. **What next?** Stop feature expansion. Move into data quality, reliability, user testing, onboarding, and product-market-fit measurement.

The product has crossed the line from “impressive engineering project” to “credible product thesis.” It has not crossed the line to a trustworthy external service. The next phase should prove that users will maintain lightweight theses, trust a coverage-aware Today feed, and return at real decision moments.
