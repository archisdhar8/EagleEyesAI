# EagleEyes release-candidate gate

Local date: 2026-08-22
Release path: `local/test → controlled production → private/internal beta → gradual limited beta`
Scope: release-gate work only. No production deploy, migration, backup, restore, account creation, alert trigger, data mutation, commit, or push was performed.

## A. Exact release revision

- Branch: `feat/chat-first-ask-canvas`
- Current HEAD: `8ad6f910b52a24d1099ef05e6a2a35426441e36e`
- Clean tree: **NO**
- Candidate entries outside HEAD after this gate: 92 visible source entries: backend 25, frontend 4, migrations 5, deployment 1, scripts 16, tests 27, docs 14. The ignored production identity artifact is additional release evidence, not a committed source entry.
- Deployable immutable revision: **NONE YET**. HEAD does not contain the candidate changes.

Release checklist tied to the current base revision:

- [x] `git status`, `git diff`, and `git diff --check` inspected.
- [x] Changes grouped and reviewed for release purpose.
- [x] No tracked `.env`, credential, private-key, token, or secret file found.
- [x] No hard-coded private-key/database-password/API-token signature found outside ignored local environment files.
- [x] Generated `.DS_Store`, caches, build output, logs, and `artifacts/` are ignored and absent from the candidate file list.
- [x] Production blueprint does not invoke `phase10_staging_preflight.py`; the staging script/report are retained only as historical evidence.
- [x] No active production plan requires a staging environment.
- [ ] Review/approve all intended changes and create one clean commit.
- [ ] Regenerate the identity manifest with the new commit SHA.
- [ ] Configure deployment to reference that exact SHA.

Change summary:

| Group | Intended release-candidate content | Hygiene result |
|---|---|---|
| Backend | canonical analytical contract, read models, bounded Ask DAG/planner, durable jobs, dashboard presentation, owner scoping, telemetry, feature kill switches, production CORS correction | Intended Phase 1–10/release safety; no debug credentials found |
| Frontend | chat-first Ask canvas contracts/state and responsive presentation | Intended Phase 8 UI; no generated bundle tracked |
| Migrations | five additive/read-model/job/scope migrations | Ordered, checksum-addressed, unapplied |
| Deployment | Render web, worker, recovery, reconciliation, ingestion schedules and explicit flags | Service names defined; provider IDs and target identity absent |
| Scripts | acceptance/benchmarks, worker/recovery/reconciliation/backfill, production preflight, owner smoke, scheduled ingestion | Production uses only current production scripts; staging preflight is historical and unused |
| Tests | backend contracts, heavy jobs, read models, planner/dashboard, frontend contracts and E2E | Test sources only; no test tokens found |
| Docs | architecture/Phase 1–10 evidence, controlled-production runbook, this gate | Historical staging document explicitly superseded |

No change was automatically discarded. “Intended” means it maps to the completed Phase 1–10 requests; it still requires human commit review because it is not in HEAD.

Current local verification: backend 627 passed/9 skipped with 2 existing warnings; frontend contracts 81/81 passed; targeted CORS/migration/flag tests 18/18 passed; TypeScript passed; production build passed with the existing chunk-size warning; Python compilation, JSON/YAML parsing, and `git diff --check` passed.

## B. Production identity verification

Non-secret manifest: `artifacts/phase10-production-identity-manifest.json`.

Observed but **not independently verified**:

- configured database hostname: `db.ootsfffufoervvjpemdg.supabase.co`;
- configured Supabase project ref: `ootsfffufoervvjpemdg`;
- Render blueprint names: `eagleeyes-api`, `eagleeyes-analytics-worker`, `eagleeyes-job-recovery`, `eagleeyes-read-model-reconciliation`, `eagleeyes-market-ingestion`, `eagleeyes-fundamentals-ingestion`, and `eagleeyes-prediction-ingestion`.

Unknown/unverified:

- whether the observed Supabase project is the intended production project;
- expected database name/project identity approved by the operator;
- Render account/project target ID and every actual service ID;
- frontend host/project/service ID; `.vercel/project.json` is absent;
- production API/frontend URLs and deployment credentials.

The manifest deliberately keeps these identities null and `deployable: false`. The preflight now compares runtime values to manifest identities and refuses to connect to the database until environment, confirmation, database, Supabase, and deployment-target identities pass.

## C. Backup/restore evidence

**No production backup or restore proof exists in the available workspace.**

Repository capability: `python -m backend.backup <approved-directory>` is dry-run by default; `--execute` invokes `pg_dump --format=custom --no-owner`. This proves only that an export mechanism exists, not that the installed host has `pg_dump`, the production role can export, storage is durable/encrypted, retention is configured, or the dump is restorable.

Provider-managed backup capability/plan for project `ootsfffufoervvjpemdg` is unknown because no provider-console evidence or management credential is available. Do not claim managed backups.

Required proof record before readiness:

1. provider/mechanism and backup ID;
2. UTC completion timestamp, location, encryption, retention, and access owner;
3. restore into a disposable, explicitly non-production PostgreSQL database;
4. restore duration and target ID;
5. `backend.migrations verify` against the restore;
6. representative counts for users' owned tables without exposing row contents;
7. RLS enabled, policies present, anonymous access blocked;
8. application read-only connection and representative owner read;
9. destroy the disposable restore after evidence retention approval.

Never restore over production. Until this record exists, backup/restore checks remain failed.

## D. CORS configuration

Production origins are not configured, so hosted validation is **NOT RUN**.

Code-level findings:

- configured origins require exact `http(s)://host[:port]` values and reject `*`;
- credentials are disabled because authentication uses explicit bearer headers rather than browser cookies;
- a release-gate defect allowed localhost by regex in production; this gate changed it so localhost/127.0.0.1 are development-only;
- preflight requires HTTPS API/frontend/Supabase, an exact manifest CORS set, the frontend origin, no wildcard, and no localhost.

Required hosted check after origins are known: allowed frontend `OPTIONS` returns its exact origin and authorization header allowance; an unlisted HTTPS origin and localhost return no CORS allow-origin header; authenticated API requests still succeed with a bearer token.

## E. Feature-flag matrix

Recommended first owner-only values preserve all accepted deterministic/analytical functionality while keeping external Gemini paths off by default:

| Feature | Production default | Emergency off |
|---|---:|---|
| general deterministic/compositional router | `ASK_ROUTER_V2=1` | set `0`; known deterministic routes remain |
| Gemini planner | `ASK_CAPABILITY_PLANNER_GEMINI=0` | already off; deterministic planner remains |
| Gemini narration | `ASK_GEMINI_ENRICHMENT=0` | already off; deterministic composer remains |
| prediction enrichment | `PREDICTION_MARKET_ENRICHMENT_ENABLED=1` | set `0` on web and ingestion scheduler |
| conversational dashboards | `CONVERSATIONAL_DASHBOARDS_ENABLED=1` | set `0`; chat remains |
| heavy-job master | `HEAVY_ANALYTICS_ENABLED=1` | set `0`; fast deterministic Ask remains |
| simulation | `SIMULATION_ENABLED=1` | set `0` |
| optimization | `OPTIMIZER_ENABLED=1` | set `0` |
| backtesting | `BACKTESTING_ENABLED=1` | set `0` |
| deep research | `DEEP_COMPANY_RESEARCH_ENABLED=1` | set `0`; stored exact reads remain |

Reasoning: accepted functions stay enabled; cost/availability-dependent Gemini calls stay opt-in; every optional layer has a narrow rollback. Runtime configuration is not yet set or verified. Preflight requires explicit `0`/`1` values and exact equality with the manifest.

## F. Alert verification

Actually delivered alerts: **NONE**.

The repository records worker and reconciliation heartbeats, job failure state, provider status, request failure metrics, and Sentry exceptions when `SENTRY_DSN` exists. Current local configuration has no Sentry DSN or alert destination, and no external routing/rule evidence exists for stale heartbeat, failed job, reconciliation failure, or elevated application failure.

Required safe proof: configure the named destination without recording its secret; trigger synthetic stale-worker, failed-job, reconciliation-failure, and application-error conditions in controlled production; record trigger/receipt UTC timestamps, latency, acknowledgement, and recovery notification. Missing delivery blocks this release under the requested gate.

## G. Two-user readiness

Accounts created: **NO**. Fixtures created: **NO**. No account creation was authorized.

Prepared synthetic fixtures:

- Internal A: portfolio `RC-A-TECH`, AAPL 60% / MSFT 40%; conversation `RC-A-CONVERSATION`; dashboard `RC-A-VIEW`; thesis `RC-A-THESIS`; decision `RC-A-DECISION`.
- Internal B: portfolio `RC-B-BALANCED`, SPY 70% / BND 30%; conversation `RC-B-CONVERSATION`; dashboard `RC-B-VIEW`; thesis `RC-B-THESIS`; decision `RC-B-DECISION`.
- Each user creates one canonical result/result reference and, after worker health is proven, one bounded heavy job.

Isolation matrix: for portfolio, conversation, dashboard, revision, result reference, analytical job, thesis, and decision, run A→B and B→A through the deployed API and direct Supabase REST with the hostile user's JWT/publishable key. Owner read must succeed; hostile exact-ID read/update/delete must return 403/404, empty rows, or zero affected rows. Fingerprints and result references never authorize. Any leakage stops rollout.

Cleanup: delete user-owned fixtures through owner APIs, delete both auth users in the provider console, then use an approved administrative audit to verify no owned rows remain. Retain only policy-approved operational evidence.

## H. Migration order

The configured remote was previously observed read-only with migrations through `202608180001` applied and these five pending. This gate did not reconnect because production identity is unverified.

| Order | Migration | Purpose/dependency | Validation and expected impact | Recovery |
|---:|---|---|---|---|
| 1 | `202608220001_capability_read_models.sql` | Adds dataset versions/read models; depends on auth users and portfolios | Locally validated; additive tables/index, RLS/policies | transaction rollback; after commit preserve schema or restore backup for corruption |
| 2 | `202608220002_idempotent_ask_requests.sql` | Durable Ask lifecycle; depends on conversations/messages/auth | Locally validated; additive table/index/RLS | same |
| 3 | `202608220003_durable_analytical_jobs.sql` | Queue, attempts, leases, dedupe; depends on users/portfolios | Locally validated; additive tables/indexes/RLS | disable heavy jobs/worker; preserve rows; restore only for corruption |
| 4 | `202608220004_phase6_domain_read_model_indexes.sql` | Domain history/scope indexes; depends on 001 | Locally validated; index creation cost only | retain compatible indexes or corrective migration |
| 5 | `202608220005_analytical_scope_keys.sql` | Adds/backfills scope keys and relaxes portfolio-only scope; depends on 001 before domain backfill | Locally validated; updates existing read-model/version rows and replaces PK, so backup and bounded maintenance observation are mandatory | transaction rollback; restore verified backup if committed data is corrupt |

No later migration exists in the branch. Production checksum/order validation remains blocked until identity passes. Do not apply yet.

## I. Backfill/startup sequence

Final controlled sequence, not executed:

```bash
# 1. Freeze access and verify backup/restore evidence plus previous rollback SHA.
git status --short                       # empty
git rev-parse HEAD                       # exact manifest/runtime SHA
python scripts/phase10_production_preflight.py --phase pre-deploy

# 2. Apply schema before starting code whose readiness requires new tables.
python -m backend.migrations status
python -m backend.migrations apply
python -m backend.migrations verify
python scripts/phase10_production_preflight.py --phase post-migration

# 3. Deploy/start web, then independent worker and schedules.
uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
python scripts/run_analytics_worker.py --concurrency 2 --poll-seconds 1
python scripts/recover_analytics_jobs.py                 # every 5 minutes
python scripts/reconcile_read_models.py                  # every 15 minutes
python scripts/run_provider_ingestion.py --scope market  # every 30 minutes
python scripts/run_provider_ingestion.py --scope prediction  # hourly
python scripts/run_provider_ingestion.py --scope fundamentals # daily

# 4. Bounded internal-user backfill after services are healthy.
python scripts/rebuild_phase6_read_models.py --user-id "$PRODUCTION_TEST_USER_A_ID" \
  --portfolio-id "$PRODUCTION_TEST_USER_A_PORTFOLIO_ID" --ticker AAPL --ticker MSFT \
  --domains company,macro,market,prediction
python scripts/rebuild_phase6_read_models.py --user-id "$PRODUCTION_TEST_USER_B_ID" \
  --portfolio-id "$PRODUCTION_TEST_USER_B_PORTFOLIO_ID" --ticker SPY --ticker BND \
  --domains company,macro,market,prediction
python scripts/reconcile_read_models.py
python scripts/recover_analytics_jobs.py
```

Then verify readiness, worker heartbeat/queue/claim/lease/recovery, reconciliation, provider heartbeats, and CURRENT/non-current state counts. Run the authenticated owner smoke runner and a manual browser close/reopen-canvas check, then the A↔B matrix. Do not invite users.

Emergency stop: freeze traffic/allowlist; set the smallest failing optional flag to `0`; set `HEAVY_ANALYTICS_ENABLED=0` and stop the worker for queue/worker faults; stop cron writes for reconciliation/provider faults; roll web/worker to the recorded compatible SHA; never down-migrate destructively; restore the verified backup only for confirmed committed corruption. Stop immediately for migration/RLS/auth/result-reference failure, unexpected Ask failure, duplicate persistence, unrecoverable jobs, saturation, missing critical alerts, or stale data labeled CURRENT.

## J. Preflight result

Result: **FAIL (exit 2), read-only, no database connection, no mutation, no secrets printed.**

Passing categories: manifest loaded/schema/environment marker; ordered repository migration declaration; no wildcard/localhost in the configured-origin set (currently empty); migration filenames/checksum inputs internally well formed.

Failed blocker categories:

- dirty/uncommitted revision and missing runtime expected SHA;
- null/unverified database and Supabase identities;
- null deployment target and frontend/API/worker/recovery/reconciliation/ingestion IDs;
- missing production API/frontend/Supabase runtime confirmation;
- missing CORS origin set;
- missing explicit runtime feature flags;
- missing worker/scheduler identities and cadence configuration;
- missing backup ID/recent verification/restore proof;
- missing Sentry/alert destination;
- explicit production confirmation absent;
- database read and migration-state comparison intentionally skipped by the identity gate.

## K. Remaining blockers

1. Human review and one clean release commit containing all intended candidate changes.
2. Regenerated identity manifest tied to that new SHA.
3. Independent confirmation of the production database host/name and Supabase project ref.
4. Actual deployment target and every frontend/API/worker/cron service ID plus deployment access.
5. Verified current backup and disposable restore evidence.
6. Exact production frontend/API URLs and CORS behavior.
7. Explicit runtime feature-flag values matching the manifest.
8. Configured alert destination and delivered synthetic alert evidence.
9. Two internal accounts/fixtures and authorization to create them.
10. A zero-exit pre-deploy preflight and read-only confirmation of the exact five pending migrations.

## L. Final verdict

# NOT READY FOR CONTROLLED PRODUCTION DEPLOYMENT

Local tests and architecture do not clear identity, immutability, backup/restore, alert, CORS, account, or production preflight gates. The release remains fail-closed.

RELEASE CANDIDATE GATE COMPLETE
