# EagleEyes Phase 3 — Ask execution, deadlines, and idempotency

Date: 2026-08-22

## Verdict

The real `/api/chat/messages` acceptance path now uses a typed, bounded capability DAG. The process-wide analysis slot is gone. One request-wide absolute deadline starts in middleware before authentication, node and database timeouts are capped by remaining time, Gemini is optional and separately bounded, and final Ask persistence is replay-safe by `request_id`.

No Phase 4/5 analytical semantics were changed. Nothing was deployed, committed, or pushed.

## Execution architecture

```text
Ask request (request_id + middleware start)
  → typed CapabilityExecutionPlan
  → bounded per-request DAG (default max 3)
  → NodeOutcomes / canonical DependencyResults
  → AnalysisResult
  → existing capability verification
  → deterministic renderer
  → optional Gemini within remaining narration budget
  → staged result
  → atomic/idempotent assistant + artifacts + request completion
```

The executor is deliberately small and read-oriented. It does not execute full simulations, optimizers, backtests, broad research rebuilds, portfolio rebuilds, or qualitative AI loops.

## Execution schemas

`CapabilityExecutionPlan` contains `request_id`, `capability`, `absolute_deadline_monotonic`, `initial_budget_ms`, typed `nodes`, and `max_concurrency`.

`ExecutionNode` contains `node_id`, `dependency_name`, `required`, `depends_on`, `expected_latency_class`, `configured_timeout_ms`, and an executor callable.

`NodeExecutionContext` carries the request/capability/node identity, deadline, configured/effective timeouts, and start time. `NodeOutcome` records start/end/latency, remaining budget at both boundaries, safe error class, read-model metadata, and one of:

- `SUCCESS`
- `UNAVAILABLE`
- `FAILED`
- `TIMED_OUT`
- `SKIPPED_DEADLINE`
- `SKIPPED_DEPENDENCY`

`DeadlineContext` stores the request start and absolute monotonic deadline and derives `remaining_ms()` at use time.

## Concurrency and cancellation

The old process-wide `CHAT_ANALYSIS_CONCURRENCY=1` semaphore was removed. Each request now owns a bounded thread pool, defaulting to three nodes and capped at four by the Ask integration (the generic executor hard-caps at eight). Independent requests therefore do not share a serialized application slot. DB pool/connection limits remain the resource boundary.

Independent nodes begin together; dependent nodes begin only after every parent succeeds. A failed parent produces `SKIPPED_DEPENDENCY`. If required paths become impossible, pending optional work is skipped and safely cancellable futures are cancelled.

Python cannot forcibly stop an already-running thread. The implementation therefore does not claim that such work was cancelled. It stops waiting, marks the node timed out, and bounds DB connect/statement time through a thread-local timeout. Heavy non-cancellable CPU work is excluded from this executor.

## Deadline behavior

Middleware records `request_started_monotonic` before authentication. Ask creates a ten-second absolute deadline from that original time. Each node calculates remaining time immediately before submission and uses:

```text
effective_timeout_ms = min(configured_node_timeout_ms, remaining_request_ms)
```

A node with less than the minimum start budget is `SKIPPED_DEADLINE`. DB connect and statement timeouts inherit the effective node timeout. Gemini starts only with at least 750 ms remaining and receives a separate budget of at most 2.5 seconds and never more than request time remaining. Gemini timeout/failure returns the already-built deterministic answer.

Authentication is now bounded to a four-second HTTP attempt plus only the remainder of an eight-second total fallback window. Auth latency is included in user-visible deadline accounting and request telemetry. It remains a latency risk when Supabase auth is degraded because it can consume most of the ten-second Ask budget, but it can no longer consume two unbounded sequential timeout windows.

## Capability execution registry

`portfolio_context` is a required in-memory parent whenever the request is portfolio-bound. Acceptance capability dependencies are:

| Capability | Required | Optional |
|---|---|---|
| OPPORTUNITY_RANKING | portfolio_overview | thesis_status |
| THESIS_REPLACEMENT | thesis_replacement | thesis_status |
| PORTFOLIO_CHANGE | portfolio_change | thesis_status |
| VALUATION_RANKING | valuation_ranking | portfolio_data_quality |
| HIDDEN_RISK | portfolio_intelligence | thesis_status, portfolio_scenario |
| MULTI_SCENARIO | portfolio_scenario | portfolio_risk |
| WATCHLIST_COMPARISON | watchlist_comparison | portfolio_data_quality |
| PORTFOLIO_EVENTS | portfolio_events | thesis_status |
| DATA_QUALITY | data_quality | — |
| SCORE_ATTRIBUTION | score_attribution | thesis_status |
| THESIS_INVALIDATION | thesis_invalidation | — |
| PORTFOLIO_ANALYSIS | portfolio_analysis | portfolio_risk |
| MULTIFACTOR_SCREEN | multifactor_screen | portfolio_data_quality |
| RECOMMENDATION_COUNTERCASE | recommendation_countercase | thesis_status |
| CASH_ALLOCATION | cash_allocation | portfolio_data_quality |

These names are capability/read-model architecture names, not acceptance-question string rules. Ask continues to load compatible Phase 2 read models and never rebuilds analytics synchronously.

Required timeout/unavailability prevents a SUCCESS claim and preserves safe diagnostic context. Optional timeout/unavailability becomes an explicit warning but does not destroy an otherwise verified result; final SUCCESS/PARTIAL semantics remain with the existing capability verifier.

## Idempotency and persistence

Migration `202608220002_idempotent_ask_requests.sql` introduces lifecycle states `RECEIVED`, `EXECUTING`, `EXECUTED`, `COMPLETED`, `PARTIAL`, `UNAVAILABLE`, `FAILED`, and `PERSISTENCE_FAILED`.

- The client may provide `request_id`; otherwise middleware generates it at request entry.
- `request_id` is bound to the authenticated user and a hash of question/workspace/page context. Reuse for different input is rejected.
- User and assistant message IDs are deterministic UUID5 values derived from `request_id`, so upserts cannot duplicate turns.
- The user turn is inserted once while the request transitions to `EXECUTING`.
- The computed response is staged as `EXECUTED` before final materialization.
- Assistant message, artifact links, durable replay response, and terminal request state are written in one Postgres transaction.
- A completed retry returns the stored response and is tagged as a duplicate replay.
- If final persistence fails after computation, the staged result remains with `PERSISTENCE_FAILED`; retry completes it without recomputation or duplicate turns.
- Known validation failures mark the request terminal rather than leaving it in `EXECUTING`.

## Telemetry

Request telemetry now includes request/capability identity, absolute deadline, initial budget, zero application queue wait, auth latency, execution start/end, node totals/started/completed/timed-out/skipped, total execution, result and verification status, deterministic render time, Gemini attempted/completed/latency, persistence latency/status, error class, and replay status.

Every node records node/dependency identity, required flag, parent IDs, relative start/end, latency, remaining budget at start/end, configured/effective timeout, status, safe error class, and read-model state/ID/fingerprint compatibility where applicable.

## Tests

Focused Phase 3 tests: **8 passed**.

- Three independent 500 ms nodes overlap and finish near one node's duration.
- An unrelated fast request completes while a slow request is still running.
- A dependent node is capped by the small remaining deadline rather than its five-second configured timeout.
- Required and optional timeout composition is explicit and safe.
- Failed parents skip children without executing them.
- Replaying an identical `request_id` creates one logical result.
- A staged result recovers from late persistence failure without recomputation.

Full backend suite: **447 passed, 9 skipped, 0 failed**. The two warnings are an upstream Starlette/httpx deprecation and a pandas future-behavior warning.

## Ask-15 Gemini-disabled baseline

Phase 3 exactly preserves Phase 2:

| Metric | Phase 2 | Phase 3 |
|---|---:|---:|
| SUCCESS | 8 | 8 |
| PARTIAL | 2 | 2 |
| UNAVAILABLE | 5 | 5 |
| FAILED | 0 | 0 |
| Deterministic answers | 15/15 | 15/15 |
| CURRENT read models | 15/15 | 15/15 |
| Fingerprint matches | 15/15 | 15/15 |
| Legacy adapters | 0 | 0 |
| Persistence success | not previously recorded | 15/15 |

All 44 recorded DAG nodes completed as 39 SUCCESS and 5 analytical UNAVAILABLE; none timed out or were skipped in this replay. Median local end-to-end handler time was 4.017 s and observed p95 was 4.166 s (15 samples). The detailed artifact lists every question, capability, required/optional node, timing/deadline data, result, verification, read-model state, deterministic answer, and persistence status.

## Local performance benchmark

Synthetic I/O benchmark, 30 ms per node unless noted:

| Scenario | Samples | p50 | p95 |
|---|---:|---:|---:|
| Single capability read | 25 | 34.80 ms | 35.99 ms |
| Two independent nodes | 25 | 35.54 ms | 37.08 ms |
| Three independent nodes | 25 | 35.70 ms | 37.31 ms |
| Four concurrent requests | 20 | 36.68 ms | 39.80 ms |
| Fast request beside 250 ms slow request | 20 | 35.61 ms | 37.86 ms |

The old/theoretical sequential time is 60 ms for two nodes and 90 ms for three; observed concurrent p50 remained about 36 ms. This proves local overlap and isolation, not production SLO compliance.

## Remaining risks and later phases

Phase 4 remains responsible for opportunity semantics, replacement dominance, cash hurdle, factor trends, score-attribution gaps, exact scenario support, and tax/turnover semantics. The five unavailable acceptance answers were intentionally not repaired here.

Phase 5 remains responsible for durable optimizer jobs, simulations, backtests, and qualitative thesis monitoring. Running threads cannot be forcibly cancelled; heavy work must remain outside this executor and move to durable workers.

Operationally, the new SQL migration must be applied before this code is released. Authentication degradation can still consume a large fraction of the request budget. Simultaneous in-flight duplicates may both perform read-only execution before one wins idempotent final persistence, although they cannot duplicate conversation turns or artifact links; cross-process single-flight coordination is intentionally deferred.
