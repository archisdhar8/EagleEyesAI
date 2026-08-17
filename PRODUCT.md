# EagleEyes Product Review

**Document status:** Authoritative product map for the current repository
**Product:** EagleEyes AI
**Positioning:** Private, market-first investment research workspace
**Primary audience:** Self-directed investors who want research, portfolio diagnostics, simulations, and transparent evidence without brokerage execution
**Default presentation:** Detailed
**Last repository review:** August 2026

## 1. Product definition

EagleEyes connects market data, company research, macroeconomic history, prediction markets, portfolio holdings, planning context, deterministic calculations, simulations, and AI explanations in one authenticated workspace.

The product is designed to help a user:

- Understand what changed in markets and why it may matter to their holdings.
- Research a stock, ETF, sector, theme, macro factor, or scenario.
- Diagnose concentration, diversification, historical risk, costs, and incomplete data.
- Compare keeping a portfolio with contribution-only, gradual, immediate, Risk-Controlled, and Balanced paths.
- Build and test ETF allocations or stock baskets.
- Ask natural-language questions and receive both a direct answer and an evidence dashboard.
- Learn investing concepts through audited lessons, deterministic labs, and quizzes.
- Inspect model methodology, validation, provider health, and lineage when needed.

EagleEyes is research and decision-support software. It does not connect to a brokerage, execute trades, select tax lots, guarantee returns, or present one portfolio as universally best.

## 2. Product-wide information architecture

| Primary workspace | Route | Primary user question |
|---|---|---|
| **Today** | `/today` | What moved, what matters to my portfolio, and what deserves investigation? |
| **Plan** | `/plan` | What is this portfolio for, and what personal constraints should research respect? |
| **Portfolio** | `/portfolio` | What do I own, what are its risks, and how do alternative paths compare? |
| **Research** | `/research` | What does the evidence say about securities, funds, market conditions, and scenarios? |
| **Learn** | `/learn` | What should I understand before using the research and portfolio tools? |
| **Ask EagleEyes** | `/ask` | Can the system turn my question into a verified answer and research board? |
| **Advanced** | `/advanced` | Can I build my own terminal and inspect the model, validation, and data system? |

### Compatibility routes

Legacy links remain valid and resolve to the current hierarchy:

| Legacy route | Current destination |
|---|---|
| `/`, `/home`, `/overview` | `/today` |
| `/explore`, `/research` | Research, Stocks |
| `/scenarios` | Research, Scenarios |
| `/optimize` | Portfolio, Portfolio Assistant |
| `/ai-workspace` | Ask EagleEyes |
| `/research-terminal` | Advanced, Research terminal |

## 3. Shared application design

### Authenticated shell

The desktop application uses a persistent left navigation rail and a top workspace bar.

**Left rail**

- EagleEyes brand and “Research terminal” descriptor.
- Seven primary workspace links.
- Research-engine connection state.
- “Learn this” concept glossary.
- Light/dark theme control.
- Sign-out control and signed-in email.
- Permanent reminder that trading is disabled.

**Top bar**

- Current workspace name.
- Workspace-specific primary action.
- Persistent Simple / Detailed / Expert control.
- Latest data-lineage date.
- Optional progress, notice, or failure status below the bar.

### Presentation levels

Presentation changes must never change stored data or numeric calculations.

| Level | Design intent | Content shown |
|---|---|---|
| **Simple** | Fast interpretation | Plain conclusion, why it matters, and one next investigative action. |
| **Detailed** | Default research view | Charts, comparisons, evidence, assumptions, tradeoffs, freshness, and warnings. |
| **Expert** | Audit and model review | Formulas, component scores, sample counts, calculation versions, diagnostics, and lineage. |

Analytical cards follow a common hierarchy:

1. **Answer** — what the result means.
2. **Evidence** — figures, comparisons, dates, and visualizations.
3. **Method** — inputs, formula, versions, assumptions, limitations, and lineage.

### Common states

Every workspace should visibly distinguish:

- Loading versus calculating.
- Current, delayed, end-of-day, cached, and stale data.
- No saved portfolio versus partial portfolio coverage.
- No qualifying evidence versus a provider failure.
- Missing inputs versus a neutral result.
- Complete versus partial-success calculations.
- Hypothetical results versus actual user performance.

## 4. Public landing and authentication

### Purpose

Explain the product before requiring an account and provide Supabase sign-in or sign-up.

### Page design

1. Navigation with Method, Research, Learn, Safety, and Sign in.
2. Hero: “Understand what your portfolio is betting on.”
3. Three-part method: macro expectations, company evidence, transparent alternatives.
4. Research-workbench explanation and evidence-source stack.
5. Authentication section with email, password, login/sign-up switch, and validation messages.
6. Safety footer with decision-support and no-trading language.

### Outputs and states

- Existing Supabase sessions open the authenticated application without another login.
- New accounts may require email confirmation.
- Missing public Supabase configuration produces a direct setup message.
- `/learn` remains available as an approved anonymous preview.

## 5. Today

### Purpose

Today is a concise market-first briefing. It replaces a prominent numeric regime score with the question: **“What currently matters to your portfolio?”**

### Page design and sections

1. **Briefing hero**
   - Short current conclusion.
   - Market-data date and briefing-build date.
   - Current, partial, or stale-fallback badge.
   - Up to two visible coverage warnings.
   - Refresh, Explore evidence, and Portfolio analysis actions.
   - Side summary of the three most relevant portfolio factors.
2. **General market mode**
   - Appears when no portfolio exists.
   - Explains that market research works without holdings.
   - Links to portfolio creation.
3. **Market movement**
   - Broad-market and style ETFs.
   - One-day, one-week, and one-month adjusted-close changes.
4. **Sector tape**
   - Sector ETF movement using the same session windows.
5. **Cross-asset evidence**
   - Rates, oil, credit, dollar, and volatility observations.
6. **Relative leadership**
   - Leading and lagging sectors and styles.
   - Expandable calculation method.
7. **Portfolio pulse**
   - No more than three attention items.
   - What changed, why it matters, affected holdings, confidence, and evidence links.
8. **Upcoming events**
   - Earnings, macro releases, and catalysts.
   - Coverage ratio and missing-event warnings.
9. **Research queue**
   - Deterministically selected ideas requiring further investigation.
   - Universe, filters, exclusions, minimum data, method, and invalidation evidence.
10. **Evidence and methodology**
    - Collapsed provider counts, macro evidence, assumptions, and coverage.

### User actions

- Refresh stored provider data.
- Open Research for a market, macro, scenario, or prediction-market investigation.
- Open Portfolio Assistant.
- Ask EagleEyes about an attention item.
- Follow a source link.

### Main outputs

- A short market-and-portfolio headline.
- Relative movements, not unsourced forecasts.
- Portfolio relevance expressed as high/moderate/low and positive/negative/mixed.
- Up to three ranked attention items.
- Validated events and research prompts.

### Data dependencies and limitations

- Market movement requires adjusted-price coverage.
- Macro indicators require FRED coverage.
- Personalized relevance requires saved, valid holdings.
- Events depend on validated calendar coverage.
- If live refresh fails, the latest valid briefing may be shown with a stale warning.

## 6. Plan

### Purpose

Plan supplies optional personal context to portfolio research. It is not required to use Today, Research, Learn, Ask EagleEyes, or Advanced.

### Sub-tabs

| Sub-tab | Use | Primary outputs |
|---|---|---|
| **Plan overview** | Review saved context before editing it | Goal status, policy state, guidance level, and links to next steps. |
| **Essentials** | Capture only information that can change an analysis | Horizon, contributions, taxes, liquidity, income stability, experience, and distinct risk measures. |
| **Goals** | Create and fund multiple objectives | Target, date, priority, flexibility, funding source, account assignment, projections, and contribution gap. |
| **Investment policy** | Define durable decision rules | Allocation ranges, reserve minimums, concentration limits, exclusions, rebalancing rules, and approval status. |

### Page design

- Overview-first landing instead of a long form.
- Progressive three-step explanation: essentials, goals, then decision rules.
- Goal creation is isolated to the Goals tab.
- Forms use grouped panels rather than one uninterrupted questionnaire.
- Results distinguish risk tolerance, loss capacity, and required risk.

### User actions

- Save or update the suitability profile.
- Add, edit, or delete goals.
- Assign account percentages to goals without double counting over 100%.
- Run deterministic projections.
- Draft or approve an Investment Policy Statement.
- Open Portfolio analysis with saved Plan context.

### Main outputs

- On-track range and goal-attainment estimate.
- Required contribution and effect of contributing more or less.
- Nominal and inflation-adjusted outcomes.
- Most influential assumptions and missing information.
- Plain-language policy and monitoring rules.
- Guidance level: research only, guided analysis, or personalized recommendations context.

### Limitations

- Projections are modeled ranges, not guarantees.
- Tax treatment is approximate unless required cost and account inputs exist.
- Social Security, RMDs, Roth conversions, withdrawal sequencing, insurance, and estate planning are outside the current release.

## 7. Portfolio

### Purpose

Portfolio is the saved source of truth for holdings and the primary place to ask portfolio questions, run transparent analysis, and compare simulated paths.

### Workflow and sub-tabs

| Step | Sub-tab | Use | Primary outputs |
|---|---|---|---|
| 1 | **Portfolio holdings** | Create, edit, or import the portfolio | Validated holdings, sizing, accounts, cost coverage, and ingestion status. |
| 2 | **Portfolio Assistant** | Ask questions and review deterministic analysis | Conversation, tool results, current versus alternative allocations, risks, taxes, and explanations. |
| 3 | **Decision Lab** | Compare paths on common simulated markets | Wealth ranges, loss risk, drawdown, robustness, fees, taxes, turnover, and goal effects. |

### Portfolio holdings design

- Status summary for positions, total weight, and reconstructed performance.
- Manual editor for ticker, quantity/weight/value, cost basis, account type, and acquisition date.
- Flexible broker-file importer with column inference and preview.
- Clear validation state and unsaved-change warning.
- Duplicate symbols are combined or surfaced for review.

Accepted import concepts include symbol/ticker/security aliases; quantity/shares/units; decimal or percentage weights; position value; cost basis; account; and acquisition date. Extra columns are ignored. Unsupported securities such as bonds described only by a long name are not silently treated as stock tickers.

### Portfolio Assistant design

- Conversation sidebar directly beside the chat.
- Explicit New conversation, reopen, rename, and delete controls.
- Large main message area with follow-up memory.
- Tool-result cards link to analyses, simulations, research snapshots, or saved dashboards.
- Calculated analysis output remains below and visually separate from chat language.

The assistant can explain holdings, concentration, alternatives, factors, research evidence, or a simulation. It may call approved deterministic tools, but it cannot fabricate calculations or execute trades.

### Portfolio analysis outputs

The user-facing comparison can include:

- Current / do nothing.
- Contributions only.
- Gradual transition.
- Immediate transition.
- Risk-Controlled.
- Balanced.

Each path may show allocation ranges, changes, modeled return/risk, drawdown range, scenario outcomes, turnover, approximate taxes, goal effect, tradeoffs, assumptions, and infeasible constraints.

Reconstructed performance is always labeled **“Hypothetical one-year return using current holdings and weights.”** Actual account performance requires transaction history, cash flows, distributions, and historical positions.

### Decision Lab outputs

- Common 5,000-path historical block-bootstrap comparison.
- Reproducible seed and calculation version.
- Median wealth and percentile ranges.
- Probability of loss, modeled drawdown, and robustness.
- Contributions, withdrawals, inflation, expenses, approximate taxes, and saved goals where available.
- Compare and optimize actions for an existing run.

The engine supports combined economic, inflation, rate, oil, and credit conditions. Sparse history is shrunk toward disclosed history or proxy evidence.

## 8. Research

### Purpose

Research is the main discovery and investigation workspace. It keeps company quality, valuation, price behavior, sentiment, macro sensitivity, and portfolio fit as distinct conclusions.

### Sub-tabs

| Sub-tab | Use | Key outputs |
|---|---|---|
| **Stocks** | Search a stock or company and inspect evidence | Relative rank, evidence bucket, fundamentals, valuation, technicals, sentiment, risks, portfolio fit, freshness. |
| **ETFs** | Search the ETF catalog and open fund detail | Issuer, category, benchmark, fees, AUM/liquidity where available, holdings, concentration, overlap, and freshness. |
| **ETF Builder** | Construct a guided fund allocation | Core/satellite ranges, expense cost, look-through exposure, overlap, risk, benchmarks, and Decision Lab handoff. |
| **Stock Basket** | Build a constrained stock basket | Weight ranges, factor blend, diversification, risk contribution, inclusion/exclusion reasons, and benchmark comparison. |
| **Sectors** | Review stored sector coverage | Security counts, evidence mix, and leading stored names. |
| **Themes** | Inspect explicit theme membership | Mapping rule, actual matched universe, and matching securities. |
| **Macro workshop** | Explore current and historical macro evidence | Factor series, history, market-state identity, combinations, security reactions, and portfolio sensitivities. |
| **Scenarios** | Review separate market-state dimensions | Economic, inflation, and rate states plus independent shocks and historical samples. |
| **Prediction Markets** | Inspect Kalshi and Polymarket evidence | Grouped events, threshold distributions, prices, expiry, confidence inputs, source, and freshness. |
| **Compare** | Compare stored securities side by side | Relative evidence, requested benchmark/security comparison, and portfolio relationship. |
| **Watchlist** | Review only saved names | Sortable research cards and optional Expert component scores. |

### Stocks design and outputs

Search accepts supported ticker symbols and company names. Results disclose the actual ranking universe and supported-security scope.

Each security result can contain:

- Five-level evidence conclusion: Very Strong, Strong, Mixed/Average, Weak, or Very Weak/Limited.
- Relative rank within the visible universe.
- Strengths and weaknesses.
- Current validated price and multi-period returns.
- 52-week range, volume/liquidity, volatility, beta, Sharpe ratio, drawdown, RSI, moving averages, and descriptive trend state.
- Revenue/EPS growth, margins, free cash flow, returns on capital, debt, liquidity, and dilution where available.
- Trailing/forward multiples, PEG, price-to-sales, EV/EBITDA, cash-flow valuation, and peer comparison where available.
- Article coverage, positive/neutral/negative distribution, catalysts, conflicts, and freshness.
- Company quality, valuation, price behavior, sentiment, macro sensitivity, portfolio fit, and research confidence as separate conclusions.
- “What would change this view?” and historical-coverage warnings.

The supportive-fundamentals-and-valuation checkbox applies deterministic minimum-evidence filters. It narrows results; it is not a buy signal.

### ETFs design and outputs

- Searchable U.S. ETF catalog.
- Fund-level page with issuer, category, benchmark, inception date, expense ratio, holdings count, top holdings, concentration, and holdings coverage.
- Dated holdings snapshots with provider and stale/delayed/unavailable labels.
- Sector, industry, style, geography, and asset-class exposure when available.
- Look-through overlap with the current portfolio and other ETFs.
- Missing weight and partial holdings are disclosed rather than inferred as complete.

### Builders design and outputs

**ETF Builder** inputs include objective, horizon, three separate risk concepts, account/tax context, contributions, required asset classes, themes, expense/liquidity/history limits, concentration limits, and exclusions.

**Stock Basket** inputs include universe source, manual names, sector/industry/theme, fundamentals, valuation, growth, income, momentum, risk, sentiment, data-quality filters, objective, turnover/tax constraints, and maximum exposures.

Both builders return transparent ranges and diagnostics, never a BUY/HOLD/SELL instruction or a single guaranteed-best portfolio. Results can feed the Decision Lab.

### Macro, scenarios, and prediction markets

- Macro charts require titles, axes, units, frequency, time range, effective date, source, sample count, and missing-data treatment.
- Scenario dimensions are not forced into one mutually exclusive 100% distribution.
- Recession can coexist with accelerating inflation, tightening/easing rates, or an oil shock.
- Prediction contracts for the same event are grouped; threshold ladders are shown as one distribution.
- Kalshi and Polymarket remain independent evidence unless contracts genuinely resolve the same event.
- Prediction markets influence scenario evidence but cannot override company quality, valuation, historical risk, or portfolio constraints.

### Research chat

The Stocks area includes a research-specific conversation sidebar and chat. It can retrieve stored company research, fundamentals, news, macro evidence, portfolio context, and approved live-source evidence. Conversations persist, support follow-ups, and remain distinct from Portfolio conversations and AI dashboard boards.

## 9. Learn

### Purpose

Learn introduces investing to users who are not ready to interpret the full research terminal. It reuses audited educational ideas from FinLearn but uses EagleEyes authentication, data, safety rules, and storage.

### Learn hub design

- Continue-learning action.
- Recommended next lesson.
- Mastered, developing, and not-started concepts.
- Three learning paths.
- Deterministic practice labs.
- Optional “Learn from your portfolio” context for authenticated opt-in users.

### Learning paths

1. **Start Investing Safely** — preparation, saving versus investing, compounding, inflation, accounts, taxes, stocks, bonds, funds, and ETFs.
2. **Build a Portfolio** — risk, time horizon, diversification, allocation, fees, tax drag, rebalancing, and decline behavior.
3. **Understand Markets** — prices, fundamentals, valuation, macro conditions, news, sentiment, catalysts, correlation, and evidence quality.

### Lesson route and design

`/learn/{module}/{lesson}` displays:

1. Learning objective.
2. Plain-language lesson.
3. Young-adult example.
4. Deterministic lab.
5. Common misconception.
6. Quiz with answer explanations.
7. Optional live EagleEyes exercise.
8. Grounded lesson tutor.
9. Recommended next lesson.

Mastery is private and requires lesson completion plus a best quiz score of at least 80%. There are no public leaderboards, points, or streaks.

### Data and safety

- Anonymous users receive only the approved preview.
- Signed-in progress, quiz attempts, tutor threads, and preferences are stored under EagleEyes Supabase RLS.
- Lessons and quizzes are versioned repository content; Supabase stores activity rather than duplicating large lesson documents.
- The tutor cannot pick stocks, invent market data, replace lab calculations, or guarantee outcomes.

## 10. Ask EagleEyes

### Purpose

Turn a natural-language research request into a direct answer and a deterministic, editable research board.

### Execution model

```text
Question
→ Gemini intent planner
→ validated DashboardPlan
→ deterministic widget compiler
→ dependency graph
→ approved data services and calculations
→ widget verification
→ narrative verification
→ editable research board
```

Gemini determines intent and writes an explanation. It does not choose arbitrary SQL, calculate numbers, rank securities, create code, or silently substitute a different factor.

### Page design

1. Full-width workspace header with job state and progress.
2. Left saved-board list with open, refresh, duplicate, rename, and delete actions.
3. Large prompt composer above the output.
4. Draft/saved board toolbar.
5. Visible planner, widget-builder, verifier, and answer-review stages.
6. “Answer first” narrative section rendered as normal Markdown.
7. Research dashboard below the answer.
8. Widget controls for move, resize, remove, and quality state.
9. Add-data catalog for approved stored widgets.

### Supported request families

- Portfolio review.
- Security comparison.
- Candidate research.
- Macro analysis.
- Factor and correlation analysis.
- Scenario analysis.
- Weekly market changes.
- Sector beneficiaries.
- Contribution-only diversification.
- Next-dollar research.
- Combined macro states.
- Thesis invalidation.
- Stale-evidence audits.

### Outputs and states

- Progressive widget rendering.
- Machine-readable lineage and calculation versions.
- Partial success when optional evidence fails.
- Successful widgets remain visible if narration fails.
- Required-evidence verification catches wrong entities, factors, periods, units, or benchmarks.
- Saved boards preserve plan, specification, layout, compatible result references, and revisions.

## 11. Advanced

### Purpose

Advanced is the manual research terminal and audit surface. It keeps technical detail away from the default Today and Portfolio experiences while preserving full transparency.

### Sub-tabs

| Sub-tab | Use | Key outputs |
|---|---|---|
| **Research terminal** | Manually compose a dashboard | Configurable, movable, resizable widgets and saved layouts. |
| **Model diagnostics** | Inspect current quantitative health | Covariance shrinkage, conditioning, effective rank, turnover, allocation stability, and model versions. |
| **Validation** | Inspect out-of-sample evidence | Walk-forward folds, equal-weight/static benchmarks, leakage checks, calibration, regime counts, and promotion decisions. |
| **Data lineage** | Audit stored datasets | Counts, effective dates, coverage, providers, cache state, assumptions, and warnings. |
| **Provider health** | Diagnose integrations | Configuration, freshness, errors, fallbacks, rate-limit metadata, and provider refresh actions without exposing secrets. |

### Research terminal design

- Add-widget catalog.
- Manual drag/move, resize, and removal controls.
- Save, open, rename, duplicate, reset, and delete layout actions.
- Simple/Detailed/Expert transformation over the same results.
- Layouts are separate from AI-generated boards but share calculation services, chart components, and result contracts.

### Available widget families

- Portfolio return, allocation, concentration, and risk.
- Stock/ETF prices and research summaries.
- Watchlists, sectors, and performance.
- Correlations and heatmaps.
- Macro indicators and yield curves.
- Oil, commodities, and market-state evidence.
- Scenario estimates and historical regimes.
- Kalshi and Polymarket search/evidence.
- Fundamentals, valuation, earnings, catalysts, and research rankings.

Advanced numbers should lead with qualitative five-level buckets where a user-facing interpretation is appropriate, while raw scores and diagnostics remain visible in Expert mode.

## 12. Persistent conversations and artifacts

Research Chat and Portfolio Assistant use separate categories but the same conversation model.

Supported behavior:

- New conversation.
- Conversation sidebar.
- Reopen and continue.
- Rename and delete.
- Automatic restoration after reload.
- Summaries for long histories.
- Follow-up memory.
- Links among messages, tool runs, simulations, analysis runs, research snapshots, and saved dashboards.

The system limits retries, continuations, request duration, provider calls, and database waits. Short-lived evidence caches reduce repeat latency. A failed optional tool should produce a partial answer with a warning rather than erase successful evidence.

## 13. Data and calculation boundaries

### Primary evidence sources

- Corporate-action-adjusted price providers such as Tiingo and Polygon/Massive.
- FRED/ALFRED macro observations and point-in-time regime features.
- SEC Company Facts fundamentals.
- ETF catalog and dated issuer/provider holdings snapshots.
- Kalshi and Polymarket public market evidence.
- Stored news and catalyst documents.
- User portfolios, profiles, goals, policies, watchlists, and prior validated runs.

### Required result metadata

Every numerical result should include:

- Effective/as-of date.
- Provider and dataset lineage.
- Retrieval/cache state.
- Calculation method and version.
- Parameters and sample count where applicable.
- Data quality and appropriate confidence dimensions.
- Assumptions, missing-data treatment, warnings, and “How this was calculated.”

Missing evidence must not become an average or neutral score.

## 14. Storage and privacy

The active EagleEyes Supabase project is the sole production authentication and user-data authority.

RLS-protected user data includes:

- Portfolios and holdings.
- Profiles, goals, projections, and investment policy.
- Conversations, messages, summaries, and linked artifacts.
- AI boards, revisions, immutable runs, and terminal layouts.
- Learn preferences, progress, quiz attempts, tutor threads, and messages.
- Simulations and ETF/stock builder results.

Provider caches and shared market datasets are stored separately from user-owned rows. Browser storage is reserved for device presentation preferences, not sensitive holdings. Service-role keys remain server-only.

## 15. Core end-to-end user journeys

### New research user

1. Review landing page or Learn preview.
2. Create an account and sign in.
3. Open Today in general-market mode.
4. Search a company or ETF in Research.
5. Ask a follow-up in Research Chat.
6. Save a watchlist or AI board.

### Portfolio user

1. Open Portfolio holdings.
2. Import a broker file or enter positions manually.
3. Review validation and save.
4. Ask Portfolio Assistant what the largest risks are.
5. Run the transparent portfolio comparison.
6. Open Decision Lab for common-path simulations.
7. Save optional goals or policy context in Plan.

### Builder user

1. Open Research → ETF Builder or Stock Basket.
2. Select objective, constraints, universe, and evidence requirements.
3. Review ranges, costs, overlap, exclusions, and data gaps.
4. Send the candidate allocation to Decision Lab.
5. Compare do-nothing, contribution-only, gradual, and immediate paths.

### AI-board user

1. Ask a question in Ask EagleEyes.
2. Watch planning, data retrieval, calculation, verification, and narration progress.
3. Read the answer first.
4. Inspect evidence widgets and methodology.
5. Add, remove, move, or resize widgets.
6. Revise, save, rename, duplicate, refresh, reopen, or delete the board.

## 16. Product review checklist

### Value and comprehension

- Can a first-time user explain the purpose of every primary workspace?
- Does each page lead with a user question rather than a model name?
- Are headings large enough to establish hierarchy?
- Is chat visually primary when the user is in an assistant workflow?
- Are analysis outputs clearly separated from conversational language?
- Is “do nothing” treated as a valid path?

### Evidence integrity

- Does every conclusion identify its universe and effective date?
- Are company quality and portfolio fit separate?
- Are hypothetical and actual performance impossible to confuse?
- Are overlapping scenarios and prediction contracts kept independent when required?
- Does missing or stale data visibly weaken the conclusion?
- Can an Expert reproduce the result from method, parameters, and lineage?

### Interaction completeness

- Does every visible button have an observable action, loading state, success state, and failure state?
- Can saved portfolios, goals, conversations, boards, layouts, simulations, and builder results reopen correctly?
- Do refresh and delete actions affect only the current user's records?
- Do partial provider or widget failures preserve usable results?

### Production readiness

- Supabase session refresh and RLS isolation pass live tests.
- FRED, price, SEC, ETF, Kalshi, Polymarket, news, and Gemini integrations expose health and fallback states.
- Provider timeouts, bounded retries, cache durations, and rate limits are configured.
- Browser journeys pass for login, import, research, analysis, simulation, board editing, Learn mastery, and saved-state restoration.
- Monitoring records latency, cache hit rate, provider failures, partial success, model versions, and coverage deterioration.

## 17. Current product caveats for review

- The breadth and freshness of stock, ETF, fundamentals, news, and event outputs depend on successful provider ingestion.
- Some researched securities may have less than one full market cycle; proxy or shrinkage treatment must remain visible.
- ETF holdings may be daily, delayed, partial, stale, or unavailable depending on issuer/provider coverage.
- Actual personal performance is not available without transaction and cash-flow history.
- Tax estimates are incomplete without account, basis, acquisition date, and applicable tax assumptions.
- Simulation and optimizer results are research estimates, not forecasts or trade instructions.
- The product should begin as a private personal beta until live integrations, RLS, complete browser workflows, retention, backups, and financial-language review pass production gates.
