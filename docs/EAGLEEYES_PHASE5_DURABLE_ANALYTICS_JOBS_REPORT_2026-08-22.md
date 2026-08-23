# EagleEyes Phase 5: Durable Analytics Jobs

Date: 2026-08-22

## Scope and verdict

Phase 5 moves the five heavy analytical families into a database-backed worker architecture without changing the Phase 1 canonical contract, the Phase 2 dependency registry, the Phase 3 bounded Ask DAG, or the Phase 4 analytical semantics.

The generated Postgres migration was not applied. SQLite development/test initialization creates the same additive tables automatically.

## A. Job architecture

```text
Ask / API request
       |
       v
compatible completed result?
       | yes
       +------------------------> canonical AnalysisResult
       |
       | no
       v
persist QUEUED analytical job
       |
       v
separate analytics worker
  claim + lease + heartbeat
       |
       v
existing analytical engine
       |
       v
typed canonical AnalysisResult
       |
       v
targeted read-model invalidation/rebuild
```

The web process may read a compatible completed result or persist/reference a job. It does not wait for the worker.

## B. Common job contract

Implementation: `backend/analytics_jobs.py`

Statuses:

- `QUEUED`
- `RUNNING`
- `SUCCESS`
- `PARTIAL`
- `FAILED`
- `CANCELLED`
- `EXPIRED`

The durable envelope records:

- identity: `id`, `job_type`, optional `request_id`, `user_id`, optional `portfolio_id`
- compatibility: `input_fingerprint`, `schema_version`, `calculation_version`, `worker_version`
- lifecycle: `status`, `created_at`, `started_at`, `completed_at`
- progress: `progress_stage`, optional `progress_percent`
- result: `result_reference`, canonical `result_payload`
- safe failure: `error_class`, `safe_error_summary`
- retry: `retry_count`, `max_retries`, `next_attempt_at`
- deduplication: `deduplication_key`
- expiry: optional `expires_at`
- lease: `worker_id`, `lease_expires_at`, `heartbeat_at`
- observability: `queue_wait_ms`, `execution_ms`

`analytical_job_attempts` stores each claimed attempt, worker, timestamps, terminal attempt state, safe error class, and execution time.

### Fingerprint and deduplication

The stable key is:

```text
sha256(job_type + input_fingerprint + calculation_version)
```

The input fingerprint includes the normalized analytical request and, where relevant, portfolio identity and stored dataset descriptors/versions.

- compatible `SUCCESS`/`PARTIAL`: reuse the completed result
- compatible `QUEUED`/`RUNNING`: return the same job
- retryable `FAILED` below its retry bound: requeue the same logical job
- changed portfolio, profile, scenario, constraints, dates, dataset identity, or calculation version: create a new job

Postgres and SQLite both enforce one active compatible job per user/deduplication key.

### Leases and restart recovery

- Postgres claims with `FOR UPDATE SKIP LOCKED` and an atomic `QUEUED -> RUNNING` update.
- SQLite uses `BEGIN IMMEDIATE` around selection and claim.
- The worker maintains a heartbeat thread while non-cancellable engine code is running.
- Expired `RUNNING` leases become `QUEUED` with an incremented retry count, or durable `FAILED` after the retry budget is exhausted.
- Expired queued work becomes `EXPIRED`.
- A worker can recover persisted work after a web or worker process restart.

### Retry model

Retryable failures are bounded and include timeout, connection, and transient database operational failures. Invalid inputs, unsupported constraints, insufficient history, and deterministic calculation errors fail without infinite retry.

Analytical infeasibility is not a worker crash:

```text
job status: SUCCESS
AnalysisResult status: UNAVAILABLE or PARTIAL
candidate weights: withheld
```

## C. Job types implemented

| Job type | Status | Existing engine reused | Typed output |
|---|---|---|---|
| `SIMULATION` | Implemented | `simulation_engine.run_simulation` | `SimulationResult` plus canonical metadata |
| `OPTIMIZATION` | Implemented | portfolio analysis, ETF allocator, stock allocator, model-portfolio comparison | `OptimizationResult` |
| `BACKTEST` | Implemented | `model_portfolios.backtest` | `BacktestResult` |
| `COMPANY_RESEARCH_BUILD` | Implemented | stored-evidence `security_research`; portfolio overview/read-model rebuild mode | versioned company/rebuild `AnalysisResult` |
| `THESIS_MONITOR` | Implemented | deterministic thesis monitor plus bounded qualitative classifier | qualitative classifications plus deterministic result |

Simulation output exposes supported path count, horizon, median current outcome, downside percentiles, probability of loss, drawdown statistics, scenario outputs, and robust alternatives. It does not add unsupported measures.

Optimization output explicitly exposes feasibility, current/candidate weights, constraint diagnostics, turnover when supported, cost-model state, tax-awareness state, tax-lot coverage, alternatives, and diagnostics. Infeasible attempted weights are removed.

Backtests now disclose requested symbols, symbols with history, missing symbols, common-history bounds, and portfolio-weight coverage. They retain the existing supported returns, volatility, drawdown, and curve outputs. Turnover and attribution remain `None` when unsupported, and supplied transaction costs are not silently deducted without turnover support.

Qualitative thesis classifications carry provider, model, prompt version, classification version, fingerprint, item ID, classification, confidence, evidence IDs, and generation time. These versions are independent of final Gemini narration.

## D. Synchronous path changes

Removed from direct web/Ask execution:

- live simulation in `POST /api/simulations/runs`
- live simulation in portfolio chat
- portfolio optimizer execution in `POST /api/analyses` and `POST /api/portfolio/analysis`
- ETF allocation optimization
- stock-basket optimization
- model-portfolio alternative optimization
- model-portfolio backtesting
- deep company refresh/rebuild calculations in chat and the refresh endpoint
- broad portfolio research/read-model rebuilds previously launched through FastAPI background tasks
- sequential qualitative thesis classifier calls in thesis monitor endpoints and Ask

The existing math remains callable by the separate worker and by focused unit tests. Fast stored-data capabilities remain synchronous: holdings, current risk/read models, factors, events, data quality, exact company detail reads, and bounded stored-evidence comparisons.

No Phase 5 heavy engine is invoked from the Ask DAG. No FastAPI in-process background task is the authoritative source for heavy work.

## E. Worker

Local commands:

```bash
python scripts/run_analytics_worker.py
python scripts/run_analytics_worker.py --once
python scripts/run_analytics_worker.py --concurrency 2
python scripts/recover_analytics_jobs.py
```

The web server and worker are independent processes. Default concurrency is one; the configurable bounded maximum is four. Every slot independently claims a database lease. Coarse stages are persisted for loading, alignment/input construction, calculation, aggregation/attribution, and persistence.

## F. Database changes

Generated, not applied:

- `supabase/migrations/202608220003_durable_analytical_jobs.sql`

Tables:

- `public.analytical_jobs`
- `public.analytical_job_attempts`

The migration includes active-work deduplication, claim and lease indexes, retry/result/timestamp fields, row-level security, owner policy, and removal of anonymous access.

## G. Ask integration

Ask and heavy API endpoints now:

1. compute the exact input fingerprint;
2. look for a compatible completed job;
3. reuse it only if fingerprint and calculation version match;
4. otherwise persist/reuse a job;
5. return `AnalysisStatus.PENDING` with a `JobReference` where the endpoint contract is canonical;
6. preserve currently available deterministic evidence.

Examples include current concentration evidence while a new simulation runs and deterministic thesis breakers while qualitative classification is pending.

If the generated migration has not yet been applied, Ask preserves the existing safe answer and reports queue unavailability as a limitation instead of turning the request into a system failure.

## H. Read-model integration

| Completed job | Dependency advanced / rebuild behavior | Affected capability models |
|---|---|---|
| Simulation | `scenario_model` | `portfolio_scenario` |
| Optimization | `optimizer_config` | `optimizer_compatibility` |
| Backtest | no current Ask read model depends on backtests | none |
| Company research | `fundamentals` for portfolios containing/watching affected tickers | opportunity, factor state, watchlist comparison, data quality, score attribution |
| Thesis monitor | `thesis_monitor` for relevant portfolios | `thesis_status` |
| Portfolio overview rebuild mode | builds the existing versioned capability projections in the worker | existing Phase 2 registry |

Invalidation remains dependency-driven. It does not mark unrelated read models stale merely because a job completed.

## I. Tests

New infrastructure suite: `backend/tests/test_analytics_jobs.py` (22 tests).

Dedicated acceptance suite: `backend/tests/test_heavy_capability_acceptance.py` (10 required workflows).

Coverage includes:

- persisted `QUEUED` state before work
- duplicate `RUNNING` and completed job reuse
- new job after fingerprint/calculation change
- exclusive two-worker claiming
- expired-lease restart recovery
- terminal failure after exhausted recovery
- queued expiry
- canonical result persistence
- feasible/infeasible/crashed optimizer distinctions
- safe error summaries
- bounded transient retry
- exact completed-result compatibility
- PENDING job references with partial evidence
- all five job types sharing one contract
- durable progress, attempts, queue wait, execution time, and worker ID
- simulation, optimizer, backtest, company research, thesis fallback, worker restart, and normal Ask isolation acceptance paths
- backtest missing-history/common-history coverage

Final backend result:

```text
509 passed, 9 skipped, 2 warnings, 0 failed
```

The warnings are the existing Starlette/httpx deprecation and pandas concat behavior warning.

## J. Performance and isolation

Artifact: `artifacts/phase5-analytics-isolation-benchmark.json`

The isolation microbenchmark holds a durable job in `RUNNING`, executes a separate two-second CPU-bound heavy process, and measures 100 calls through the materialized Ask-tool boundary.

| Workload | Heavy runtime | Queue wait | Ask median | Ask p95 |
|---|---:|---:|---:|---:|
| Simulation + portfolio-risk Ask | 2,000 ms | 1.263 ms | 0.0007 ms | 0.0009 ms |
| Backtest + portfolio read Ask | 2,000 ms | 1.996 ms | 0.0007 ms | 0.0008 ms |

This is an isolation microbenchmark of the already-materialized read boundary, not an end-to-end network latency claim. The important result is that the heavy process does not execute in or block the web/Ask process. The acceptance suite separately exercises the real Ask dispatch boundary while a durable job is `RUNNING`.

## K. Gemini-disabled Ask-15 regression

Artifacts:

- `artifacts/ask-15-phase5-gemini-disabled.md`
- `artifacts/ask-15-phase5-gemini-disabled.json`

| Status | Phase 4 | Phase 5 |
|---|---:|---:|
| SUCCESS | 6 | 6 |
| PARTIAL | 4 | 4 |
| UNAVAILABLE | 5 | 5 |
| FAILED | 0 | 0 |

Additional acceptance results:

- deterministic answers: 15/15
- persistence: 15/15 SUCCESS
- CURRENT read models: 15/15
- fingerprint matches: 15/15
- legacy adapters: 0
- per-question status changes: none
- heavy analytical engines executed inside measured Ask requests: none

The evaluation setup creates one cached scenario fixture before the Ask requests begin. No measured Ask request performs simulation or provider refresh.

## L. Remaining prerequisites

The job architecture does not fabricate missing analytical inputs. These remain explicit:

- lot-level tax data
- supported trading-cost model
- sourced cash/risk-free yield
- saved theses and thesis breakers where absent
- historical portfolio and score-component baselines
- complete earnings, macro-event, and company-catalyst providers
- issuer fundamentals where funds do not have appropriate company fundamentals
- seasonally comparable fundamental history
- broader real peer coverage
- survivorship/security-master history for stronger historical backtests

## M. Phase 6 handoff

Do not begin automatically. The next unified analytical work should cover:

- versioned fast company analysis/read models, replacing remaining bounded stored-data calculation adapters
- canonical macro state
- canonical market state
- stored prediction-market state
- broader historical portfolio/change models

The general arbitrary-question planner, conversational dashboards, UI redesign, and broad macro/company/prediction-market Ask unification remain outside Phase 5.

## N. Verdict

All five heavy analytical families have durable job representations; heavy execution is independent of the web process; queued state precedes work; leases recover after restart; duplicate compatible work is deduplicated; compatibility is fingerprint/version based; terminal results use canonical `AnalysisResult`; targeted read-model dependencies advance on completion; and Phase 4 Ask behavior is preserved.

PHASE 5 COMPLETE
