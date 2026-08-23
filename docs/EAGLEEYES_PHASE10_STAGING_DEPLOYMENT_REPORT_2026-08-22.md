# EagleEyes Phase 10 Staging Deployment Report

Local date: 2026-08-22
Release manifest: `artifacts/phase10-staging-release-manifest.json`
Scope: staging only. No production or staging deployment, migration, backfill, account creation, invitation, or destructive rollback was performed.

## A. Staging deployment report

**Deployment status: NOT STARTED — PRE-DEPLOYMENT GATE FAILED CLOSED.**

The Phase 9 topology remains the source of truth: separate frontend, FastAPI web/API, analytics worker, five-minute lease recovery, fifteen-minute read-model reconciliation, and independently scheduled ingestion. No conflicting architecture was introduced.

The gate found no safely identifiable staging target:

- `STAGING_API_URL`, `STAGING_FRONTEND_URL`, `STAGING_DATABASE_URL`, `STAGING_SUPABASE_URL`, staging CORS, two staging user tokens, staging alert destination, and explicit staging target ID are absent.
- The configured `DATABASE_URL` and `SUPABASE_URL` appear to reference the same unlabelled remote project and neither hostname contains a staging/test/dev marker. That is not proof of production, but it is insufficient authorization to mutate it.
- Vercel is not linked in `.vercel/project.json` and has no usable local credentials. No Render CLI/API credential exists. GitHub CLI credentials are invalid.
- The working tree contains the accumulated Phase 1–10 candidate as a dirty tree rather than a committed release revision. At preflight it contained 83 source entries (34 modified and 49 untracked after adding the preflight), based on commit `8ad6f910b52a24d1099ef05e6a2a35426441e36e` on `feat/chat-first-ask-canvas`.
- `SENTRY_DSN` and a staging alert destination are absent.

The release manifest records frontend/backend `0.1.0`, `analytics-worker-v1`, `capability-registry-v1`, `ask-read-model-builder-v2`, `capability-planner-v1`, the dashboard compiler, calculation versions, migration versions, revision, and source-tree digest. It is intentionally marked `deployable: false`.

Pre-deployment code validation was rerun on the candidate:

| Gate | Result |
|---|---|
| Production frontend build | PASS; existing >500 kB chunk warning remains |
| TypeScript | PASS |
| Frontend contracts | 81/81 PASS |
| Backend | 620 PASS, 9 SKIPPED |
| Git revision | IDENTIFIED |
| Clean/reproducible release | FAIL |
| Explicit staging target | FAIL |
| Two-user staging auth | FAIL |
| Deployment credentials/project link | FAIL |
| Alert destination | FAIL |

`scripts/phase10_staging_preflight.py` now enforces the missing gate without connecting to any service or printing secrets. It requires an exact clean revision, explicit staging target confirmation, HTTPS URLs, distinct user tokens, alerting, and target separation before any mutable step.

## B. Migration/backfill report

A read-only status check was run against the currently configured remote database. It showed every repository migration through `202608180001_portfolio_intelligence_dashboard.sql` applied and these five migrations pending:

1. `202608220001_capability_read_models.sql`
2. `202608220002_idempotent_ask_requests.sql`
3. `202608220003_durable_analytical_jobs.sql`
4. `202608220004_phase6_domain_read_model_indexes.sql`
5. `202608220005_analytical_scope_keys.sql`

No migration validation transaction, application, schema mutation, or backfill was run because the remote target could not be proven to be staging.

Staging continuation order remains:

```bash
python scripts/phase10_staging_preflight.py
python -m backend.migrations check
python -m backend.migrations status
python -m backend.migrations validate
# verify a restorable staging backup, then:
python -m backend.migrations apply
python -m backend.migrations verify
```

After schema verification, backfill test users in bounded scopes:

```bash
python scripts/rebuild_phase6_read_models.py \
  --user-id "$STAGING_USER_A_ID" --portfolio-id "$STAGING_USER_A_PORTFOLIO_ID" \
  --ticker MSFT --ticker AMZN --domains company,macro,market,prediction

python scripts/rebuild_phase6_read_models.py \
  --user-id "$STAGING_USER_B_ID" --portfolio-id "$STAGING_USER_B_PORTFOLIO_ID" \
  --ticker AAPL --ticker SPY --domains company,macro,market,prediction

python scripts/reconcile_read_models.py
```

Required post-backfill report: expected/created totals and `CURRENT`, `PARTIAL`, `STALE`, `FAILED`, and `MISSING` counts by `read_model_type` and user, including company, portfolio, macro, market, prediction, scenario, optimizer compatibility, events, data quality, and historical state. Missing provider data must remain visible rather than being converted to success.

## C. Tenant isolation report

**Actual staging matrix: NOT RUN — two independent staging auth contexts do not exist.**

The mandatory matrix remains a limited-beta blocker. It must run A→B and B→A for portfolio, conversation, dashboard, revision, result reference, analytical job, thesis, and decision-journal IDs. Each cell must be denied twice: through the deployed API owner lookup and through direct authenticated Supabase/RLS access.

Local PostgreSQL and application-boundary isolation passed in Phase 9, but that evidence does not substitute for deployed Supabase auth/RLS. Tokens must never be reused between A and B, and result fingerprints must never be treated as authorization credentials.

## D. Acceptance results

| Suite | Local release candidate | Actual staging HTTP |
|---|---:|---:|
| Ask-15 | Prior configured-remote baseline 15/15 answered/persisted | NOT RUN |
| Phase 6 | 20/20 | NOT RUN |
| Phase 7 | 32/32 | NOT RUN |
| Phase 8 E2E | 19/19 localhost | NOT RUN |
| Phase 9 cross-browser | 8/8 localhost | NOT RUN |
| Heavy capability | 10/10 controlled | NOT RUN |
| Backend | 620 pass, 9 skip | N/A |
| Frontend contracts | 81/81 | N/A |

The staging versions must use real HTTP, authentication, remote persistence, actual read models, absolute request deadlines, and deployed worker processes. Heavy planner nodes must return `PENDING`; no unexplained `FAILED` result is acceptable.

Required deployed UI flow: chat-only initial state; ordinary Ask leaves canvas closed; explicit visualization opens it; close/reopen; conversational widget edit; dashboard save and refresh persistence; mobile Chat/Analysis switching without state loss. Run it in Chromium, Firefox, WebKit, and mobile WebKit against `STAGING_FRONTEND_URL`.

## E. Latency/SLO report

**Authenticated staging latency: NOT MEASURED.**

The provisional SLOs remain unchanged because there is no new staging evidence:

- Fast/read-model Ask: p50 ≤2 s, p95 ≤5 s, p99 ≤8 s.
- Planner Ask: p50 ≤3 s, p95 ≤6 s, p99 ≤9 s.
- Stored dashboard render: p95 ≤3 s.
- Heavy work: asynchronous; queue p95 ≤30 s and oldest queued alert at 120 s.

The staging run must separate auth, DB/read-model, planner, DAG, composition, persistence, optional Gemini, HTTP total, and frontend-observed time for concentration, company comparison, macro, mixed macro/portfolio, prediction/portfolio, and visualization requests. At least 100 fast requests are required before treating p99 as meaningful. SLOs may only change from observed operational evidence, not to make a failing run pass.

## F. Load report

**Staging load: NOT RUN.**

The bounded load profile must use both staging users and mix direct Ask, comparisons, planner Ask, dashboard reads, job submission, and worker execution. Record throughput, p50/p95/p99, connection-pool wait/saturation, CPU/RSS, queue depth/wait, deadline timeout, and `FAILED` rate.

Head-of-line gate: while User A runs a slow planner request and the worker processes backtest/simulation/optimizer jobs, User B's stored direct Ask must continue to meet the fast-Ask SLO. Abort the run on cross-user leakage, repeated pool timeout, an unbounded queue, or a web memory increase that does not stabilize.

Abuse controls must be tested across every deployed web replica. Current process-local IP/path rate limiting is insufficient evidence for a distributed staging deployment. The durable four-active-heavy-jobs-per-user cap must return 429 without affecting the other user. Deep research and dashboard refresh also require measured limits or an explicit internal-only constraint.

## G. Failure drill report

**Deployed failure drills: NOT RUN.**

Required staging drills:

- Prices, fundamentals, macro, prediction markets, and Gemini disabled/faulted one at a time. Stored compatible results must remain available under declared freshness rules, unrelated capabilities must stay current, and no value may be fabricated.
- Start a real heavy job, stop the worker after claim, wait beyond its lease, run recovery/restart, and verify reclaim plus a terminal result with no permanent `RUNNING` row.
- Restart the web while conversations, a dashboard, and a job exist. Verify auth, artifacts, references, and idempotent message retry survive without duplication.
- Introduce one controlled upstream-version mismatch. Only its dependent model becomes `STALE`; reconciliation rebuilds it to `CURRENT`; Ask does not rebuild synchronously.
- Verify completed backtest/simulation/optimizer results persist canonically and can be consumed by Ask/dashboard.

No staging restart, rollback, provider fault, or reconciliation mutation was attempted without a confirmed target.

## H. Alert report

**Alert delivery: NOT CONFIGURED / NOT PROVEN.**

Before internal users, staging must deliver safe synthetic alerts for failed job, stale worker heartbeat, reconciliation failure/backlog, provider health issue, elevated HTTP failure, and queue backlog. For each, record trigger timestamp, destination receipt, delivery latency, acknowledgement, recovery action, and clear timestamp.

Code-level Sentry support and durable operational events are present, but code existence is not delivery evidence. A missing or undelivered security, worker, DB, or reconciliation alert blocks limited beta.

## I. Soak report

**Elapsed staging soak: 0 hours. Incomplete.**

Exact minimum 24-hour procedure once staging is available:

1. Freeze a clean revision and regenerate the release manifest; run preflight and archive its passing output.
2. Confirm web, worker, recovery, reconciliation, provider health, alert destination, two users, migrations, and backfill all pass before `T0`.
3. Record baseline DB size, pool connections, read-model counts/states, queue/jobs/attempts, operational-event count, service CPU/RSS, provider timestamps, and auth/API latency.
4. Every 5 minutes collect liveness/readiness, worker heartbeat age, recovery/reconciliation heartbeat age, queue counts/oldest age, RUNNING beyond lease, DB connections, CPU/RSS, and error totals.
5. Every 15 minutes issue one authenticated fast Ask per user with stable request IDs and verify persistence/idempotency.
6. Every hour run one planner request, one dashboard read/reopen, one provider-health read, and a two-user hostile-ID sample. Allow scheduled prediction ingestion and reconciliation to run naturally.
7. Every 4 hours rotate one heavy job type across simulation, optimization, backtest, company research, and thesis monitor; capture queue wait/runtime/result and an unrelated fast-Ask latency sample.
8. During the first six hours run the worker restart, web restart, reconciliation mismatch, Gemini outage, prediction outage, and one alert-delivery drill. Restore each condition and verify recovery.
9. Allow at least one normal daily ingestion cycle. Do not replace elapsed time with unit tests or accelerated loops.
10. At `T+24h`, repeat the baseline inventory and compare growth/deltas. Prefer continuation to 48–72 hours before any external beta.

Abort/rollback thresholds:

- Any cross-user data visibility or authorization ambiguity.
- Any permanent RUNNING zombie, unrecoverable job, duplicate user message/result, or canonical-value mismatch.
- Readiness failure >5 minutes, missing critical heartbeat for two expected intervals, queue age >120 seconds without explanation, or reconciliation backlog increasing for three intervals.
- Fast Ask p95 >5 seconds for three consecutive 15-minute windows, p99 >8 seconds with adequate samples, unexpected `FAILED` >1%, repeated pool exhaustion, or non-stabilizing RSS/DB-connection growth.
- Required alert not delivered within the configured notification SLO.

Post-soak consistency queries must prove: no expired RUNNING lease, no unexplained failed builders, acceptable stale backlog, current models within freshness policy, no duplicate dedupe keys/messages, bounded DB growth, and continued A↔B isolation.

## J. UX/accessibility/cross-browser report

**Actual staging UI/accessibility/cross-browser: NOT RUN.**

Local evidence remains strong but cannot be promoted to deployed evidence. Staging must cover keyboard order/focus, History drawer, canvas close/reopen, dropdowns, dashboard controls, textual status labels, contrast, reduced motion, chart/table alternatives, and mobile Chat/Analysis tabs.

Required widths are 375, 390, 430, and a representative tablet. Each must retain a usable composer, compact toolbar, readable dashboard, stable canvas state, and zero horizontal overflow. Accessibility findings are classified critical/high/medium/low; any critical security, keyboard-blocking, or status-disclosure issue blocks beta.

The real-user walkthrough must include stock research, company comparison, portfolio risk, macro, prediction markets, scenario, dashboard build/save, backtest start, and return-later result recovery. Fix only beta blockers, not product/navigation design.

## K. Beta limitations

The following remain explicit product limitations and must be disclosed rather than filled by Gemini:

- incomplete tax lots;
- no validated trading-cost model;
- no sourced cash/risk-free hurdle;
- incomplete saved theses and historical baselines;
- incomplete event, guidance, and estimate coverage;
- funds without complete issuer fundamentals;
- incomplete peer coverage;
- incomplete prediction-market mapping, calibration, liquidity, and availability;
- incomplete survivorship data for stronger backtests.

These may coexist with a controlled beta only if coverage/freshness/limitations are displayed and unsupported recommendations remain blocked.

## L. Rollback plan

The Phase 9 additive rollback plan remains valid but is **not rehearsed in staging**.

- Web: remove traffic from the new revision, restore the previous compatible image, preserve additive schema, and smoke auth/portfolio/deterministic Ask.
- Worker: disable `HEAVY_ANALYTICS_ENABLED`, stop gracefully, retain queued rows, restore the prior worker, and recover only after version compatibility is confirmed.
- Planner: disable Gemini planner first, then `ASK_ROUTER_V2` if required; never weaken the registry/verifier.
- Gemini narration: disable enrichment; deterministic Ask stays online.
- Prediction enrichment: stop its scheduler/optional path and retain the last validated snapshot.
- Dashboard optional layer: staging must prove a concrete disable/rollback control before beta; there is not yet a dedicated conversational-dashboard flag.
- Migration: leave successful additive migrations in place on code rollback. A failed transaction rolls back. For committed data corruption, stop services/backfill and restore the verified pre-release staging backup or roll forward with a corrective migration—never destructively improvise a down migration.

Required rehearsal: new→previous web, new→previous worker, planner off, Gemini off, prediction off, heavy jobs off, then full core Ask smoke. The rollback revision must be recorded in the regenerated manifest.

## M. Limited-beta operating plan

Initial audience after all staging gates: internal users only, beginning with two accounts and no external invitations. Expand to at most 5–10 allowlisted users only after a 24-hour passing soak; prefer 48–72 hours.

Required feature controls:

- Gemini narration: `ASK_GEMINI_ENRICHMENT=0`.
- Gemini planner: `ASK_CAPABILITY_PLANNER_GEMINI=0`.
- General compositional router fallback: `ASK_ROUTER_V2=0` when required.
- Heavy job creation: `HEAVY_ANALYTICS_ENABLED=0`.
- Prediction enrichment: operational scheduler/provider disable exists, but a dedicated application flag must be verified or added before beta if core routes cannot cleanly omit it.
- Conversational dashboards: no dedicated fail-closed flag is currently proven; use deployment rollback until a narrow flag is validated.

First-user dashboards/alerts must cover Ask latency/status/deadlines/persistence; planner invocation/invalid/repair/direct-route; stale models/reconciliation/provider health; job queue/running/failure/wait/runtime/lease; Gemini failure/latency/cost; dashboard creation/widget refresh; auth/DB pool; and authorization-boundary failures.

Escalation criteria: immediate traffic freeze for data leakage, canonical-value mismatch, authorization bypass, irrecoverable job, or migration inconsistency. Disable the smallest optional layer for provider/Gemini/planner/dashboard faults. Roll back web/worker for sustained SLO, pool, memory, or unexpected-failure breaches.

## N. Final verdict

# READY FOR STAGING CONTINUATION

The code candidate still qualifies for staging, and its pre-deployment build/test gates pass. It does not qualify for internal users or limited beta because no isolated staging target, reproducible clean revision, two-user auth setup, deployed service topology, alert destination, staging migration/backfill, authenticated acceptance, load/failure/restart/rollback evidence, or real soak exists.

To resume, provide/configure an isolated staging frontend/API/database/Supabase project, deployment access, two distinct test-user tokens, exact CORS and alert destination, and a clean expected revision. Then run `scripts/phase10_staging_preflight.py`; only a zero exit status authorizes the migration/deployment sequence.

PHASE 10 COMPLETE
