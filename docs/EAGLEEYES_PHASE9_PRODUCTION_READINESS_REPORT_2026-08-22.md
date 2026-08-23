# EagleEyes Phase 9 Production-Readiness Report

Date: 2026-08-22
Scope: production hardening and staging validation only; no deployment, production migration, production backfill, commit, or push was performed.

## A. Executive verdict

**READY FOR STAGING**

The release candidate is suitable for a controlled staging deployment. It is not ready for a limited beta because the pending schema and new web/worker/cron topology have not run together in staging; authenticated end-to-end latency, two-account live authorization, provider failure behavior, worker/reconciliation heartbeats, and alert delivery have not been observed there.

The strongest production blocker found during Phase 9 was fixed: Phase 6 company and global read models used semantic scopes such as `company:MSFT` and `global:macro_state`, while the Phase 2 PostgreSQL schema required `portfolio_id uuid NOT NULL`. Migration `202608220005_analytical_scope_keys.sql` adds a semantic `scope_key`, preserves a nullable real portfolio foreign key, and supplies the matching lookup/reconciliation indexes.

Release posture: deploy to an isolated staging environment, complete every gate in Section L, then conduct an internal-only rollout before any limited beta. Trading remains disabled.

## B. Blocking issues

These block **limited beta**, but not a staging deployment:

1. The configured remote database still shows migrations `202608220001` through `202608220005` as pending. They were tested only in the disposable PostgreSQL validation database; they must first be applied and verified in staging.
2. No staging API URL or first/second test-user access tokens were available (`LIVE_API_URL`, `LIVE_ACCESS_TOKEN`, `LIVE_SECOND_ACCESS_TOKEN`, `PRODUCTION_API_URL`, and smoke tokens were absent). The mandatory authenticated staging suite, direct live RLS test, and real auth percentile measurement therefore could not run.
3. The Render worker and two cron services exist only as a reviewed Blueprint. They have not yet produced sustained staging heartbeats, recovered a real staging lease, or demonstrated reconciliation with real staging read models.
4. Real authenticated Ask latency has not been measured after migration and pooling in staging. The latest configured-remote Ask-15 baseline (15 samples, Gemini disabled) was p50 4.030 s, p95 5.163 s, and max 5.666 s; it narrowly misses the proposed 5 s p95 target and does not include a controlled real-auth staging run.
5. Alert delivery is not proven. Sentry support is present and the Blueprint requires a secret DSN, but the current environment has no configured `SENTRY_DSN`; no external alerts for queue, reconciliation, provider, DB, or auth failures have been exercised.
6. The current API request limiter is process-local and IP/path scoped. The durable per-user heavy-job cap is safe, but a shared distributed/edge per-user Ask and dashboard limit must be configured or explicitly accepted before beta.

## C. Non-blocking issues

- The main client chunk is 561,325 bytes minified / 141,867 bytes gzip and still triggers the 500 kB minified warning. It is acceptable for staging; route/component splitting should target the monolithic dashboard, charts, research tools, and rarely used admin/debug surfaces after beta safety gates.
- The desktop Ask divider remains fixed. Resizing is post-beta polish; the current layout passed desktop and mobile overflow tests.
- Some generic fallback tables and dense legacy widgets remain. Phase 9 reduced repeated widget prose to a compact key takeaway and compacted the mobile header.
- The rate limiter resets on process restart and is not shared across web replicas.
- The operational endpoint's process-local percentile window resets on restart. Durable analytical events exist, but a hosted metrics backend/dashboard is still needed.
- Provider status currently reports events, Kalshi, Polymarket, Supabase, and Gemini as `awaiting_data`, not failed. Market snapshots are intentionally unconfigured; stored daily prices remain the fallback.
- SEC and some catalog ingestion paths use bounded timeouts but do not share the six-attempt retry helper. Their scheduler retry/alert behavior should be monitored rather than moved into Ask.
- Automated contrast auditing with a dedicated axe rule set is not installed. Keyboard, labels, semantic status, reduced motion, and responsive overflow were tested.
- Known product/data limitations remain: incomplete tax lots; no validated trading-cost model or sourced cash/risk-free hurdle; incomplete saved-thesis and historical baselines; incomplete event/guidance/estimate, fund fundamental, peer, prediction-market mapping/calibration/liquidity, and survivorship coverage. Gemini cannot fill these gaps.

## D. Migration plan

Configured remote status on 2026-08-22: all migrations through `202608180001` applied; the five rows below pending. No Phase 8 schema migration exists.

| Migration | Purpose | Dependencies | Compatibility | Expected lock impact | Recovery | Backfill |
|---|---|---|---|---|---|---|
| `202608220001_capability_read_models.sql` | Adds dataset versions and append-only capability read models, RLS, owner grants, initial lookup index | Existing `auth.users`, `portfolios` | Additive to old web | Table creation is low impact | Leave additive tables in place on code rollback | Required after `005` |
| `202608220002_idempotent_ask_requests.sql` | Durable one-logical-turn Ask lifecycle and staged result | Chat conversations/messages | Additive; old web ignores it | Low; new table/index | Leave table; new web can replay/repair | None; begins empty |
| `202608220003_durable_analytical_jobs.sql` | Durable jobs, attempts, leases, retries, dedupe and RLS | Users and optional portfolios | Additive; old web ignores it | Low on empty new tables | Stop worker and roll back code; preserve rows | None; begins empty |
| `202608220004_phase6_domain_read_model_indexes.sql` | Domain history/version lookup indexes | `001` | Additive | Non-concurrent index build; low only while new tables are empty | Indexes may remain | None |
| `202608220005_analytical_scope_keys.sql` | Corrects portfolio-only UUID scope to semantic `scope_key`; nullable real portfolio FK; new PK/indexes | `001`, before any domain backfill | New code reads/writes `scope_key`; old code remains safe for real portfolio rows | `UPDATE`, `NOT NULL`, PK replacement and index creation can lock; apply immediately after `001` while tables are empty | Restore from backup only for a failed transaction; after success leave additive columns/constraints and roll code forward | Converts any existing portfolio row to `portfolio:<uuid>` |

Validation performed:

- Applied the complete repository migration chain through `005` to PostgreSQL 17 with pgvector.
- Reapplied `001`–`005`; all idempotent guards behaved correctly.
- Reapplied `005` after representative data; portfolio, company, and global scopes remained valid.
- Verified RLS enabled and anonymous privileges revoked.
- Verified valid `company:MSFT`, `global:macro_state`, and `portfolio:<uuid>` rows.
- `EXPLAIN` under the authenticated RLS role used `capability_read_models_scope_lookup_idx` for the primary scope lookup.
- Static migration tests and PostgreSQL serialization tests passed.

Staging commands, in order:

```bash
python -m backend.migrations check
python -m backend.migrations status
python -m backend.migrations validate   # transaction is rolled back
# take and verify a restorable database backup, then during the release window:
python -m backend.migrations apply
python -m backend.migrations verify
```

Do not deploy the new web or worker until `verify` passes. Do not run `005` after a large backfill without a measured maintenance window.

## E. Backfill/reconciliation plan

Tables needing population: `capability_read_models` and `analytical_dataset_versions`. Ask request/job tables begin empty. Existing analysis history, chat artifacts, dashboard revisions, decisions, and theses are not rewritten.

Initial backfill, per test user/portfolio in bounded batches:

```bash
python scripts/rebuild_phase6_read_models.py \
  --user-id <user-uuid> \
  --portfolio-id <portfolio-uuid> \
  --ticker MSFT --ticker AMZN \
  --domains company,macro,market,prediction
```

The release operator should generate the user/portfolio/ticker input list from an owner-authorized staging inventory, process small batches, retain command output, and retry only failed scopes. It must not pass semantic company/global keys as portfolio IDs.

Incremental reconciliation and retry:

```bash
python scripts/reconcile_read_models.py
python scripts/reconcile_read_models.py  # safe targeted retry after fixing the dependency
```

Verification:

```sql
select read_model_state, read_model_type, count(*)
from public.capability_read_models
group by 1,2 order by 2,1;

select scope_key, dataset_type, updated_at
from public.analytical_dataset_versions
order by updated_at desc limit 100;

select count(*) filter (where scope_key is null) as invalid_scope_rows,
       count(*) filter (where scope_key like 'portfolio:%' and portfolio_id is null) as invalid_portfolio_rows
from public.capability_read_models;
```

Representative company/global/portfolio materialization, load, history, and reconciliation were exercised against PostgreSQL. The Phase 6 acceptance backfill produced 20/20 grounded answers.

## F. Worker/scheduler plan

Recommended independent worker:

```bash
python scripts/run_analytics_worker.py --concurrency 2 --poll-seconds 1
```

The Render Blueprint declares a paid background worker rather than assigning work to the web process, with two worker slots, one BLAS thread, a 150-second shutdown delay, a maximum of four active jobs per user, and a fail-closed `HEAVY_ANALYTICS_ENABLED` flag. The layout follows Render's official [background worker](https://render.com/docs/background-workers), [cron job](https://render.com/docs/cronjobs), and [Blueprint](https://render.com/docs/blueprint-spec) contracts.

| Task | Cadence | Owner/process | Timeout/bounds | Retry/recovery | Alert |
|---|---|---|---|---|---|
| Prices, macro, news, regimes | Weekdays 02:35 UTC | GitHub Actions ingestion | Provider requests 30–60 s; workflow bounded | Transient provider helper up to 6 attempts; workflow rerun | Failed workflow/provider error rate/stale age |
| Tiingo supplemental prices | Same daily workflow, if configured | GitHub Actions | 30 s/request | Bounded provider retry | Failure or adjusted-price lag |
| Prediction markets | Hourly at :17 | GitHub Actions | 15 s/request | Next hourly run/manual rerun | Snapshot age or repeated failure |
| SEC fundamentals | Sunday 03:45 UTC | GitHub Actions | 30 s/request | Next run/manual rerun | Fundamental age and coverage drop |
| ALFRED/history/regimes | Monthly day 1 at 04:15 UTC | GitHub Actions | 60 s/request | Bounded retry/manual rerun | Missing vintage/failed workflow |
| Heavy analytics | Continuous | Render background worker | Job expiry, lease, per-type runtime | Max retries stored per job; terminal FAILED/EXPIRED | Queue age, stuck RUNNING, worker heartbeat |
| Expired lease recovery | Every 5 minutes | Render cron | One bounded scan | Requeues below max retry; otherwise terminal FAILED | Missing heartbeat/recovered spike |
| Read-model reconciliation | Every 15 minutes | Render cron | One pass over real portfolio scopes | Next run and explicit rerun | Missing heartbeat, failures, stale backlog |
| Historical snapshots | Produced by scheduled ingestion/portfolio rebuilds | GitHub Actions + builders | Builder-specific | Reconciliation/backfill | Snapshot age/coverage |

Ask correctness no longer depends on opening Today. Heavy calculations are durable jobs; Ask consumes compatible stored read models.

Worker validation: independent startup against PostgreSQL succeeded, claimed a queued job, emitted `analytics.worker.heartbeat`, and moved the deliberately invalid representative payload to terminal `FAILED`. Controlled handlers passed success/partial/unavailable, lease, bounded retry, restart recovery, dedupe, and concurrency tests.

## G. Security review

- Authentication validates the bearer token against Supabase with a 4-second production timeout. The local curl fallback passes credentials on stdin; Phase 9 disables that second retry path in `APP_ENV=production` so auth cannot consume another four seconds.
- Exact production CORS origins are required; wildcard and origin strings without HTTP(S) are rejected.
- Request bodies default to 1 MiB. Security headers, no-store behavior, request IDs, and safe 503 dependency errors are applied centrally.
- All private Phase 2–9 tables have RLS, owner policies, and anonymous grants revoked. PostgreSQL tests used actual `SET ROLE authenticated` and `auth.uid()` claims.
- User B saw zero of User A's portfolios/read models, jobs, conversations, dashboard views/jobs/artifacts, theses, and decisions. Hostile application lookups for another user's conversation/view/dashboard/job returned `KeyError`/404-style failures.
- Stable `result_<fingerprint>` and `composed_<fingerprint>` references are metadata, not bearer credentials. There is no result-ID-only read endpoint; artifacts and jobs are loaded through the owner scope.
- Dashboard ID, revision, widget result-reference, job-reference, and conversation-artifact substitutions remain subject to the parent user ownership checks.
- Planner execution remains registry-only. Validation rejects unknown capabilities, arbitrary Python/code/backend functions, SQL, URLs/API calls, unresolved entities, output-schema substitution, excessive depth/nodes, and multiple heavy jobs. No trading capability exists.
- Prompt-injection regression covers: registry override/Python, direct SQL, external URL, nonexistent capability, fabricated entities/schema, missing-value fabrication boundaries, and infeasible optimizer weights. Plans fail closed to a known deterministic route or `UNSUPPORTED`; they never become unrestricted model/tool execution.
- Provider exceptions strip credential-bearing request URLs. Structured logs contain request IDs, paths, safe failure classes, fingerprints, timings, and statuses—not tokens or full portfolio payloads. Sentry is configured with `send_default_pii=False` when enabled.
- Rate limits: 60 requests/minute per IP/path in the Blueprint, 4 active heavy jobs per user enforced transactionally with a PostgreSQL advisory lock, planner max one heavy node, and worker concurrency 2. Distributed per-user web limits remain a beta gate.

## H. Failure testing

The controlled failure/regression group passed 107/107 tests.

| Drill | Result |
|---|---|
| Prices unavailable/stale | Stored compatible snapshot retained; stale/coverage disclosure; no value invention |
| Fundamentals missing/stale | Company result becomes `UNAVAILABLE` or `PARTIAL` according to required fields |
| Macro missing | Macro quality becomes partial without invalidating unrelated company/market models |
| Prediction markets missing/stale | Explicit stale/calibration-unavailable state; deterministic macro prior only where declared |
| Gemini timeout/outage | Deterministic answer remains; enrichment is optional and deadline-bounded |
| Slow DB/transient connection/statement timeout | Node timeout is capped by absolute deadline; middleware returns safe terminal 503; no unbounded retry |
| Worker outage | Queued rows remain durable; normal Ask reads remain available; expired lease is reclaimed |
| Worker retry exhausted | Job becomes terminal `FAILED`; queued expiry becomes terminal `EXPIRED` |
| Web restart/late persistence failure | Request staging and idempotent replay recover one logical turn without duplicate answer |
| Stale dependency matrix | Current prices/macro remain current while stale fundamentals/prediction only stale/partial their dependent models |
| Targeted invalidation | Staling one company does not globally stale other tickers/domains |

User-facing states use `PARTIAL`, `UNAVAILABLE`, `PENDING`, stale labels, coverage counts, and safe prerequisite/provider explanations. Raw internal exceptions are not used as financial answers.

## I. Load/latency

No benchmark below is presented as a production SLO claim unless explicitly described as configured-remote.

Configured remote database, read-only `SELECT 1`:

- Before pooling, 30 fresh-connect samples: p50 789.57 ms, p95 903.56 ms, p99 948.91 ms.
- After bounded pooling, 30 sequential checkout/query samples: p50 306.80 ms, p95 376.28 ms, p99 394.49 ms, max 454.76 ms.
- After pooling, 100 queries at concurrency 20 with pool max 8: wall 5.679 s, p50 909.99 ms, p95 1.857 s, p99 2.071 s. Pool queuing was bounded; there was no connection explosion.

Configured-remote Ask-15 baseline (15 answers, Gemini disabled, before the final staging migration/pool deployment): p50 4.030 s, p95 5.163 s, p99 not statistically meaningful, max 5.666 s. All 15 answered and persisted successfully. Real auth and the deployed worker topology still require staging measurement.

Local boundary measurements:

- Synthetic DAG: one/two/three independent nodes p50 about 35.1 ms; 4 concurrent requests p95 35.83 ms; a 250 ms slow request did not raise the 30 ms request above 35.66 ms p95.
- SQLite materialized models: company 0.70 ms median, two-company comparison 2.17 ms, macro 0.66 ms, market 0.65 ms, prediction 0.64 ms, mixed three-capability DAG 5.11 ms. These exclude network/auth.
- Separate CPU-heavy process with a durable RUNNING job: 100 Ask boundary reads remained stable in both simulation and backtest cases. This validates process isolation, not production throughput.

Initial SLOs and alerts:

| Surface | SLO |
|---|---|
| Direct/read-model Ask | p50 ≤2 s, p95 ≤5 s, p99 ≤8 s |
| Planner Ask | p50 ≤3 s, p95 ≤6 s, p99 ≤9 s |
| Dashboard initial render from stored results | p95 ≤3 s |
| Dashboard build | p95 ≤60 s with visible progress; partial slots allowed |
| Durable queue wait | p95 ≤30 s, alert oldest queued >120 s |
| Heavy runtime | Per job type; never part of synchronous Ask SLO; alert >configured expiry |
| Gemini enrichment | ≤2.5 s budget in Ask; optional, deterministic fallback |

Do not advance beyond internal rollout until a staging run with at least 100 direct, 50 planner, 30 dashboard, and a bounded mixed worker workload meets these targets without pool timeout, head-of-line blocking, or material RSS growth.

## J. Observability

Available request telemetry includes request ID, safe conversation identity, capability/intent and planner/direct route, dependencies, read-model ID/version/state, coverage/freshness/effective-through, fingerprint, per-node timings/timeouts/deadline remaining, result/verification status, Gemini state/latency, persistence status, and dashboard artifact references.

Available job telemetry includes job/type/status, queue wait, worker/lease/heartbeat, retry/attempt, execution time, result reference, safe error class, worker heartbeat, queue counts, oldest queue age, and latest running heartbeat. `/api/operations/metrics` includes job operational health. `/api/health` is liveness; `/api/health/readiness` checks core DB plus read-model/job tables and returns 503 without exposing errors. Optional provider failure does not fail core readiness.

Alerts to configure before beta:

- Ask `FAILED` or `UNEXPECTED` rate; dependency/persistence failures; deadline exhaustion; p95/p99 breaches.
- Auth 401 anomaly, auth 503, auth latency, DB connect/pool/statement latency.
- Missing worker/recovery/reconciliation heartbeat; queue age >120 s; stuck RUNNING beyond lease; retry or terminal-failure spike.
- Reconciliation failures/backlog; stale required model percentage and oldest age.
- Provider failure rate/last-success age/coverage regression/rate-limit exhaustion. Legitimate analytical `UNAVAILABLE` prerequisites are not infrastructure alerts.
- Gemini errors only if enrichment is expected/enabled.
- Sentry configuration failure and error-event delivery test failure.

Staging must connect Sentry or an equivalent log/metric sink and prove at least one synthetic alert from trigger to notification.

## K. UX/accessibility

- Phase 8 E2E: 19/19 passed.
- Phase 9 cross-browser readiness: 8/8 passed across Chromium, Firefox, desktop WebKit, and iPhone 13 WebKit.
- Verified keyboard focus and Enter activation for composer, canvas close, and reopen; accessible close label; visible textual verification status; no horizontal overflow; mobile compact header; desktop and mobile contextual canvas behavior.
- Interactive browser inspection confirmed the production landing/auth surface renders cleanly at desktop and 390×844, with semantic Email/Password labels and zero horizontal overflow.
- Reduced-motion CSS already exists. Statuses use text in addition to color. Chart widgets preserve source/details and data/table alternatives where implemented.
- Dense canvas widgets now prioritize title, visual, two-line key takeaway, and details. The mobile canvas header is single-line and its close control becomes `← Chat`.
- Remaining accessibility work: automated WCAG contrast scan, screen-reader traversal on the authenticated staging app, and manual chart/table equivalence audit. These are required in staging acceptance but are not code blockers for staging.
- Bundle stayed effectively unchanged at 561,325 bytes minified / 141,867 gzip. A broad lazy-loading rewrite was deliberately deferred as too risky for hardening.

## L. Staging acceptance results

Completed locally/production-like:

| Suite | Result |
|---|---|
| Full backend | 620 passed, 9 skipped |
| Frontend contracts | 81 passed |
| TypeScript | Passed |
| Production frontend build | Passed; one quantified chunk warning |
| Phase 8 E2E | 19/19 passed |
| Phase 9 cross-browser | 8/8 passed |
| Phase 6 acceptance | 20/20 passed |
| Phase 7 planner | 32/32 passed |
| Heavy capability acceptance | 10/10 passed |
| Ask-15 latest configured-remote baseline | 15/15 answered and persisted; not rerun against a staging deployment |
| PostgreSQL migration/idempotency/RLS/worker | Passed in disposable PostgreSQL 17 |

Real stored provider retrieval was bounded and read-only. Provider health showed 3 healthy, 5 awaiting data, 0 degraded, 1 unconfigured. Stored prices contained 1,067,028 bars across reported provider coverage; latest Polygon date 2026-08-20 and Tiingo 2026-08-18. FRED last success was 2026-08-21 with recent error rate 0.333; prices 0.133; SEC 0.25. Events and prediction providers had no stored success yet. This is pipeline-state evidence, not a market-truth audit.

Pipeline-integrity spot checks matched source-to-result values: MSFT stored price 360 and score 82; comparison net margin 0.2 and valuation score 55; macro regime `mixed`; seeded prediction probability 0.62 and +8 percentage points; scenario and dashboard widget states preserved canonical status/lineage. The MSFT result correctly disclosed unavailable revenue-growth evidence instead of substituting the research-row estimate.

Not run because staging credentials/runtime were absent: live login, actual Supabase auth p50/p95/p99, deployed readiness, all mandatory Ask prompts against migrated staging, save/reopen staging dashboard, real backtest queue/completion/reopen, two-account artifact attack, live provider refresh, worker/recovery/reconciliation heartbeat age, alert delivery, and production-like mixed load. These are blockers listed in B.

Mandatory staging smoke sequence:

1. Verify readiness; log in as User A and load the expected portfolio.
2. Ask concentration, MSFT/AMZN comparison, macro, prediction-market, and mixed macro/exposure questions.
3. Request “Visualize my largest portfolio risks”; close/reopen the canvas; save and reopen the dashboard.
4. Start “Backtest my portfolio against SPY”; verify immediate `PENDING`, separate worker claim, heartbeat, terminal completion, and result reopen.
5. Repeat artifact/job/dashboard/conversation/result-reference reads with User B and direct Supabase REST; every User A private ID must be invisible.
6. Run Ask-15, Phase 6, Phase 7, Phase 8 E2E, heavy capability, and the Phase 9 cross-browser config against the staging URL.
7. Run bounded direct/planner/dashboard/multi-user load while all five heavy job types are queued with worker concurrency 2; record latency, queue wait/runtime, CPU/RSS, pool waits, and failures.
8. Disable or fault each provider in turn, then restore it; verify stale/partial/fallback state and alert delivery.

## M. Deployment sequence

1. Create isolated staging services and two test accounts; configure exact frontend/backend URLs and CORS.
2. Configure database, Supabase publishable auth key, provider keys, `APP_ENV=production`, Sentry/telemetry, DB pool/timeouts, Ask budgets, concurrency, and feature flags. Keep Gemini planner/narration off initially.
3. Take and verify a restorable staging database backup; record row counts and migration status.
4. Run migration `validate`; then apply exactly `001`, `002`, `003`, `004`, `005` in one controlled release window. Run `verify` and the RLS/query-plan checks.
5. Deploy the compatible web service with readiness at `/api/health/readiness`, but keep beta traffic disabled.
6. Deploy the independent analytics worker. Confirm heartbeat and one controlled success plus one controlled failed job.
7. Enable 5-minute recovery and 15-minute reconciliation crons. Confirm two consecutive successful heartbeats.
8. Run bounded initial backfill by user/portfolio/ticker. Verify counts, scopes, states, history, and zero invalid scope rows.
9. Run the mandatory smoke, full staging acceptance, failure drills, two-user isolation, latency/load, data spot checks, and alert delivery in Section L.
10. Hold an internal-only soak for at least one daily ingestion cycle and 24 hours of hourly prediction/reconciliation/recovery scheduling.
11. If all gates pass, enable a small allowlisted internal cohort. Gemini remains optional; heavy jobs can be disabled instantly.
12. Only after the monitored internal soak meets SLO/error/freshness gates should a limited beta be reconsidered.

## N. Rollback sequence

Web deployment:

1. Disable traffic to the new web revision and restore the last known-good image.
2. Keep additive tables/migrations in place; old web ignores them. Do not drop columns/tables.
3. Verify liveness, auth, portfolio load, and deterministic Ask.

Worker deployment:

1. Set `HEAVY_ANALYTICS_ENABLED=0` on web to stop new submissions.
2. Gracefully stop the new worker; leases expire safely.
3. Deploy the prior worker or leave jobs queued; run recovery only after compatibility is confirmed.
4. Never delete queued/running rows to recover service.

Migration issue:

1. If the migration transaction fails, it rolls back; inspect the exact statement and restore only if the DB itself is unhealthy.
2. If it commits but new code fails, retain additive schema and roll back code.
3. For a bad `005` data conversion, stop web/worker/backfill and restore the pre-release backup or roll forward with a new corrective migration. Do not destructively reverse PK/columns in place.

Bad read-model builder:

1. Stop reconciliation/backfill and disable the affected optional route/worker submissions.
2. Preserve prior append-only compatible model versions.
3. Deploy the last builder version, mark only affected dependency scopes stale, and rebuild those scopes.

Provider issue:

1. Disable the provider-specific scheduler/optional feature; retain the last validated snapshot.
2. Confirm stale/partial disclosure and deterministic Ask.
3. Restore credentials/provider and run one bounded refresh before resuming cadence.

Planner issue:

1. Set `ASK_CAPABILITY_PLANNER_GEMINI=0`; if needed set `ASK_ROUTER_V2=0` to use known deterministic routing.
2. Leave verification and registry constraints enabled.
3. Re-run the 32-question planner suite and injection corpus before reenabling.

## O. Limited-beta monitoring

Recommended first release remains **internal only**, followed by an allowlisted limited beta after all Section B blockers close.

Monitor by 5-minute, hourly, and daily windows:

- Ask volume, direct/planner split, p50/p95/p99, deadline exhaustion, result status, verification refusal, persistence/replay, and failure class.
- Auth latency/status; DB pool wait, connect/statement timeouts, transaction failures, and query latency.
- Queue depth/oldest age, worker heartbeat, RUNNING beyond lease, retry count, terminal failure, queue wait and runtime by job type, worker CPU/RSS.
- Read-model current/stale/partial/missing counts, reconciliation failures/heartbeat, input-version mismatch, rebuild latency and coverage.
- Provider last success, effective-through age, coverage, recent error rate and quota/rate-limit metadata. Treat legitimate missing prerequisites separately from outages.
- Dashboard build/save/reopen success, artifact owner-scope failures, result-reference mismatch, partial widget rate, and frontend error rate.
- RLS/authorization denials and suspicious cross-user ID attempts, without logging raw tokens or portfolio contents.
- Sentry/log delivery health and synthetic alert acknowledgement.
- Product limitations surfaced to users: tax-lot, trading-cost, cash hurdle, baseline, event/estimate/fund/peer, prediction calibration/liquidity, and survivorship coverage.

Promotion gate from internal to limited beta: seven days without a severity-1 security/data-integrity issue; all required scheduler heartbeats healthy; no unresolved stuck jobs; read-model required-data freshness within policy; direct/planner SLOs met; provider outages degrade safely; alert delivery proven; and the two-user live isolation suite passes after every schema/auth change.

Retention policy for the first release:

- Operational telemetry: 30 days hot, then aggregate; remove request-level rows by 90 days unless tied to an incident.
- Completed analytical jobs: 90 days hot; retain canonical result lineage/history separately. Failed job metadata 30 days after incident resolution.
- Job attempts: 30 days after parent terminal state, unless incident/legal retention requires longer.
- Obsolete read models: keep current plus prior compatible lineage for 90 days; prune only after reconciliation verifies a replacement.
- Planner/evidence process caches: TTL-only; no long-term retention required.
- Dashboard revisions: preserve user-visible decision history; only prune abandoned unsaved drafts after 30 days with explicit policy.
- Stale drafts: 30 days; expired widget cache immediately eligible.
- Briefings: 180 days. Redundant non-Tiingo price rows older than two years may be archived only when a same-session canonical Tiingo row exists.
- Never automatically delete decisions, thesis versions, immutable analysis lineage, ALFRED vintages, user portfolios, or canonical adjusted-price observations.

PHASE 9 COMPLETE
