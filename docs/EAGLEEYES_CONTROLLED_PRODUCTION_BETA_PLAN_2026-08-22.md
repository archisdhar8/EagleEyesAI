# EagleEyes controlled-production beta plan

Local date: 2026-08-22
Scope: release tooling and operating plan only. No deployment, production migration, production write, account creation, invitation, or Git commit/push was performed.
Supersedes the staging requirement in `EAGLEEYES_PHASE10_STAGING_DEPLOYMENT_REPORT_2026-08-22.md`; that file remains historical evidence, not an active release gate.

## A. Revised environment strategy

The release path is now:

`local/test → controlled production deployment → private/internal beta → gradual limited beta`

There is no required long-lived staging frontend, API, database, or Supabase project. Safety remains layered:

1. local frontend/backend tests and production build;
2. disposable PostgreSQL migration apply/verify from an empty schema and from a copy of the last known production schema;
3. clean, immutable expected Git revision and release manifest;
4. read-only, fail-closed production preflight against an explicitly named target;
5. verified current backup and recovery record;
6. additive production migration transaction, bounded backfill, reconciliation, and health verification;
7. owner-only access, synthetic test data, small authenticated smoke/isolation suite, alerts, and feature kill switches;
8. gradual allowlisted expansion after stable elapsed-time soak evidence.

Production stays private during the initial soak. Public signup, brokerage connections, trade execution, and broad invitations remain disabled.

## B. Production preflight

Run from the exact candidate revision:

```bash
export PRODUCTION_RELEASE_CONFIRMATION=EAGLEEYES_CONTROLLED_PRODUCTION
python scripts/phase10_production_preflight.py --phase pre-deploy
```

`scripts/phase10_production_preflight.py` is read-only and prints no secrets. Exit code `0` is required. It fails closed unless all of these are true:

- `APP_ENV=production` and the explicit confirmation value matches;
- worktree is clean and `EXPECTED_GIT_REVISION` exactly equals `git rev-parse HEAD`;
- the non-secret production identity manifest is loaded and its expected Git revision matches both runtime configuration and Git;
- deployment target, frontend, API, worker, recovery, reconciliation, and all ingestion IDs exactly match the manifest;
- database URL host/name and Supabase URL project ref exactly match verified manifest identities;
- API, frontend, and Supabase use HTTPS, and CORS explicitly contains the production frontend origin;
- required API/database/Supabase, Sentry, alert destination, backup, worker, recovery, reconciliation, ingestion, and schedule values are configured;
- worker concurrency is 1–4 and every private-beta flag is explicitly `0` or `1`;
- the backup verification is no older than 24 hours and a restore-test timestamp is recorded;
- the database connection is read-only, the migration table is readable, applied checksums match the repository, no unknown migration is applied, and applied migrations form a prefix of repository order;
- in `pre-deploy`, actual pending migrations exactly equal the ordered list in the manifest; in `post-migration`, none may remain.

The ignored, non-secret release artifact is generated at
`artifacts/phase10-production-identity-manifest.json`. Null identities and
`deployable: false` are intentional blockers. Regenerate it after the clean
release commit and independently fill only verified non-secret identifiers.

For this candidate its expected pending list is:

```text
202608220001_capability_read_models.sql
202608220002_idempotent_ask_requests.sql
202608220003_durable_analytical_jobs.sql
202608220004_phase6_domain_read_model_indexes.sql
202608220005_analytical_scope_keys.sql
```

The script deliberately will not connect if the production identity/confirmation gate fails.

## C. Production migration sequence

No command below has been run against production. The exact authorized sequence is:

```bash
# 1. Hosting/Supabase console: verify backup ID, completion, retention,
#    download/export availability, and the last restore-test record.
git status --short                         # must be empty
git rev-parse HEAD                         # must equal EXPECTED_GIT_REVISION
python scripts/phase10_production_preflight.py --phase pre-deploy

# 2. Apply only the exact additive prefix above, in repository filename order.
python -m backend.migrations status
python -m backend.migrations apply
python -m backend.migrations verify
python scripts/phase10_production_preflight.py --phase post-migration

# 3. Bounded initial read-model backfill for the two internal test portfolios.
python scripts/rebuild_phase6_read_models.py \
  --user-id "$PRODUCTION_TEST_USER_A_ID" --portfolio-id "$PRODUCTION_TEST_USER_A_PORTFOLIO_ID" \
  --ticker AAPL --ticker MSFT --domains company,macro,market,prediction
python scripts/rebuild_phase6_read_models.py \
  --user-id "$PRODUCTION_TEST_USER_B_ID" --portfolio-id "$PRODUCTION_TEST_USER_B_PORTFOLIO_ID" \
  --ticker SPY --ticker QQQ --domains company,macro,market,prediction

# 4. Reconcile and verify CURRENT/visible non-current states.
python scripts/reconcile_read_models.py
python scripts/recover_analytics_jobs.py
```

Then inspect authenticated `/api/operations/metrics`, `/api/providers/health`, job queue/heartbeat, read-model counts by state, and application errors. `FAILED`, `STALE`, `PARTIAL`, and `MISSING` remain explicit; backfill must never relabel unavailable provider data as current.

Rollback/recovery:

- Stop expansion and disable the smallest optional layer first.
- For a web regression, remove traffic from the candidate and restore the previous compatible image; retain additive schema.
- For a worker regression, set `HEAVY_ANALYTICS_ENABLED=0`, stop the worker gracefully, restore the previous compatible worker, then run lease recovery.
- A failed migration transaction rolls back. Never improvise destructive down migrations.
- For committed data corruption, stop web/worker/cron writes, preserve evidence/logs, restore the verified pre-release backup, or roll forward with a reviewed corrective migration.
- Re-run schema verification, reconciliation, core deterministic Ask, and owner isolation before restoring traffic.

## D. Owner smoke suite

The small suite uses only the internal synthetic portfolio. It performs authenticated stored-data Ask calls, creates temporary chat/dashboard records, queues one heavy job, and cleans chat/dashboard records. It never refreshes providers or changes portfolio holdings.

```bash
export RUN_CONTROLLED_PRODUCTION_SMOKE=1
export PRODUCTION_API_URL=https://api.example.invalid
export PRODUCTION_OWNER_SMOKE_TOKEN='<short-lived-user-token>'
export PRODUCTION_OWNER_PORTFOLIO_ID='<synthetic-portfolio-id>'
python scripts/run_controlled_production_smoke.py
```

Cases are: portfolio concentration, AAPL/MSFT comparison, macro state, prediction-market relevance, opportunity ranking, rates-up/growth-down scenario, mixed macro/market/portfolio planning, visual request, dashboard save/close/reopen, and backtest job creation/completion. The runner verifies auth, target portfolio ownership, conversation persistence, structured/canonical results, fingerprints, observed `CURRENT` states, dashboard persistence, durable job reference, separate worker ID, terminal result reference, queue health, and worker heartbeat.

Run the existing minimal header/readiness check separately:

```bash
RUN_PRODUCTION_SMOKE=1 PRODUCTION_SMOKE_ACCESS_TOKEN="$PRODUCTION_OWNER_SMOKE_TOKEN" \
  pytest -q -m production backend/tests/test_production_smoke.py
```

Do not run the full local suite or provider-refresh tests against production.

## E. Two-user tenant-isolation procedure

Create two temporary internal Supabase users manually and two synthetic, non-sensitive portfolios. Use distinct sessions/tokens. Record IDs for A and B for portfolios, conversations, analytical results, result references, dashboards, dashboard revisions, analytical jobs, theses, and decisions.

For every resource type run both A→B and B→A:

1. owner successfully reads the resource through its normal API;
2. hostile user requests the exact owner ID through the deployed API and receives 404/403 with no metadata;
3. hostile user uses their JWT and the publishable key against Supabase REST with `id=eq.<foreign-id>` and receives an empty array;
4. hostile update/delete attempts affect zero rows;
5. result fingerprint/reference substitution does not grant access;
6. list endpoints never contain the other user's ID.

The matrix covers `portfolios`, `chat_conversations`, canonical analytical results, `chat_artifact_links`, `dashboard_views`, `dashboard_view_revisions`, `analytical_jobs`, `investment_theses`, and `investment_decisions`. Both the API owner predicate and RLS result must be captured. A single leak stops the rollout immediately.

Cleanup after evidence capture: delete saved dashboards, conversations, theses, decisions, and portfolios through each owner's API; delete the two auth users in the Supabase console; then, using an approved administrative session, verify no rows remain for either user in owned tables. Durable operational/audit rows may be retained per policy but must not retain raw tokens or sensitive payloads.

## F. Worker/reconciliation startup procedure

Web and worker are independent services:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
python scripts/run_analytics_worker.py --concurrency 2 --poll-seconds 1
```

Scheduled production commands and default cadence:

| Process | Command | Cadence |
|---|---|---|
| lease recovery | `python scripts/recover_analytics_jobs.py` | every 5 minutes |
| read-model reconciliation | `python scripts/reconcile_read_models.py` | every 15 minutes |
| prices + macro | `python scripts/run_provider_ingestion.py --scope market` | every 30 minutes |
| prediction markets | `python scripts/run_provider_ingestion.py --scope prediction` | hourly at minute 10; safely no-ops when disabled |
| fundamentals + news | `python scripts/run_provider_ingestion.py --scope fundamentals` | daily at 06:15 UTC |

After deploy verify worker heartbeat, healthy queue, exclusive claim, live lease/heartbeat updates, bounded retry after a controlled worker stop, recovery after lease expiry, and `SUCCESS`/`PARTIAL`/`FAILED` terminal state. A completed heavy result must carry a worker ID and result reference. The web process must never call a heavy handler; its role is submit/read only.

## G. Feature-flag rollback matrix

| Optional layer | Control | Disabled behavior |
|---|---|---|
| general capability router | `ASK_ROUTER_V2=0` | known deterministic routes remain |
| Gemini planner | `ASK_CAPABILITY_PLANNER_GEMINI=0` | deterministic registered planner remains |
| Gemini narration | `ASK_GEMINI_ENRICHMENT=0` | deterministic composer remains |
| prediction-market enrichment | `PREDICTION_MARKET_ENRICHMENT_ENABLED=0` | prediction tool is explicitly unavailable; other domains remain |
| conversational dashboards | `CONVERSATIONAL_DASHBOARDS_ENABLED=0` | chat answers remain; chat does not create/mutate canvas state |
| all heavy jobs | `HEAVY_ANALYTICS_ENABLED=0` | synchronous deterministic Ask remains; new heavy work unavailable |
| simulation | `SIMULATION_ENABLED=0` | only simulation submissions fail closed |
| optimizer | `OPTIMIZER_ENABLED=0` | only optimizer submissions fail closed |
| backtesting | `BACKTESTING_ENABLED=0` | only backtest submissions fail closed |
| deep company research | `DEEP_COMPANY_RESEARCH_ENABLED=0` | exact stored company reads remain; rebuild submissions fail closed |

Flags are simple deployment environment values, not a new platform. The preflight requires every flag to be explicit. Flag changes require a service restart/redeploy and a core smoke check.

## H. Private soak procedure

Rollout is access-controlled and elapsed-time based:

- Days 1–2: owner/internal account only. Run owner smoke, two-user hostile matrix, one worker recovery drill, one alert-delivery drill, and daily consistency review.
- Days 3–5: add a very small allowlist of trusted testers only after all owner gates stay green.
- Later: expand to a small limited beta cohort only after stable multi-day evidence and no unresolved high-severity issue.

Every five minutes monitor readiness, Ask failure/latency, worker heartbeat, queue depth/oldest age, stuck/expired leases, reconciliation heartbeat/failures, stale models, provider failures, auth/DB errors, and persistence errors. Every hour sample deterministic Ask, planner Ask, dashboard reopen, and provider health. Daily verify isolation, migration checksums, duplicate request keys, permanent `RUNNING` rows, alert delivery, DB growth, and model freshness.

Abort immediately for tenant leakage, auth bypass, canonical-value mismatch, migration inconsistency, unrecoverable/duplicate work, or missing critical alert. Freeze expansion for readiness loss over five minutes, two missed heartbeat intervals, queue age over 120 seconds without explanation, fast Ask p95 over five seconds for three windows, unexpected Ask failures over 1%, increasing stale backlog for three intervals, or non-stabilizing memory/connection growth.

## I. Limited-beta expansion gates

Before the first production deploy: local/backend/frontend suites green; production build/typecheck green; disposable PostgreSQL migration apply/verify green; current production backup and restore-test record; clean expected Git revision; production preflight green; explicit rollback revision/procedure; invitation-only access.

Before adding any tester: all five migrations applied/verified; bounded backfill and reconciliation successful; worker/queue healthy; owner smoke green; A↔B API and RLS matrix green; synthetic alert delivery proven; no critical runtime error; owner-only soak stable.

Before limited beta: multi-day private soak stable; alert acknowledgement ownership established; provider/staleness limitations disclosed; optional-layer rollback rehearsed; latency/failure/queue thresholds met; tester data cleanup/support process ready; no unresolved critical/high security, isolation, migration, persistence, or correctness issue.

Alert coverage must include worker failure/stale heartbeat, stuck jobs, provider outage, reconciliation failure/backlog, elevated Ask failures, database/auth failures, and persistence/dashboard failures. `SENTRY_DSN` plus a named alert destination is configuration evidence only; a delivered and acknowledged synthetic alert is required before expansion beyond owner-only use.

## J. Remaining prerequisites before first deploy

Current status remains blocked for execution:

- the Phase 1–10 candidate is still a dirty worktree, not a clean immutable release revision;
- the exact production database host/name, Supabase project ref, deployment target ID, API/frontend URLs, and deployment credentials are not configured in a verified release session;
- no verified recent production backup ID or restore-test timestamp has been supplied;
- alert destination/delivery is unproven;
- production CORS and every explicit private-beta flag have not passed the new preflight;
- the five migrations remain pending on the previously observed remote database and have not been production-authorized;
- the new production preflight, smoke suite, scheduler, and flag changes have only local validation until a clean release is cut;
- two internal accounts and synthetic portfolios do not yet exist, by design.

Local verification of this tooling revision: production build PASS (existing chunk-size warning only), TypeScript PASS, frontend contracts 81/81 PASS, backend 627 PASS with 9 expected skips and 2 existing warnings, targeted flag/worker tests 31/31 PASS, Python compilation PASS, and `git diff --check` PASS. The production preflight was run without production confirmation/configuration and correctly exited non-zero without a database connection or mutation.

# NOT READY FOR CONTROLLED PRODUCTION DEPLOYMENT

The release strategy is ready to continue without a staging environment, but the first controlled-production deployment remains fail-closed until the prerequisites above are supplied and the production preflight exits zero. No deployment was performed.
