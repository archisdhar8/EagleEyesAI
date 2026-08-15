# EagleEyes Product Hierarchy — Repository Audit and Implementation Record

This document records how the approved market-first product hierarchy maps to the current repository. It is an engineering contract, not a user guide.

## Architecture audited

- Frontend: React 19, TypeScript, vinext app router, shared orchestration in `app/Dashboard.tsx`.
- Backend: FastAPI services under `backend/`, with deterministic research, planning, portfolio, scenario, dashboard, and terminal calculations.
- Persistence: Supabase/Postgres with authenticated ownership and RLS; saved AI boards, immutable board runs, terminal layouts, portfolios, profiles, goals, policies, provider data, and model validation are preserved.
- Providers: FRED/ALFRED, Polygon/Massive, Tiingo, SEC Company Facts, Kalshi, Polymarket, Gemini, and supported ETF issuer/reference adapters.
- Compatibility: legacy routes are centralized in `app/lib/routes.ts`; v1 AI and terminal JSON is read through versioned adapters and is not rewritten.

## Product hierarchy

| Workspace | Canonical route | Repository implementation | Status |
|---|---|---|---|
| Today | `/today` | `app/components/today/TodayPage.tsx`, `backend/today_briefing.py` | Implemented |
| Research | `/explore` | `app/components/research/`, `backend/research_workspace.py` | Implemented; provider coverage varies |
| Portfolio | `/portfolio` | `app/components/portfolio/`, shared implementation boundary, `backend/analysis.py` | Implemented |
| Ask EagleEyes | `/ask` | `app/components/ask/`, `backend/dashboard_workspace.py` | Implemented |
| Plan | `/plan` | `app/components/plan/`, shared implementation boundary, `backend/planning.py` | Implemented; progressive simplification ongoing |
| Advanced | `/advanced` | `app/components/terminal/`, `backend/model_monitoring.py` | Implemented |

The manual Research Terminal and AI-generated research boards remain separate saved products while sharing calculation and result contracts.

## Phase audit

### Phase 1 — Hierarchy and compatibility

Implemented:

- Canonical navigation and legacy route aliases.
- Versioned adapters for terminal layouts and AI specifications.
- Regression fixtures preserving widget identity, order, size, task references, and result references.
- Existing Supabase tables and JSON fields remain additive and backward compatible.
- `Dashboard.tsx` is routing and shared-state orchestration only.
- Each workspace has a stable domain entry point. The former `workspaces.tsx` module is now a compatibility-only re-export; implementations sit behind `app/components/shared/workspace-implementations.tsx` so old imports remain valid.
- Shared status, freshness, lineage, and presentation components live under `app/components/shared/`.

Completed remediation:

1. Freeze the current workspace props and saved-layout fixtures as compatibility contracts.
2. Move Plan, Portfolio, Ask EagleEyes, Advanced, and Research behind stable domain entry points without changing exported props.
3. Extract shared loading, error, freshness, guidance-level, lineage, and presentation components into `app/components/shared/`.
4. Keep v1 JSON adapters at the boundary and introduce a new schema version only when a persisted field must change.
5. Run fixture, route, TypeScript, build, and Playwright tests after each workspace extraction rather than after one large rewrite.

Acceptance criteria:

- `Dashboard.tsx` contains routing, shared state, and request orchestration only.
- `workspaces.tsx` is removed or contains only compatibility re-exports.
- Saved AI boards and terminal layouts render with identical widget IDs, sizes, order, and result references.
- No data migration is required for component extraction.

Acceptance status: met. A deeper internal split of `workspace-implementations.tsx` may be done incrementally as a maintainability improvement, but is not required to load or preserve persisted v1 artifacts.

### Phase 2 — Today

Implemented:

- Market-first headline with no normalized regime score.
- General-market mode without a portfolio.
- Portfolio-aware concentration, relevance, and up to three deterministic attention items.
- Explicit no-urgent-change result.
- Index, sector, rates, oil, credit, dollar, volatility, leadership, events, and research follow-ups.
- Evidence links and stale-snapshot fallback.
- Per-observation status: end-of-day, delayed, cached, or stale.
- Guidance disclosure: General Market Research, Portfolio-Aware Analysis, or Personalized Guidance.
- Research ideas disclose universe, eligibility filters, exclusions, minimum data, method, freshness, why they appeared, and invalidation evidence.
- A normalized market-observation contract records effective time, retrieval time, latency class, entitlement, dataset version, and stale policy.
- An optional Polygon snapshot adapter overlays stored adjusted-price history and only labels observations `live` when real-time entitlement is explicitly configured.
- The last validated observations are persisted in `market_observations`; failures retain the stored end-of-day or cached briefing with an explicit status.
- Composite event providers normalize stable IDs, deduplicate events, retain confirmed-versus-estimated timing, and report holdings-level earnings coverage.
- Provider Health reports snapshot mode, entitlement, event counts, effective-through dates, errors, and fallbacks.

Unsupported or conditional:

- Exchange-grade `live` status requires a separately entitled provider subscription. Without explicit entitlement, Polygon snapshots are truthfully labeled `delayed`; stored adjusted history remains `end-of-day`.
- The application measures and exposes earnings coverage and missing tickers, but the 95% target depends on the configured calendar provider actually supplying dates. Missing external coverage is never filled with invented events.

Completed remediation:

1. Define the actual latency requirement per widget: delayed quotes for briefing context, intraday bars for charts, and real-time quotes only where the product can justify exchange licensing and cost.
2. Add a normalized `market_observations` contract containing provider timestamp, exchange timestamp, retrieval timestamp, delay class, entitlement, and stale-after policy.
3. Add an entitled streaming or snapshot provider behind the existing provider interface; never relabel end-of-day data as live when the provider is unavailable.
4. Persist the last validated intraday snapshot and fall back to end-of-day or cached evidence with an explicit status transition.
5. Add dedicated earnings and economic-calendar adapters with stable event IDs, revisions, cancellations, confirmed-versus-estimated status, affected symbols, and source URLs.
6. Deduplicate events across providers and measure event coverage for current holdings, watchlist names, and major U.S. macro releases.
7. Add provider-health checks for quote delay, event coverage, rate limits, and stale fallbacks.

Acceptance criteria:

- Every market observation is labeled live, delayed, end-of-day, cached, or stale from deterministic metadata.
- Today continues working when the real-time provider fails.
- At least 95% of current U.S. holdings have upcoming earnings coverage when an earnings date exists.
- Major scheduled U.S. releases display release time, timezone, source, status, and last verification timestamp.

Acceptance status: the software and fallback criteria are met. The external 95% earnings-coverage service level and real-time label remain conditional on provider coverage and entitlement; the UI now measures and discloses both rather than overstating them.

### Phase 3 — Research

Implemented:

- Internal Stocks, ETFs, Sectors, Themes, Macro, Scenarios, Prediction Markets, Compare, and Watchlist navigation.
- Ticker and company-name search across the stored supported universe.
- Deterministic evidence buckets, disclosed ranking universe, strengths, weaknesses, valuation audit, fundamentals, price behavior, catalysts, thesis risks, portfolio fit, invalidation, freshness, missing-data reasons, and historical coverage.
- Searchable U.S. ETF catalog and dated holdings where an issuer/provider supplies them.
- Kalshi and Polymarket remain independent evidence; related contracts are grouped.
- A versioned `security_master` records the supported instrument tier separately from research evidence availability.
- Exact-symbol and company searches return the supported scope and a concrete conditional/unsupported reason.
- Every research result carries field-level component coverage; missing fields are excluded instead of becoming neutral 50-point inputs.
- ETF snapshots report as-of date, provider, freshness, explained weight, unexplained weight, and a two-percent reconciliation tolerance.

Unsupported or conditional:

- “Any stock” means any valid symbol the configured providers can resolve; coverage is not guaranteed for every global, OTC, private, delisted, or newly listed security.
- ETF holdings completeness depends on issuer access and snapshot freshness.
- Research ideas are comparative follow-ups, not buy recommendations.

Completed remediation:

1. Define supported security scope explicitly: begin with active U.S.-listed common stocks and ETFs, then add ADRs, OTC, international, delisted, and historical identifiers as separate coverage tiers.
2. Populate a security-master table with ticker, name, exchange, FIGI or CUSIP where licensed, instrument type, currency, active dates, ticker changes, and provider mappings.
3. Make symbol resolution search the security master first, then query configured providers and persist newly validated records.
4. Add per-security coverage diagnostics for adjusted prices, fundamentals, classifications, earnings, valuation inputs, news, and minimum usable history.
5. Build ETF issuer adapters in priority order by assets and user demand, storing complete dated holdings snapshots rather than overwriting the latest snapshot.
6. Reconcile constituent identifiers, weights, cash, derivatives, and “other” exposure; verify that reported weights explain the fund total within a documented tolerance.
7. Add scheduled refreshes based on issuer frequency and mark delayed, stale, partial, unavailable, or provider-blocked holdings distinctly.
8. Preserve the research-idea boundary. If personalized recommendations are ever introduced, build a separate suitability, conflict, disclosure, approval, audit, and legal-review workflow rather than changing research-card wording alone.

Acceptance criteria:

- Symbol and company-name lookup reports the searched universe and why an instrument is unsupported.
- Every result exposes field-level coverage and never substitutes neutral defaults for missing evidence.
- ETF detail pages report holdings as-of date, coverage percentage, unexplained weight, provider, and freshness.
- Research ideas continue to state why they appeared, what was excluded, and what would invalidate the view.

Acceptance status: met for the supported core U.S. universe. ADR, OTC, international, delisted, newly listed, and provider-blocked coverage remains explicitly conditional rather than being silently treated as supported.

### Phase 4 — Portfolio

Implemented:

- Manual and flexible CSV import, save, duplicate-symbol handling, holdings diagnostics, hypothetical reconstructed return labeling, concentration, overlap, costs, tax completeness, and historical risk evidence.
- Four implementation paths: Current / do nothing, contributions only, gradual transition, and immediate transition.
- Next-contribution evidence and transparent optimizer alternatives.
- Expert-only covariance, shrinkage, walk-forward, and model diagnostics.
- A separate additive account ledger now supports transaction CSV review, broker-column aliases, duplicate detection, buys, sells, deposits, withdrawals, dividends, income, fees, splits, and transfers.
- Transaction reconstruction remains separate from the current holdings snapshot.
- Actual account performance uses reconciled valuations for time-weighted return and dated external cash flows for money-weighted return; it is never inferred from today's weights.
- Statement reconciliation records market-value and cash differences against a documented tolerance.
- Imported acquisition lots report included lots, jurisdiction assumptions, missing information, and explicitly unavailable wash-sale coverage.

Unsupported or conditional:

- Actual account return requires transaction, deposit, withdrawal, dividend, and historical-position records. Current reconstructed performance is explicitly hypothetical.
- Tax-lot selection, wash sales, trading, custody, and brokerage execution are not implemented.

Completed remediation:

1. Add additive, RLS-protected account, transaction, cash-flow, security-lot, corporate-action, and income-event tables; do not repurpose current holdings snapshots.
2. Support transaction CSV imports with broker-specific mappings and a review screen for unknown columns, transfers, splits, reinvestments, fees, and duplicate records.
3. Reconstruct daily positions and cash balances from the ledger, then reconcile them against imported statements before calculating performance.
4. Implement time-weighted return for strategy performance and money-weighted return for the investor experience, with dividends, fees, deposits, and withdrawals explicitly included.
5. Keep hypothetical current-weight performance beside—but visually distinct from—actual account performance.
6. Add deterministic tax-lot estimates using acquisition date, basis, holding period, account type, and jurisdiction assumptions; label unavailable inputs instead of estimating them silently.
7. Add wash-sale detection only after cross-account transaction coverage is sufficient; otherwise disclose that the check is incomplete.
8. Treat brokerage connection and execution as a later regulated integration requiring provider security review, explicit user confirmation, order previews, idempotency, audit logs, and specialized legal review.

Acceptance criteria:

- Imported ledgers reconcile to statement market value and cash within a documented tolerance.
- Time-weighted and money-weighted results pass golden fixtures covering deposits, withdrawals, dividends, splits, and fees.
- No hypothetical result is labeled actual.
- Tax estimates list included lots, missing accounts, jurisdiction assumptions, and wash-sale coverage.
- No trade is sent without a separately approved execution phase.

Acceptance status: the ledger, reconciliation, return, and tax-coverage contracts are implemented and covered by golden fixtures. Actual results remain unavailable until a user imports complete transactions and dated statement valuations; brokerage execution and wash-sale conclusions remain intentionally outside scope.

### Phase 5 — Ask EagleEyes and Plan

Implemented:

- Deterministic Plan → Spec → DAG → verified widget flow.
- Progressive rendering, partial success, verified narration, board revision, add/remove/resize, save/reopen/rename/duplicate/delete, and immutable runs.
- Multiple goals, projections, account allocation validation, optional suitability context, and an approvable investment policy.
- Plan now explains that research does not require profile completion and separates essential inputs from optional household context.
- Every board stores and displays its guidance-level decision, context used, missing or stale context, and calculation version.
- Personalized Guidance now requires current holdings, risk tolerance, loss capacity, required risk, tax/account context, liquidity needs, at least one relevant goal, and an approved investment policy.
- Required-evidence verification checks ready data, widget verification, units, periods, freshness, named entities, requested factors, and requested benchmarks before narration.

Unsupported or conditional:

- Gemini interprets intent and narrates validated facts; it does not calculate results or run arbitrary SQL/code.
- Personalized Guidance is only labeled when saved portfolio and profile context justify it. Otherwise the app explicitly labels the answer General Market Research or Portfolio-Aware Analysis.

Completed remediation:

1. Preserve the LLM restriction as a safety control: Gemini may plan intent and explain validated results, but deterministic services remain the only source of numbers, rankings, and portfolio changes.
2. Expand supported intents through versioned `DashboardPlan` schemas and deterministic spec-compiler mappings rather than allowing generated code or arbitrary queries.
3. Add required-evidence rules for every new intent, including exact factors, entities, benchmarks, units, periods, and minimum data quality.
4. Grow the AI evaluation suite with realistic and adversarial prompts; reject or clarify unsupported requests before building a misleading board.
5. Add a progressive suitability-completeness model that identifies which missing Plan fields could materially change a requested answer.
6. Ask only for those fields, explain why each matters, and allow the user to continue with a lower guidance level.
7. Require an approved investment policy, current portfolio, tax/account context, risk tolerance, loss capacity, required risk, liquidity needs, and relevant goal data before labeling output Personalized Guidance.
8. Store the guidance-level decision, inputs used, missing context, calculation versions, and narrative verification with every board run.
9. Obtain specialized securities counsel review before converting research output into individualized buy, sell, or account recommendations.

Acceptance criteria:

- Unsupported prompts receive a useful clarification or limitation instead of substituted evidence.
- Every generated widget passes entity, factor, benchmark, unit, timeframe, lineage, and freshness verification.
- Changing the narrator never changes a numeric result.
- Personalized Guidance cannot be emitted when its required context is missing or stale.
- Partial widget or narrative failure preserves successful deterministic evidence.

Acceptance status: met. Gemini remains limited to intent interpretation and narration; deterministic application services remain the source of numbers, rankings, factors, comparisons, and portfolio alternatives.

### Phase 6 — Advanced and integrity

Implemented:

- Manual customizable terminal, saved layouts, diagnostics, validation, lineage, and provider-health views.
- Simple, Detailed, and Expert presentation transforms preserve identical stored numeric results.
- Scenario dimensions support economic, inflation, rate, and independent-shock evidence without forcing overlapping events into one 100% distribution.
- Existing model versions, immutable runs, RLS ownership, and cache versions remain intact.

Unsupported or conditional:

- Some diagnostics remain inconclusive when securities lack a full market cycle, regimes have small sample counts, or live providers are unavailable.
- The skipped production-smoke tests mean passing deterministic tests does not prove current external-provider availability.
- Model monitoring records evidence but does not yet constitute an automated production promotion system.

Remediation steps:

1. Enforce minimum-history policies by calculation type and route inadequate securities to disclosed sector or broad-market proxies.
2. Expand adjusted-price history to at least one full cycle when available and record start date, end date, missing sessions, corporate-action treatment, provider, and fallback.
3. Accumulate point-in-time macro labels and prediction-market snapshots so walk-forward validation does not substitute current mappings for unavailable historical probabilities.
4. Define model promotion gates for calibration, Brier score, benchmark performance, covariance conditioning, regime sample counts, turnover stability, data freshness, and reproducibility.
5. Run validation automatically after major provider or methodology changes and store immutable candidate, benchmark, decision, approver, and rollback records.
6. Enable credentialed smoke tests in a dedicated non-production account for Supabase RLS, FRED, prices, SEC, Kalshi, Polymarket, ETF providers, and Gemini.
7. Add structured operational alerts for provider failures, stale evidence, cache anomalies, verification failures, latency, and model-coverage deterioration.
8. Document backup, restore, migration rollback, secret rotation, and provider-failure procedures; rehearse them before production launch.

Acceptance criteria:

- Advanced distinguishes “validated,” “inconclusive,” and “failed” rather than treating missing evidence as a pass.
- Every model result links to an immutable validation run, data window, calculation version, and benchmark.
- No challenger becomes the production model without a recorded promotion decision.
- Credentialed smoke tests run on a schedule without exposing secrets or modifying production user data.
- A failed provider or model promotion can be rolled back while retaining historical runs.

## Recommended remediation order

1. Finish Phase 1 component extraction to lower change risk.
2. Build Phase 6 live-provider smoke tests, coverage gates, monitoring, and rollback procedures.
3. Complete the Phase 3 security master and ETF holdings coverage.
4. Improve Phase 2 event coverage and add intraday data only where its user value justifies licensing.
5. Add the Phase 4 transaction ledger and actual-performance calculations before advanced tax features.
6. Expand Phase 5 supported intents and progressive suitability only after deterministic evidence services are complete.
7. Consider brokerage execution or personalized recommendations only as separately approved, legally reviewed product phases.

## Verification

- Frontend build and Node regression tests: 15 passing.
- TypeScript: passing.
- Backend: 141 passing, 9 environment-dependent smoke tests skipped.
- Playwright browser workflows: 10 passing, including login refresh, portfolio import, legacy redirects, terminal persistence, AI board editing, partial failure, stale fallback, presentation levels, and cross-user isolation.

The skipped backend tests require live provider credentials or an explicitly enabled production-smoke environment; deterministic mocks do not prove live provider availability.
