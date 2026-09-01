# EagleEyes UI Simplification and Browser Stability Audit

Audit date: 2026-08-31

Production target: `https://eagle-eyes-ai.vercel.app`

Scope: read-only product/content audit plus production browser stress testing. No product behavior, methodology, provider, backend architecture, or deployment was changed.

## A. Executive summary

EagleEyes is overloaded in the places users need to understand fastest. Research is the clearest example: a completed company report mounts 61 cards, 66 disclosure controls, 69 evidence/status badges, about 2,400 DOM nodes, 11 screens of content, and roughly 11,000–12,000 characters at once. Portfolio becomes similarly dense once intelligence is loaded: 61 editable holding rows, 432 inputs, 83 controls, 16 cards, 11 disclosures, about 2,137 DOM nodes, and more than nine screens. Decisions mounts the full security universe plus the full thesis, journal, review, and scenario workflow before a security is chosen.

The app is not uniformly overloaded. Plan, Learn, Market Climate, the empty Research builders, and a short Ask conversation are reasonably bounded. The problem is an inconsistent hierarchy: several pages expose the entire analytical capability surface as the initial experience instead of presenting one answer and deferring evidence.

The production “browser crash” observed in this audit is primarily an application render failure, not a proven browser out-of-memory event. Today reproducibly throws `TypeError: Cannot read properties of undefined (reading 'score')` because it dereferences `overview.health.score` when a partial overview lacks `health`. Chrome then shows “This page couldn’t load.” That is a P0 stability blocker.

Separate frontend memory tests did not prove a DOM or canvas leak:

- Research AAPL → MSFT → AMZN → AAPL replaced the prior report rather than duplicating it.
- Ten dashboard canvas close/open cycles returned to exactly 1,038 DOM nodes closed and 1,084 open.
- A 30-question Ask conversation remained responsive, but live DOM grew linearly from 115 to 998 nodes and text retained in the mounted conversation grew from 716 to 28,361 characters.

The main pressure risks are therefore large payload/render work, unbounded conversation retention, full-table mounting, and broad global state—not a demonstrated chart/listener leak. The full Research response was about 560 KB in captured production telemetry and takes about 43 seconds to reach the full report in the tested production path. The endpoint also duplicates shared Research data in multiple response branches.

## B. Page content inventory

Counts are production measurements after data settled unless marked static/variable. “Sections” means product-level sections, not raw HTML section tags. Controls include buttons and form controls. Text is `body.innerText` and includes shell navigation.

| Page/state | Primary job | Sections | Cards/panels | Tables / rows | Charts | Controls | Tabs | Badges | Expandables | DOM | Text chars | Screens | Key answer above fold? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Today | Know what changed and needs attention | ~7 static, data-variable | health + components + actions + changes + 61-row heatmap + 5 context blocks | heatmap / up to all holdings | 0 | variable; up to 6/action | 0 | variable | actions + 1 methodology block | Not measurable: production render crashes | Not measurable | Not measurable | No; page is unavailable |
| Portfolio — Holdings/intelligence | Understand portfolio state and edit holdings | ~8 | 16 | 1 / 62 | 0 | 83 buttons + 432 inputs | 2 | 0–2 | 11 | 2,137 | 9,894 | 9.3 | No; editing and intelligence compete |
| Portfolio — Analysis/optimizer initial | Decide whether and how to run analysis | ~6 | ~8 control/explanation panels | 0 | 0 | 16 buttons + 19 inputs | 2 | 0 | 2 | 253 | 2,666 | 3.9 | Partly; setup dominates |
| Research — empty company picker | Choose a company | 2 | 1 picker + universe | 0 / 61 ticker choices | 0 | 88 buttons + 1 input | 2 | 0 | 2 | 178 | 941 | 1.3 | Yes, but 61 ticker buttons add noise |
| Research — full AAPL | Decide whether the company merits attention | 11 report sections + header/summary | 61 | 0 semantic tables; several div-grids | 1 | 96 buttons + 42 links | 2 | 69 | 66 | 2,396 | 11,804 | 11.0 | Five questions are visible; report overwhelms afterward |
| Research — Watchlist | Review saved names | 2 | small list/controls | 0 | 0 | 27 + 3 inputs | 2 | 0 | 3 | 145 | 989 | 1.4 | Yes |
| Research — Scenarios | Understand current scenario evidence | 5 | 5 | 0 initially | 0 | 26 | 2 | 0 | 2 | 281 | 2,408 | 3.6 | Partly |
| Research — Stock/ETF builder | Define a constrained basket | 2 | 1 setup panel | 0 before run | 0 | 26 + 4 inputs | 2 | 0 | 2 | 118 | 729–756 | 1.0 | Yes |
| Research — Model portfolio builder | Draft, compare, backtest, simulate, save | 4 initial; up to 8 after results | setup, saved models, alternatives, backtest, simulation, save bar | result-dependent | result-dependent | 38 + 8 inputs initially | 2 | 0 | 3 | 197 initially | 1,338 | 1.8 | Workflow is clear initially; results can become dense |
| Research — Compare | Start a comparison | 2 | empty state | 0 | 0 | 25 | 2 | 0 | 2 | 103 | 524 | 1.0 | Yes |
| Market Climate | Know the current regime and relevant forward signals | ~5 | 13 | 0 | 0 | 12 | 0 | 0 | 1 | 217 | 3,209 | 2.6 | Yes, then repeats support evidence |
| Ask — one exchange | Ask and receive an answer | 3 | 2 messages | 0 | 0 | 10 + 4 inputs | 0 | 0 | 2 | 169 | 1,792 | 1.1 | Yes |
| Ask — 30 questions | Continue a long investigation | 3 | 60 messages | 0 | 0 | 19 + 4 inputs | 0 | 0 | 31 | 998 | 28,361 | internal scroll | Current answer yes; all old answers remain mounted |
| Ask canvas — tested saved analysis | Inspect/modify a visual result | +2 canvas sections | 1 widget | 1 unavailable widget result | 0 | +10 | 0 | 0 | +2 | +46 open | +427 | split-pane | Yes, but result was unavailable |
| Decisions/theses | Record and later review a security decision | ~7 workflows | 11 + 63 security buttons | 0 | 0 | 120 + 36 inputs | 3 | 0 | 6 | 778 | 5,023 | 3.6 | No; universe and empty workflows dominate |
| Plan & profile | Define constraints and goals | 2 | compact forms | 0 | 0 | 25 | 4 | 0 | 1 | 141 | 1,368 | 1.4 | Yes |
| Learn hub | Choose and complete education | 1 path + 6 lessons | 6 | 0 | 0 | 30 + 2 inputs | 0 | 0 | 1 | 226 | 2,869 | 2.1 | Yes |
| Advanced terminal | Configure expert monitoring | 3 | 6 widgets initially | div tables | 1 | 49 + 1 input | 5 | 0 | 1 | 422 | 3,068 | 2.7 | Mostly; expert density is intentional |

There is no separate production backtest route. Backtest and 5,000-path simulation are steps inside the model portfolio builder. Rebalancing/optimizer is Portfolio Analysis. Scenario work is a Research subview and feeds Decision Lab.

### Primary job and hierarchy decisions

| Page | One primary job | Secondary | On demand / separate | Remove from initial view |
|---|---|---|---|---|
| Today | What changed since yesterday that matters? | Top action, next event, thesis change | Full holdings heatmap, methodology, broad macro | Duplicate health components and generic market context |
| Portfolio | What is my portfolio state and what needs attention? | Largest risks, opportunities, meaningful changes | Editable holdings, factors, scenarios, optimizer | Simultaneous edit + intelligence + methodology presentation |
| Research | Does this company deserve more attention? | Five-question evidence and decision summary | Detailed sections, raw tables, sources/methods | Repeated badge/method block on every visible card |
| Ask | Get a useful answer to the current question | Evidence and next action | Old messages, full source metadata, canvas | Permanent explanatory strips after the first answer |
| Canvas | Inspect a concise visual answer | 4–6 supporting widgets | More widgets and full datasets | Repeated full narrative already present in chat |
| Market Climate | What regime matters to my portfolio now? | 3–5 drivers and upcoming changes | Full market list and methodology | Repeated state labels that restate headline |
| Decisions | What did I decide, why, and when should I review it? | Current evidence and invalidation | Editor, three-case memo, journal, calibration, scenario lab | Rendering every empty workflow before selecting a security |
| Builders | Produce one transparent candidate allocation | Constraints and comparison | Backtest, simulation, save/convert | Explanations repeated at each step |
| Plan | Set durable goals and constraints | Guidance | Detailed methodology | None material |
| Learn | Continue the next lesson | Progress | Full catalog | None material |
| Advanced | Operate an expert terminal | Current layout | Diagnostics/provider/lineage tabs | None; gate behind Advanced is already appropriate |

## C. Must-show / secondary / on-demand / redundant / remove matrix

| Page | MUST_SHOW | SECONDARY | ON_DEMAND | REDUNDANT | REMOVE |
|---|---|---|---|---|---|
| Today | one-sentence briefing, top 3 changes, top action, next material event | health score, 3 risk/opportunity indicators | all holdings, action workflow, broad market/macro, methodology | component score repeated beside headline; general market context also in Market Climate | full 61-row heatmap from briefing default |
| Portfolio | value/allocation headline, top 3 risks, top 3 opportunities/changes, actions | 5 largest holdings, sector/overlap summary | editable 61-row table, factors, correlations, scenarios, optimizer settings, ledger | concentration repeated across position, sector, factor, scenario panels | all edit controls in the intelligence default |
| Research | identity/price, five-question summary, one decision state, 3–5 key metrics, top catalyst/risk | section status and one supporting fact per question | 11 detailed sections, historical tables, ownership, portfolio-fit details, raw evidence/method | status/freshness/source on every card plus global source section; same metric in header, summary and detail | persistent per-card prose for unavailable fields; use compact grouped missing state |
| Ask | current answer, conclusion, affected limitation, composer | compact evidence count, 1–3 next actions | source details, older messages, canvas | permanent “Verified facts / Model outputs / Market-implied” strip on every turn; repeated full company boilerplate for narrow questions | full company template when user asks one metric |
| Canvas | title, takeaway, up to 4–6 widgets, refresh state | widget source/as-of | full data, methods, more widgets | narrative duplicated from chat inside widgets | default skeleton count beyond expected widget count |
| Decisions | selected security, latest decision/thesis, invalidation, due review | current evidence quality and relationship | editor, cases, journal, retrospectives, calibration, scenario comparison | empty evidence cards and empty journal sections simultaneously | full 61-security button list; replace with search/recent/needs-review shortlist |
| Market Climate | headline regime, confidence/as-of, top drivers, portfolio relevance | upcoming events/markets | full evidence and all scenario cards | five state cards that restate one regime | stale/expired items from “upcoming” presentation (correctness issue noted, not redesigned here) |
| Builders | current step, essential constraints, result summary | universe disclosure | alternatives, backtest, simulation, raw series | repeated workflow/explanation copy | none before results; progressively reveal later stages |
| Advanced | active widget layout | freshness indicator | catalog, detailed diagnostics | repeated widget footers | none; enforce widget budget |

### Redundancy findings

1. Research repeats evidence type, status, source/method, and freshness at card, section, page, and Sources levels. Best presentation: one section-level trust line; per-field detail only on disclosure.
2. Research header, five-question strip, detailed sections, and Decision Summary repeat the same thesis/valuation/risk claims. Best presentation: five-question strip is the sole concise summary; Decision Summary adds only action state and invalidation.
3. Portfolio repeats concentration through holdings weight, sector exposure, effective holdings, risk contribution, and dependency panels. Best presentation: one “Concentration” block with tabs/details for the analytical lenses.
4. Today repeats health score and each component before showing what changed. Best presentation: change headline first; health as one supporting indicator.
5. Ask narrow questions receive the full company overview template. Best presentation: direct answer + 2 supporting facts + limitation; link to Research for the dossier.
6. Ask renders evidence labels both in a permanent strip and per answer. Best presentation: remove the permanent strip after onboarding; keep answer-specific evidence.
7. Canvas can repeat chat narrative inside widgets. Best presentation: one canvas takeaway, then visual evidence only.
8. Decisions displays empty stored research, fundamentals, earnings, markets, three cases, journal, calibration, and scenarios before selection. Best presentation: one select state, then progressive workflow.

## D. Simplified target structure

### Today

- Above fold: one briefing headline; top three material changes; single highest-priority action; next material event.
- Below fold: health trend, risk/opportunity shortlist, thesis changes.
- On demand: holdings heatmap, full action center, broad market/macro, score methodology.

### Portfolio

- Above fold: total value/health; top three risks; top three opportunities/changes; actions requiring attention.
- Below fold: largest holdings, allocation/concentration, performance and thesis coverage.
- Secondary tabs: Holdings editor; Risk & factors; Scenarios; Optimize.
- On demand: full tables, correlation matrices, methodology, ledger import.

### Research

- Above fold: identity/price; five-question summary; decision state; 3–5 key metrics; top catalyst and top risk.
- Below fold, initially collapsed/lazy: Financial trend; Valuation; Earnings; Thesis; Market/technical; Ownership; Portfolio fit.
- On demand: raw evidence, long historical grids, provenance, methodology, registry missing fields.
- Initial mount target: header + summary + at most three high-value detail sections. Preserve all 148 fields in capability/detail access, not in the initial DOM.

### Ask

- Default: chat header, current thread, concise answers, composer.
- Mount only the latest 20–40 messages; load earlier history incrementally.
- Collapse sources and verbose evidence by default.
- Open canvas only for explicit visual requests; retain chat answer as a short takeaway, not a duplicate dashboard.

### Canvas/dashboard

- Initial: title, one takeaway, 4–6 widgets maximum.
- Each widget: one conclusion, one visual/table, compact source/as-of.
- On demand: full rows, raw series, methodology, additional widgets.
- Saved dashboards load specification and summary first; fetch heavy widget datasets when visible.

### Market Climate

- Above fold: regime headline, confidence/as-of, top three drivers, one portfolio implication.
- Below fold: upcoming changes/events and 3–5 supporting indicators.
- On demand: all scenarios, prediction-market details, methodology.

### Decisions

- Above fold: security search plus “recent” and “needs review”; latest decision, thesis, invalidation, review date.
- Below fold after selection: evidence changes and case summary.
- Secondary modes: Edit thesis; Record decision; Journal/review; Scenario comparison.
- Do not mount the full universe and all empty workflows together.

### Watchlist and Research lists

- Default: compact ranked list with changed/new evidence flags.
- On demand: full coverage/missing data and batch actions.
- Do not render all holdings as permanent ticker buttons above every report.

### Scenario/simulation

- Initial: chosen scenario, probability/evidence state, portfolio effect headline, top contributors.
- On demand: all dimensions, contract thresholds, path distribution, methodology.

### Optimizer/rebalance

- Initial: current problem statement, recommended posture, one “run/update” action.
- Secondary: key constraints.
- On demand: presets, all sliders, alternatives, tax/turnover detail, full calculation evidence.

### Model portfolio/backtest

- Progressive steps: basket → alternatives → backtest → simulation → save.
- Only the active/completed step is expanded; later stages are not mounted until available.
- Result summary compares at most three alternatives; full series and tables are details.

### Plan, Learn, Advanced

- Plan and Learn need targeted cleanup only.
- Advanced can remain denser because it is explicitly gated, but should enforce widget/data budgets and lazy-load inactive tabs.

## E. Top 10 simplification changes

| Priority | Change | User benefit | Effort | Behavior risk |
|---|---|---|---|---|
| P0 | Fix Today partial-data render guard and add an error boundary with recoverable state | Restores the primary page and prevents a single card from taking down the app | Small | Low |
| P0 | Make Research summary-first; lazy-mount detail sections | Fast answer, far less DOM/payload work | Medium | Medium, mostly presentation/loading |
| P0 | Split full Research response; remove duplicated capability branches | Faster time-to-useful, lower browser/backend pressure | Medium | Medium contract risk |
| P0 | Separate Portfolio “Overview” from the 61-row editor | Immediate portfolio understanding | Medium | Low–medium |
| P1 | Virtualize/paginate Holdings and Decisions security universe | Removes hundreds of inputs/buttons from initial DOM | Medium | Medium interaction risk |
| P1 | Virtualize/incrementally load long Ask conversations | Bounded DOM and state for real use | Medium | Medium scroll/history risk |
| P1 | Make Decisions progressive after security selection | Eliminates empty-workflow overload | Medium | Low |
| P1 | Consolidate Research trust/source/freshness UI at section level | Cleaner scanning without losing provenance | Small–medium | Low |
| P1 | Enforce 4–6 initial dashboard widgets and lazy widget data | Predictable canvas density and memory | Small–medium | Low |
| P2 | Shorten Ask renderers for narrow metric questions and remove repeated boilerplate | More useful, faster-scanning answers | Medium | Medium answer-contract risk |

## F. Browser crash root cause

### Reproduced blocker

- Route: `/today`
- Visible result: page renders briefly, then Chrome displays “This page couldn’t load.”
- Production console, repeated three times: `TypeError: Cannot read properties of undefined (reading 'score')` in chunk `589-c1dd539cb46e0528.js`.
- Local source match: `TodayPage.tsx` guards only `!overview`, then dereferences `overview.health.score`, `overview.health.status`, and `overview.health.components`. The Ask prompt also optional-chains `overview` but not `health`.
- Trigger class: a partial or schema-incompatible portfolio overview object exists while `health` is absent.
- Classification: **OTHER / RENDER EXCEPTION**, with a data-contract mismatch. It is not evidence of browser heap exhaustion.

### Other stability classifications

| Finding | Classification | Evidence | Leak proven? |
|---|---|---|---|
| Full Research takes ~43 s and mounts ~2.4k nodes | NETWORK/PAYLOAD + DOM SIZE + RENDER WORK | measured AAPL/MSFT/AMZN | No |
| Portfolio mounts 432 inputs and 62 rows | DOM SIZE | measured production DOM | No |
| Ask grows linearly with messages | STATE RETENTION + DOM SIZE | 115→998 nodes over 30 questions | Bounded test shows growth by design, not post-removal retention |
| Canvas open/close | chart/component lifecycle | exact 1,038↔1,084 nodes for 10 cycles | No leak observed |
| Research ticker changes | state/DOM replacement | ~2,396→2,393→2,312→2,396 | No mounted-DOM leak observed |
| Dashboard event stream survives route changes until terminal | EVENT/SUBSCRIPTION RETENTION risk | static code lacks route/unmount abort | Potential; not reproduced as a crash |

## G. Frontend memory profile

The controlled production browser surface did not expose `window.performance`, JS heap snapshots, or per-tab RSS. The machine had multiple Chrome tabs/processes, so OS-wide Chrome RSS would not be a valid per-EagleEyes measure. This report therefore does not invent heap numbers or call monotonic heap growth a leak.

Measured proxies:

| Stage | DOM nodes | Visible nodes | Text chars | Notes |
|---|---:|---:|---:|---|
| Ask new chat | 115 | 91 | 716 | baseline |
| Ask after 10 questions | 429 | 405 | 8,927 | 20 message articles |
| Ask after 20 questions | 725 | 701 | 19,047 | 40 message articles |
| Ask after 30 questions | 998 | 974 | 28,361 | 60 message articles, 31 disclosures |
| Ask history open | 1,027 | 1,003 | 28,918 | small incremental drawer cost |
| Ask canvas closed/open | 1,038 / 1,084 | — | 29,130 / 29,557 | stable over 10 cycles |
| Portfolio after Ask | 2,137 | 1,801 | 9,894 | Ask DOM unmounted, state retained |
| Research blank | 178 | 155 | 941 | Portfolio DOM unmounted |
| AAPL full | 2,396 | 2,369 | 11,804 | full report |
| Ask return | 1,038 | 1,014 | 29,130 | prior 60-message state restored exactly |

The navigation sequence requested in the brief cannot be completed exactly because step 1, Today, crashes. The safe subset demonstrates DOM release between conditional routes, while `Dashboard.tsx` intentionally retains cross-page state for Ask, dashboard results, portfolio intelligence, terminal data, and other workspaces.

Research stress result:

| Ticker | Full DOM | Full text | Result |
|---|---:|---:|---|
| AAPL first | 2,396 | 11,764 | full |
| MSFT | 2,393 | 11,427 | full |
| AMZN | 2,312 | 10,498 | full after completion |
| AAPL repeat | 2,396 | 11,804 | same shape as first |

No monotonic mounted-DOM growth was observed. A repeated ticker can benefit from backend caches, but the production UI still waited around 43 seconds in the tested path before the full dossier became visible.

Ask stress result: all 30 submitted questions completed without a browser failure. Observed per-answer latency after the first ranged from roughly 2.5 to 9.2 seconds. The test also exposed a product-content issue: several narrow questions render a generic full-company template or an indirect capability summary. That is answer composition quality, not the browser-crash root cause.

## H. Large payload and state findings

| Surface | Finding | Why it matters | Recommendation |
|---|---|---|---|
| Research `/overview` | about 560 KB captured production response; response carries `security`, legacy `intelligence`, merged shared intelligence, and `research_capabilities` | duplicated object graph, parse/GC cost, backend memory, long settle time | summary/core contract plus section detail endpoints; do not return shared model twice |
| Research frontend | `overview` state holds the complete response although only header/summary is above fold | keeps full dossier live while all 61 cards render | retain summary; fetch and cache section data only on open/near viewport |
| Ask | all messages map to DOM; full structured content and artifacts are retained in React state | linear live memory/DOM growth | window/virtualize messages and fetch older turns incrementally |
| Ask cache | `conversationCache` Map retains every opened conversation for each workspace; full messages/artifacts are also serialized to local storage | in-memory + browser-storage duplication | LRU by conversation count/bytes; snapshot only current conversation summary/recent turns |
| Dashboard | `dashboardJob` retains all `widget_results` while canvas is closed | hidden heavy data remains live | retain job/spec summaries; evict or refetch heavy result datasets |
| Dashboard stream | reader is cancelled on terminal state but is not tied to route/component abort | an in-flight stream can outlive canvas navigation | AbortController owned by job/canvas lifecycle |
| Portfolio | global holdings, diagnostics, overview, analysis and Today briefing coexist | necessary cross-page convenience, but broad object graph | keep canonical summary global; lazy-load/evict large page-specific detail |
| Simulation | frontend requests 5,000 paths but receives aggregate outcomes rather than raw paths | good: avoids retaining path arrays | preserve aggregate-only contract |

Browser storage size was not inspected because the browser-control safety boundary prohibits reading local/session storage. Static code confirms full current conversation snapshots are serialized there; this should be measured with an explicit in-app byte counter in a later instrumentation change.

## I. Component, chart, and table hotspots

1. `Dashboard.tsx` is 1,188 lines and owns state for every workspace. Only the active top-level page is mounted, which is good; however, large results remain retained across navigation.
2. `workspace-implementations.tsx` is 642 dense lines containing Portfolio, scenario, chat, dashboard and rendering logic. It encourages broad rerenders and makes payload boundaries hard to reason about.
3. Holdings renders every row and all seven inputs/selects per row. Production: 62 table rows and 432 controls. Virtualization or edit-on-demand is warranted.
4. Decisions renders every holding/watchlist name as a button before selection. Production: 120 buttons total.
5. Research renders 61 cards and 66 `<details>` elements. Closed details reduce visual clutter but do not avoid mounting their contents.
6. Ask maps every message and structured response detail. At 30 questions it mounted 60 message articles.
7. Dashboard maps every specification widget. Current tested canvas had one unavailable widget and no chart; lifecycle behavior was stable. A widget-count budget is still needed for generated dashboards.
8. Mini charts are native SVG rather than a third-party chart library. Research ticker replacement and canvas cycles did not show orphaned chart DOM.
9. Most effects clean up timers/listeners/subscriptions correctly. Research uses an AbortController and request sequence guard. The global document click effect has no dependency array, but React cleans the previous listener before rerunning; this is churn, not a proven leak.
10. Several async effects use `active` flags without aborting the network request. They prevent stale state writes but do not release request work early.

## J. Recommended frontend budgets

| Budget | Target | Rationale |
|---|---:|---|
| Initial page DOM | target <1,500 nodes; warn at 2,000; hard review at 2,500 | Research/Portfolio are already near the hard boundary |
| Research initial cards | 8–12 | header, five questions, key evidence/catalyst/risk |
| Research initially mounted detailed sections | max 3 | defer remaining sections until expanded/near viewport |
| Dashboard initial widgets | 4–6 | supports one clear answer without canvas overload |
| Simultaneously mounted charts | max 4 | defer non-visible charts |
| Raw points per visible series | 500; downsample above | sufficient for viewport-scale interaction |
| Correlation matrix | max 30×30 visible | larger matrices need drill-down/virtualization |
| Table rows without virtualization | max 50 desktop / 25 mobile | current 61 editable rows exceeds budget |
| Ask messages mounted | 40 messages (20 exchanges) | 60 messages produced ~1,000 DOM nodes; older turns should page in |
| Conversation in-memory cache | current + 2 recent, byte-bounded | prevents unbounded Map growth |
| Research header payload | <50 KB | first paint only |
| Research core payload | <150 KB | summary plus key evidence |
| Per-section detail payload | <200 KB; loaded on demand | avoids current ~560 KB full graph |
| Initial route data transfer | <250 KB compressed API data | practical interactive target |
| Steady-state tab heap | target <200 MB and plateau within 15% or 30 MB after three warm cycles | must be verified later with Chrome DevTools/Performance instrumentation |
| Long task | no main-thread task >100 ms during report expansion | protects interaction responsiveness |

## K. Implementation plan (not implemented)

### Phase 1 — P0 stability and primary hierarchy

- Fix Today’s partial-overview guard and add a route-level recoverable error boundary.
- Make Research summary-first and lazy-mount detail sections.
- Remove duplicated shared capability data from the full Research response; define bounded header/core/section contracts.
- Split Portfolio overview from holdings edit mode.
- Add production telemetry for route DOM, long tasks, payload bytes, and opt-in heap snapshots in test runs.

### Phase 2 — secondary simplification and lazy rendering

- Virtualize/paginate Holdings, Decisions security universe, and long Ask conversations.
- Make Decisions progressive after selection.
- Consolidate Research provenance/status UI.
- Add dashboard widget limits and lazy heavy-result loading.
- Add LRU/byte bounds to conversation and page-detail caches; abort dashboard streams on cancellation/navigation.

### Phase 3 — polish and performance hardening

- Shorten Ask renderers for narrow questions.
- Collapse low-value methodology/evidence repetition across pages.
- Enforce payload/DOM/long-task budgets in automated browser tests.
- Run instrumented heap snapshots for the full navigation, Research, Ask, and multi-dashboard sequences and require plateau after warmup.

## L. Final verdict

UI SIMPLIFICATION REQUIRED BEFORE BETA

BROWSER STABILITY BLOCKER
