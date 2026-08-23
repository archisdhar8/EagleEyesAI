# EagleEyes Phase 2 — Versioned Capability Read Models

Date: 2026-08-22

## Verdict

The Phase 1 Ask acceptance path now prefers persisted, capability-specific read models, checks request fingerprints and every recorded upstream version centrally, and uses the old `portfolio_health_snapshot.ask_cache` only as an explicit compatibility adapter when no new model is available. Dependency invalidation, missed-event reconciliation, freshness bounds, history preservation, compatibility rejection, and the real Ask path are directly tested.

**PHASE 2 COMPLETE**

## Architecture

```text
portfolio/provider/thesis/scenario/optimizer data
                    |
                    v
      analytical_dataset_versions
                    |
                    v
         dependency registry
                    |
       invalidate now / rebuild later
                    |
                    v
     capability-specific builders
                    |
                    v
 capability_read_models (append-only history)
                    |
          compatibility loader
                    |
                    v
 Ask router -> Phase 1 verifier -> deterministic renderer -> optional Gemini
                    ^
                    |
 portfolio_health_snapshot.ask_cache (missing-model compatibility only)
```

Storage/build state (`CURRENT`, `STALE`, `BUILDING`, `FAILED`, `MISSING`) is separate from analytical status (`SUCCESS`, `PARTIAL`, `UNAVAILABLE`, `FAILED`, `PENDING`). A current model may legitimately contain a partial analysis. A failed rebuild is appended and does not delete its prior valid model.

## Snapshot Findings and Migration Boundary

The old `portfolio_health_snapshots.result` contains portfolio health/components, holding metrics, changes, warnings, actions, input hash, methodology/effective timestamps, and an embedded `ask_cache`. The cache contained portfolio intelligence, watchlist research, latest simulation, latest optimizer, portfolio events, scenario probabilities, and a top-level generation time.

It was rebuilt after portfolio create/update/import, manual overview refresh, nightly Today refresh, and high-materiality Today events. It depended broadly on saved holdings, security prices/fundamentals/research, classifications, active theses and monitors, goals/policy/profile, Today briefing/events, watchlist research, scenario runs, and optimizer runs. Ask treated the snapshot as one freshness unit and overlaid request-context holdings; optimizer and scenario paths carried additional compatibility checks.

Phase 2 retains this document for the Today UI and fallback. New overview rebuilds project its completed deterministic computations into independent read models. Ask does not build or broadly calculate analytics in the request.

## Read Model Contract

All models use schema version `1`, builder version `ask-read-model-builder-v1`, the canonical Phase 1 `Coverage` and `Freshness` types, an analytical status, a separate storage state, a portfolio/input fingerprint, calculation version, timestamps, and a map of relevant upstream versions.

| Read model | Required dependencies | Optional dependencies | Calculation version |
|---|---|---|---|
| `portfolio_opportunity` | holdings, prices, fundamentals | classification, theses | `portfolio-opportunity-read-v1` |
| `portfolio_risk` | holdings, prices, classification | theme mappings, theses | `portfolio-risk-read-v1` |
| `portfolio_change` | holdings | health history, theses | `portfolio-change-read-v1` |
| `portfolio_factor_state` | holdings, prices, fundamentals | — | `portfolio-factor-state-read-v1` |
| `watchlist_comparison` | holdings, profile, prices, fundamentals | theses | `watchlist-comparison-read-v1` |
| `portfolio_events` | holdings | earnings, macro calendar, company catalysts | `portfolio-events-read-v1` |
| `portfolio_data_quality` | holdings, prices, fundamentals | provider state | `portfolio-data-quality-read-v1` |
| `score_attribution` | holdings, prices, fundamentals | health history | `score-attribution-read-v1` |
| `thesis_status` | holdings, theses | thesis monitor | `thesis-status-read-v1` |
| `portfolio_scenario` | holdings, scenario model | macro state, prediction markets | `portfolio-scenario-read-v1` |
| `optimizer_compatibility` | holdings, constraints, optimizer config | tax lots | `optimizer-compatibility-read-v1` |

Portfolio compatibility uses the canonical normalized eligible-holdings context fingerprint. Other inputs use stable content fingerprints, provider/source effective times, or the stored run payload identity. Required and optional upstream versions are recorded only where the capability declares them.

`calculated_at` is build time. `effective_through` and `oldest_required_input` come from required input evidence; build time never advances an older fundamental or price observation.

## Invalidation Matrix

`X` means the dependency registry invalidates that capability.

| Upstream change | Opportunity | Risk | Change | Factors | Watchlist | Events | Quality | Score | Thesis | Scenario | Optimizer |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Portfolio holdings | X | X | X | X | X | X | X | X | X | X | X |
| Prices | X | X |  | X | X |  | X | X |  |  |  |
| Fundamentals | X |  |  | X | X |  | X | X |  |  |  |
| Classification | X | X |  |  |  |  |  |  |  |  |  |
| Profile/watchlist |  |  |  |  | X |  |  |  |  |  |  |
| Thesis | X | X | X |  | X |  |  |  | X |  |  |
| Earnings/company events |  |  |  |  |  | X |  |  |  |  |  |
| Macro state |  |  |  |  |  |  |  |  |  | X |  |
| Prediction markets |  |  |  |  |  |  |  |  |  | X |  |
| Scenario model/run |  |  |  |  |  |  |  |  |  | X |  |
| Optimizer/config |  |  |  |  |  |  |  |  |  |  | X |
| Tax lots |  |  |  |  |  |  |  |  |  |  | X |

Portfolio mutations are invalidated and followed by the existing bounded background overview rebuild. Profile, thesis, price, fundamentals, macro, prediction-market, scenario, and optimizer update paths issue targeted invalidations. Security-specific updates are bounded to the user's portfolios containing the updated ticker set.

`scripts/reconcile_read_models.py` is the durable scheduler/cron entry point. It enumerates persisted read-model scopes, reconstructs the current portfolio fingerprint, compares all recorded dependency versions, and marks missed mismatches stale. Reconciliation does not depend on a Today or Ask page read and does not rebuild inside Ask.

## Builders

The implemented named builders are:

- `build_portfolio_opportunity_read_model`
- `build_portfolio_risk_read_model`
- `build_portfolio_change_read_model`
- `build_portfolio_factor_state_read_model`
- `build_watchlist_comparison_read_model`
- `build_portfolio_events_read_model`
- `build_portfolio_data_quality_read_model`
- `build_score_attribution_read_model`
- `build_thesis_status_read_model`
- `build_portfolio_scenario_read_model`
- `build_optimizer_compatibility_read_model`

They reuse the existing deterministic overview/research/diagnostic outputs. No new opportunity, scoring, scenario, or optimization methodology was introduced.

## Ask Compatibility

All Ask-15 cached tools are mapped to the new models. The centralized loader returns `CURRENT`, `STALE`, `INCOMPATIBLE`, or `MISSING` and verifies:

- request portfolio/input fingerprint;
- schema version;
- calculation version;
- every declared required and optional upstream version;
- persisted build state.

A bounded stale model may be disclosed as `PARTIAL`; an incompatible model is unavailable. Missing new storage/model rows use the old snapshot adapter with `legacy_adapter_used=true`. The Phase 2 baseline used zero legacy adapters.

Production migration/backfill is intentionally not applied in this task. Until the included database migration is applied and overview models are rebuilt, deployed instances safely remain on the explicit legacy adapter.

## Telemetry

Request/dependency and build/invalidation telemetry now includes allowlisted fields for read-model type/id/state, schema/calculation/builder versions, cache hit, legacy use, fingerprint match, upstream match, stale reason, changed upstream dependency, build status, and build latency. Raw exceptions are not exposed to users. Evaluation telemetry was non-durable.

## Tests

New direct tests cover:

- all 11 builders and persisted metadata;
- portfolio mutation, invalidation, and rebuilt fingerprints;
- price and fundamentals matrices;
- thesis-, macro-, and prediction-market-only invalidation;
- required and optional missed-event reconciliation;
- build-time versus seven-day-old fundamentals freshness;
- portfolio, schema, calculation, dependency, optimizer, and scenario incompatibility;
- failed rebuild history preservation;
- the real Ask acceptance path using every mapped model with no legacy adapter.

Focused Phase 2/contract/telemetry tests pass. The full backend suite is **436 passed, 9 skipped, 3 failed** with two warnings. The only failures remain the three Phase 1-known expectation drifts around Gemini defaults and one deterministic wording assertion.

## Ask-15 Baseline

| Result | Phase 1 | Phase 2 |
|---|---:|---:|
| `SUCCESS` | 8 | 8 |
| `PARTIAL` | 2 | 2 |
| `UNAVAILABLE` | 5 | 5 |
| `FAILED` | 0 | 0 |
| Deterministic answer returned | 15/15 | 15/15 |
| Current capability model | — | 15/15 |
| Legacy adapter | — | 0/15 |
| Fingerprint match | — | 15/15 |

The two partial results remain multi-scenario coverage and event-calendar coverage. The unavailable results remain thesis replacement, portfolio change, score attribution, thesis invalidation, and optimizer/rebalance due to genuine missing baselines/prerequisites/compatibility. Semantics were not inflated to improve counts.

Detailed results: `artifacts/ask-15-phase2-gemini-disabled.md` and `.json`.

## Local Read Benchmark

This is a 200-read-per-model SQLite development benchmark, not a production SLO claim.

| Model | p50 ms | p95 ms |
|---|---:|---:|
| Opportunity | 0.612 | 0.707 |
| Risk | 0.613 | 0.674 |
| Valuation/factor state | 0.611 | 0.686 |
| Portfolio change | 0.602 | 0.683 |
| Events | 0.568 | 0.651 |
| Scenario | 0.566 | 0.620 |
| Watchlist comparison | 0.607 | 0.693 |

These retrievals are materially cheaper than rebuilding research, covariance diagnostics, simulations, or optimizations, but production database/network latency must be measured after migration.

## Remaining Risks and Phase 3 Boundary

- The executor is still sequential and retains the global analysis slot.
- Deadlines are observable but not yet an enforceable concurrent dependency DAG.
- Required and optional dependencies are modeled in read models but tool execution is not yet concurrent by dependency criticality.
- Request/message persistence is not yet fully idempotent.
- Reconciliation has a durable CLI entry point but still needs deployment scheduler configuration after approval.
- Provider invalidation is user/portfolio bounded at authenticated refresh entry points; a future global ingestion event stream should fan out by held symbols without scanning broad scopes.
- The legacy snapshot remains necessary until migration and backfill are completed.

No deployment, commit, push, UI redesign, planner work, worker migration, timeout increase, or Phase 3 work was performed.
