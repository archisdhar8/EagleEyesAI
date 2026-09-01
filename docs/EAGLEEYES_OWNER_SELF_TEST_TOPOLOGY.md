# EagleEyes zero-cost owner self-test topology

This profile is for a single owner validating the production deployment. It is
not the private-beta topology and must not be represented as private-beta ready.

## Runtime

- Vercel serves the existing Next.js frontend.
- one Free Render web service serves the FastAPI application;
- the existing Supabase production project stores application and provider data;
- scheduled GitHub Actions perform market, fundamentals, prediction-market, and
  historical ingestion;
- each ingestion workflow reconciles persisted read models after a successful
  refresh;
- the daily owner-maintenance workflow reconciles persisted read models.

The GitHub schedules use the repository's included Actions allowance. They are
zero incremental cost only while that allowance and the current Vercel, Render,
Supabase, and provider entitlements remain available. A missed or failed Action
does not make stale data current; normal freshness states remain authoritative.

## Enabled product surface

Fast deterministic capabilities remain enabled: stored-data Research, portfolio
metrics, evidence/data-quality views, deterministic Ask routing and composition,
prediction-market enrichment, and conversational dashboards. Provider refreshes
run out of process through GitHub Actions so they do not consume the Free Render
API's memory budget.

Durable heavy analytics are fail-closed by setting all of these to `0`:

- `HEAVY_ANALYTICS_ENABLED`
- `SIMULATION_ENABLED`
- `OPTIMIZER_ENABLED`
- `BACKTESTING_ENABLED`
- `DEEP_COMPANY_RESEARCH_ENABLED`

No worker or recovery service is provisioned. Unsupported requests must return
their explicit unavailable state; they must never enqueue work that has no
consumer. Owner maintenance intentionally does not requeue legacy heavy jobs.

## Release gates

Copy `docs/templates/owner-self-test-identity-manifest.json` outside the Git
worktree, replace the exact release/evidence values, point
`PRODUCTION_IDENTITY_MANIFEST` to that copy, and run:

```bash
python scripts/phase10_production_preflight.py --gate owner-self-test --phase pre-deploy
```

The owner gate still requires an immutable clean SHA, verified production
identity, exact CORS and flags, current backup evidence, a live read-only
migration audit, and the checked-in zero-cost topology. It does not require a
paid analytics worker, paid cron services, Sentry delivery, or restore-drill
proof.

The default remains the stricter private-beta gate:

```bash
python scripts/phase10_production_preflight.py --gate private-beta --phase pre-deploy
```

Private beta continues to require worker/recovery/reconciliation/ingestion
service identity, bounded worker concurrency, alerting/Sentry configuration,
and restore-test evidence. The preflight reports `private_beta_gaps` even when
the selected owner gate passes.

## Owner smoke

After deployment, use the existing authenticated owner smoke without asserting
a durable worker:

```bash
python scripts/run_controlled_production_smoke.py --gate owner-self-test
```

The private-beta smoke remains the default and still verifies durable heavy-job
completion and worker health.
