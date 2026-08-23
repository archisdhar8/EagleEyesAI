# EagleEyes Phase 1 analytical contract and observability report

Date: 2026-08-20 (America/Los_Angeles)

## Outcome

Phase 1 is implemented on the Ask v2 acceptance path. Cached portfolio capabilities now return a canonical `AnalysisResult`; legacy tools are adapted at the executor boundary; deterministic and optional Gemini renderers consume the same verified contract; and request/dependency telemetry records capability-level timing, coverage, freshness, cache, verification, and persistence fields without logging question or answer content.

No UI redesign, deployment, commit, push, general planner, or heavy-job relocation was performed.

## Canonical schema

The schema is defined in `backend/analytical_contract.py`:

- `AnalysisResult`
- `AnalysisStatus`: `SUCCESS`, `PARTIAL`, `UNAVAILABLE`, `FAILED`, `PENDING`
- `Coverage`: entity, required-field, and portfolio-weight coverage
- `Freshness`: calculation time, effective-through time, oldest/newest required inputs, and stale dependencies
- `LineageItem`
- `DependencyResult`: required/optional status, latency, cache state, freshness, coverage, safe error class, and a non-serialized internal error message
- `Prerequisite`
- `VerificationResult` and `VerificationCheck`
- `JobReference`

Shared helpers provide stable fingerprints, non-fabricated legacy adaptation, required/optional dependency status derivation, freshness calculation, full-entity coverage, and request-verifier merging.

Empty strings and empty collections do not count as analytically available. Valid zero and false values do.

## Acceptance-path integration

Files changed:

- `backend/ask_portfolio.py`: canonical cached capability builders, complete internal result sets, explicit prerequisites, calculation versions, coverage, freshness, lineage, and a conservative saved-optimizer adapter.
- `backend/main.py`: canonical adaptation at the Ask executor boundary, one contract for deterministic/Gemini narration, canonical response payloads, shared verification gates, and capability telemetry.
- `backend/ask_runtime.py`: transitional verifier no longer defaults missing coverage to full coverage and no longer divides watchlist entities by total portfolio positions.
- `backend/analytical_telemetry.py`: request/dependency telemetry and one absolute request deadline context.
- `scripts/evaluate_ask_15.py`: exact-portfolio selection and explicit Gemini-disabled contract baseline mode.

The saved optimizer path is diagnostic-only unless all of these are established:

- a saved optimizer run exists;
- its input fingerprint matches the current portfolio context;
- its constraint state is feasible;
- tax-lot coverage is available.

The current saved optimizer lacks sufficient compatibility/tax metadata, so attempted weights are withheld and the result is `UNAVAILABLE`, not a recommendation.

## Observability

`ask.capability.dependency` records:

- request/capability/dependency identity;
- required flag and status;
- start/end timestamps and latency;
- absolute-deadline remaining time at start and end;
- cache state and safe error class.

`ask.capability.request` records:

- request/conversation/capability/intent identity;
- request timing and total latency;
- input fingerprint and calculation/read-model version;
- result and verification status;
- entity, field, and weight coverage;
- calculated/effective-through/oldest-input timestamps;
- Gemini start/completion/latency;
- persistence outcome and required/optional dependency failure names.

Only allowlisted metadata is emitted. Questions, answers, holdings payloads, raw provider data, internal exception messages, and secrets are excluded. Durable events reuse `public.operational_events` from `supabase/migrations/202608100001_operational_monitoring.sql`; no new migration was required.

## Tests

New tests:

- `backend/tests/test_analytical_contract.py`
- `backend/tests/test_analytical_telemetry.py`

They cover entity/field/weight coverage, freshness semantics, required versus optional failures, fingerprint mismatch, infeasible optimizer withholding, missing thesis prerequisites, deterministic rendering with Gemini disabled, telemetry content allowlisting, and absolute deadline propagation.

Focused Phase 1 result: **34 passed**.

The full backend suite produced **419 passed, 9 skipped, and 3 failed**. The three failures are pre-existing expectation drift:

- two tests expect Gemini to run by default, while production currently defaults `ASK_GEMINI_ENRICHMENT` off;
- one wording assertion expects “weakest evidence-ranked,” while the existing answer says “weakest stored evidence profiles.”

These failures are unrelated to the canonical contract behavior and were not hidden or rewritten as part of Phase 1.

## Gemini-disabled 15-question baseline

Artifacts:

- `artifacts/ask-15-phase1-gemini-disabled.md`
- `artifacts/ask-15-phase1-gemini-disabled.json`

Scope: the exact portfolio in the prior baseline, with 61 saved rows and 57 eligible stock/ETF positions. The harness did not save portfolios, conversations, messages, simulations, or durable metrics.

Results:

| Status | Count | Meaning |
|---|---:|---|
| `SUCCESS` | 8 | Complete canonical answer from available stored evidence |
| `PARTIAL` | 2 | Answer delivered with explicit limitation |
| `UNAVAILABLE` | 5 | Safely blocked because a required analytical prerequisite was absent |
| `FAILED` | 0 | No execution failure |

All 15 requests returned complete deterministic responses. The two partial cases were multi-scenario analysis (AI-capex mapping and per-holding coverage not fully available) and the event calendar (per-holding calendar coverage not tracked). The unavailable cases were thesis replacement, since-last-review change, score attribution, thesis invalidation, and rebalance; their missing baselines, saved theses, compatibility, feasibility, or tax-lot prerequisites were disclosed.

## Remaining gaps

- Persist optimizer input fingerprints, normalized constraint status, tax-lot coverage, turnover, and trading-cost assumptions in the optimizer result contract.
- Persist component-level score baselines and historical portfolio snapshots so change and attribution capabilities can become available.
- Track per-holding event-calendar and scenario coverage.
- Populate saved thesis assumptions/breakers for thesis-dependent capabilities.
- Migrate remaining non-acceptance-path analytical endpoints from the legacy adapter to native `AnalysisResult` producers.
- Add production dashboards/alerts over the durable capability events.

## Phase 1 verdict

**Complete for the Ask v2 15-question acceptance path.** The path now fails conservatively, reports real coverage and prerequisites, uses one canonical source for both renderers, and emits capability-level telemetry. The baseline also shows that data-product gaps remain; Phase 1 exposes them rather than manufacturing confident answers.
