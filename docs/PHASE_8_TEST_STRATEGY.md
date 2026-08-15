# Phase 8 test strategy

## Commands

- `npm test` — production frontend build plus static interaction and compatibility contracts.
- `npm run typecheck` — TypeScript contract verification.
- `.venv/bin/python -m pytest` — backend unit, API, model, migration-contract, and ownership tests.
- `npm run test:e2e` — browser journeys using Playwright and deterministic provider fixtures.
- `npm run test:all` — all of the above.

The browser suite uses the real Supabase client with intercepted test auth responses. It never adds an authentication bypass to the production application.

## Browser contracts

The browser suite covers:

- Password login, forced expired-token refresh, reload, and sign-out.
- Portfolio CSV import, save, Research load, and three-alternative analysis.
- Legacy URL canonicalization.
- Manual terminal add, resize, move, save, reopen, and reset.
- AI board progressive results, revision, add, resize, remove, save, reopen, and exact duplication.
- Optional-widget failure with preserved successful results and narration.
- Stale-provider fallback and no-portfolio general research.
- Simple, Detailed, and Expert transformations over the same stored result.
- Isolated saved-board state across two browser users.

## Golden quantitative contract

`backend/tests/fixtures/golden_quantitative_v1.json` is the versioned input and expected-output contract for:

- Return paths and drawdowns.
- Correlations.
- Sector exposure.
- Candidate filters.
- Research evidence buckets.
- Next-dollar allocation.

The accompanying tests also generate fixed macro histories for factor sensitivity and verify that economic, inflation, rate, and independent-shock dimensions remain composable.

## Compatibility and ownership

- Version-one terminal and AI-board fixtures remain readable without rewriting stored JSON.
- AI specifications and terminal widgets pass through versioned TypeScript adapters.
- Saved boards, revisions, terminal layouts, goals, and jobs use additive schemas.
- Local ownership checks and Supabase RLS-policy contract tests prevent cross-user reads and mutations.

## Phase verification

| Phase | Verified implementation | Remaining boundary |
|---|---|---|
| 1 | Central routes, shell, presentation libraries, versioned adapters, compatibility fixtures | `Dashboard.tsx` still contains the Plan, Portfolio, Ask, and Terminal renderers; extraction is partial and behavior is locked by regression tests. |
| 2 | Market-first Today briefing, deterministic attention rules, event abstraction, no-portfolio and stale states | Live event breadth depends on stored provider coverage. |
| 3 | Stocks, Sectors, Themes, Macro, Scenarios, Prediction Markets, Compare, and Watchlist; disclosed-universe search and word buckets | Broader external consensus/valuation coverage remains provider-dependent. |
| 4 | Progressive suitability profile, goals, policy, next-dollar guidance, diagnostics, costs, overlap, and implementation paths | Actual performance still requires transaction and cash-flow history. |
| 5 | Editable versioned AI boards, required-evidence verification, revisions, exact duplication, partial success | Queue-backed workers remain a later scaling step. |
| 6 | Central presentation transformations and independent composable scenario dimensions | Numeric result generation is intentionally unchanged between presentation levels. |
| 7 | Additive versioned migrations, immutable runs/revisions, ownership and RLS contracts | No destructive migration was introduced. |
| 8 | Browser journeys, golden numeric fixtures, cross-user checks, and a single all-tests command | Browser tests use deterministic API/provider fixtures; separate live-provider smoke tests are still appropriate for deployment monitoring. |
