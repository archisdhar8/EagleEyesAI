# EagleEyes Phase 8 — Contextual Conversational Dashboard Canvas

Date: 2026-08-22

## A. UX architecture

```text
chat only
→ explicit visual request or existing-view open
→ chat + contextual canvas (38% / 62% desktop)
→ close canvas
→ chat only, with analysis state preserved
→ click the dashboard title / Open analysis
→ the same draft or saved view reopens
```

Ask no longer reserves empty canvas space. The desktop canvas is a contextual split surface with minimum pane widths. Its header contains the view selector, save/state controls, an overflow menu, and a clear close button. History is a drawer and saved Research Views live in the canvas selector rather than permanent rails.

## B. Dashboard contracts

`DashboardPlan` (`dashboard-plan-v1`) contains the user goal, title, canonical `source_result_ids`, and bounded widget plans. `DashboardWidgetPlan` (`dashboard-widget-plan-v1`) contains a stable widget ID, purpose, source result/capability/category, validated visualization and field mapping, title, layout, widget state, and optional durable-job reference. Materialized dashboard specs use `dashboard-spec-v3` and `verified-result-dashboard-compiler-v1`.

Widget IDs derive from capability + canonical data path + semantic title, not result fingerprints. They therefore survive refreshed results, rerenders, layout changes, revisions, and conversational follow-ups. Each widget independently stores `source_result_id` (`result_<fingerprint>`), `source_capability`, and one of `VERIFIED`, `MODEL_OUTPUT`, `MARKET_IMPLIED`, or `USER_THESIS`.

The supported widget-state vocabulary is `CURRENT`, `STALE`, `REFRESHING`, `PARTIAL`, `UNAVAILABLE`, `FAILED`, and `PENDING`. The renderer maps these into independent ready, stale, loading, partial, unavailable, failed, or durable-job placeholder states.

The existing typed `DashboardAction` system now validates `CREATE_WIDGET`, `UPDATE_WIDGET`, `DELETE_WIDGET`, `MOVE_WIDGET`, `RESIZE_WIDGET`, `CHANGE_VISUALIZATION`, `UPDATE_FILTER`, `UPDATE_DATE_RANGE`, `RENAME_DASHBOARD`, and `CLEAR_DASHBOARD`, in addition to existing save/duplicate/undo flows. Mutations return `SUCCESS`, `INVALID`, `UNSUPPORTED`, or `FAILED`; widget, result-reference, visualization, filter/date, and layout inputs are schema-checked before mutation.

## C. Analytical integration

The implemented boundary is:

```text
User question
→ direct deterministic route or registered CapabilityPlan
→ verified AnalysisResult / ComposedAnalysisResult
→ presentation-only DashboardPlan
→ validated DashboardAction / existing dashboard artifact
```

The dashboard compiler receives canonical results after normal Phase 7 execution. It can select a registered field, chart type, and layout, but it cannot call financial tools or calculate metrics. Widget data is an exact canonical result subtree. Unsupported shapes/visualizations are rejected, and generic results fall back to a table rather than inferred numbers. Requests requiring additional data—benchmark/date changes, market-regime comparisons, risk contributors, and backtests—return through the existing capability boundary. Heavy capabilities retain their durable `PENDING` job reference.

Supported mappings cover portfolio risk, company analysis/comparison, macro state, market state, prediction markets, scenarios, and backtests. Multi-result plans select at most eight widgets. Partial and unavailable canonical results do not block valid sibling widgets.

## D. Canvas rules

- Auto-open: explicit dashboard, chart, graph, plot, table, heatmap, visualization, canvas/widget, or clear “show/open analysis” requests; opening a saved artifact also opens it.
- Stay closed: ordinary analytical questions, including company valuation, macro state, thesis risk, and portfolio facts, unless the user elects to visualize.
- Close: changes only canvas visibility. It does not delete the draft/view, widgets, conversation, revisions, results, or pending jobs.
- Reopen: the header shows the active analysis title when a conversation has a draft/view. Reopening uses the same dashboard state.
- Mobile: Chat is the default. An opened artifact exposes explicit `Chat | Analysis` tabs while retaining both panes' state.

## E. Conversational editing

References resolve against stable IDs, semantic titles/types, grid position, recent widget/action context, and active result references. Phrases such as “that chart,” “sector exposure,” “top right,” and “bottom table” resolve deterministically. A destructive ambiguous request, such as “Delete the chart” with several candidates, produces a short clarification and makes no mutation.

Move, resize, remove, rename, visualization-only changes, save, duplicate, and undo remain presentation/persistence operations. Filters, date ranges, new benchmarks, new capability comparisons, backtests, and canonical refreshes are marked `requires_new_analysis` and route through Phase 7. The canonical refresh path reruns the prior registered capability, replaces the result for the same stable widget ID, preserves the existing grid, and records the new source result reference.

## F. Persistence

Phase 8 reuses existing dashboard jobs for drafts, saved dashboard views for persistence, dashboard revisions for undo, and conversation-artifact links. New verified widgets merge into the active draft; an edit to a saved view derives a draft while retaining its source view. Save/rename/duplicate/undo continue through existing database methods. Structured conversation context records active dashboard/revision/widget IDs, recent widget/action, and widget-to-result references rather than relying on prose.

## G. Staleness and asynchronous work

Canonical freshness and invalidation state map into widget state; stale results render “Updated data available” and are not presented as current. Refresh re-enters normal analysis and never calculates in the frontend or legacy dashboard calculator for Phase 8 dashboards. A pending backtest renders its durable job reference and a local placeholder while other widgets remain usable. `PARTIAL`, `UNAVAILABLE`, and `FAILED` states are widget-scoped, so one missing capability cannot create a global dashboard failure.

## H. Phase 8 files changed

| Path | Purpose | Major Phase 8 modification |
|---|---|---|
| `backend/dashboard_presentation.py` | Verified result-to-dashboard compiler | Added typed plans, supported field/visual mappings, stable IDs, source classification, widget states, exact-subtree rendering, draft/view materialization, merge and refresh replacement. |
| `backend/main.py` | Ask orchestration/API integration | Runs analysis-requiring visual requests through Phase 7, materializes verified dashboards, attaches operations/plans, and persists structured dashboard context. |
| `backend/dashboard_chat.py` | Natural-language dashboard intent | Distinguishes presentation-only mutations from new analysis; supports visual follow-ups, risk, regime, backtest, and canonical refresh requests. |
| `backend/dashboard_actions.py` | Typed mutation validation | Added/validated visualization, filter, and date-range actions plus canonical source references and typed outcomes. |
| `backend/ask_orchestration.py` | Existing analytical planner routing | Added registered backtest/market/risk patterns and reuse of prior active capabilities for visualize/refresh follow-ups. |
| `app/components/ask/AskPage.tsx` | Chat-first contextual canvas | Added deterministic open rules, desktop split, close/reopen preservation, mobile tabs, and chat-routed canonical refresh. |
| `app/components/ask/contracts.ts` | Frontend Ask contracts | Added result references, source categories, widget states, and expanded action vocabulary. |
| `app/components/shared/workspace-implementations.tsx` | Existing canvas/widget renderer | Added Phase 8 metadata/states, concise source labels, result IDs, pending/stale/partial rendering, contextual header/refresh, and removed duplicate canvas narrative. |
| `app/globals.css` | Responsive canvas presentation | Added 38/62 split, minimum widths, mobile tab behavior, and source/state styling. |
| `backend/tests/test_dashboard_presentation.py` | Compiler and persistence tests | Covers exact canonical data, stable IDs across refresh, mappings, source classes, pending/partial/stale states, merge, save, and conversation linkage. |
| `backend/tests/test_dashboard_actions.py` | Mutation validation tests | Covers added typed action and result-reference validation. |
| `backend/tests/test_dashboard_chat.py` | Conversational editing tests | Covers creation, references, ambiguity, analysis boundary, risk/regime/backtest, and refresh. |
| `backend/tests/test_ask_orchestration.py` | Planner regression tests | Covers natural-language Phase 8 routing and prior-capability reuse. |
| `tests/ask-canvas-contracts.test.mjs` | Static UI contract tests | Covers chat-first visibility, deterministic open/close/reopen, mobile tabs, lineage, and widget states. |
| `tests/phase9-contracts.test.mjs` | Cross-phase UI contract compatibility | Updated expectations for contextual Ask composition. |
| `tests/model-portfolio-contracts.test.mjs` | Existing UI regression contract | Updated source expectation after shared renderer changes. |
| `tests/e2e/fixtures.ts` | Browser fixtures | Provides dashboard operation data for the contextual flow. |
| `tests/e2e/eagleeyes.spec.ts` | Browser acceptance flow | Verifies chat-only start, explicit visual open, edits, save, close/reopen, persistence, and existing application regressions. |
| `tests/e2e/phase8-screenshots.spec.ts` | Visual evidence | Captures the six required desktop/mobile states. |

No deployment, commit, push, migration execution, or Phase 9 implementation was performed.

## I. Tests

- Focused Phase 8 backend/action/planner suite: 86 passed.
- Full backend suite: 614 passed, 9 skipped, 2 known dependency warnings.
- TypeScript: `tsc --noEmit` passed.
- Frontend build and component/static contracts: build passed; 81/81 tests passed. One existing bundle-size warning remains for chunks above 500 kB.
- Browser/E2E suite: 19/19 passed, including chat-first open rules, contextual canvas, conversational edits, save/undo/reload, partial widgets, isolation, and all six screenshots.
- Phase 6 acceptance: 20/20 passed.
- Phase 7 mixed-domain planner acceptance: 32/32 passed.
- Ask-15 with Gemini disabled: 15/15 deterministic answers and 15/15 persistence successes; analytical outcomes were 6 `SUCCESS`, 4 `PARTIAL`, and 5 explicit `UNAVAILABLE` (no fabricated fallback).
- Explicit coverage includes stable result references, close/reopen, mobile state, pending durable jobs, partial dashboards, stale indicators/refresh routing, ambiguous destructive edits, and exact canonical subtree values.

## J. Screenshots

1. `artifacts/phase8-screenshots/01-chat-only.png` — centered chat with no reserved canvas.
2. `artifacts/phase8-screenshots/02-chat-and-canvas.png` — populated desktop split.
3. `artifacts/phase8-screenshots/03-canvas-closed.png` — expanded chat with analysis reopen control.
4. `artifacts/phase8-screenshots/04-canvas-reopened.png` — same dashboard state restored.
5. `artifacts/phase8-screenshots/05-mobile-chat.png` — mobile Chat tab.
6. `artifacts/phase8-screenshots/06-mobile-analysis.png` — mobile Analysis tab with populated widget.

## K. Remaining UX issues

The contextual experience is materially simpler than the prior permanent builder, but it is not yet a fully polished production interaction. Individual widgets still include an explanatory answer layer before evidence, so dense multi-widget dashboards can feel vertically long. The narrow mobile canvas header wraps to two rows. The desktop divider is fixed rather than user-resizable. Generic canonical tables are safe but could use richer domain-specific renderers without changing the calculation boundary. The production bundle also needs code splitting, and real provider latency/error behavior still needs staging validation.

## L. Phase 9 handoff

Phase 9 should perform the production-readiness and deployment review only: migration/backfill validation, workers and schedulers, observability, security and tenant isolation, load/latency, durable-job recovery, provider failure drills, staging data verification, cross-browser/accessibility checks, deployment configuration, and end-to-end staging tests. Phase 8 deliberately did not execute migrations or begin deployment work.

## M. Verdict

Ask now starts chat-first; the canvas is contextual, closable, and state-preserving; every new visual is bound to verified analytical output; natural-language creation/editing uses typed actions; new analysis returns through Phase 7; heavy/partial/stale states remain honest; and analytical/UI suites have not regressed.

PHASE 8 COMPLETE
