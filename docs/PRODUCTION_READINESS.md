# EagleEyes production runbook

## Release gate

The active path is local/test → controlled production → private beta → limited beta.
A separate staging environment is not required. Follow
`EAGLEEYES_CONTROLLED_PRODUCTION_BETA_PLAN_2026-08-22.md` and require its
fail-closed preflight before any production mutation.

1. Run the complete local suite and disposable PostgreSQL migration validation.
2. Freeze a clean expected revision and verify a current production backup.
3. Run `python scripts/phase10_production_preflight.py --phase pre-deploy`.
4. Apply additive migrations in order, backfill bounded internal scopes, reconcile, and verify.
5. Deploy privately, run owner smoke plus two-user API/RLS isolation, and inspect operational metrics/alerts.
6. Expand only after stable elapsed-time private soak evidence.

## Live isolation and provider checks

The live tests are opt-in and never use deterministic mocks. Configure `LIVE_API_URL`, two short-lived test-user access tokens, the Supabase URL and publishable key, then set `RUN_LIVE_SMOKE=1`. The direct REST test creates a temporary terminal layout as user one, proves user two cannot read it through Supabase REST, and removes it.

## Backups and migrations

`python -m backend.backup /approved/backup/directory` is always a dry run. Add `--execute` only after confirming the destination. PostgreSQL backups use `pg_dump --format=custom`; local SQLite uses a timestamped copy. Restore into an isolated environment and run API contract tests before accepting the backup. Never rewrite immutable dashboard or validation runs; use additive, versioned migrations.

## Limits, logging, and errors

- Requests default to 1 MiB and 240 requests per minute per client/path group. Configure `MAX_REQUEST_BYTES` and `RATE_LIMIT_REQUESTS_PER_MINUTE` for production.
- Every response gets a request ID and security headers. Logs are structured and do not include authorization headers, access tokens, holdings payloads, or secret values.
- Set `SENTRY_DSN`, `APP_ENV`, and optionally `SENTRY_TRACES_SAMPLE_RATE` to activate error monitoring. Default PII collection is disabled.
- `/api/operations/metrics` reports latency, provider status, model monitoring, validation, cache hits, partial successes, and verification failures to authenticated users.

## Secret handling

Runtime secrets belong in the hosting secret manager or GitHub Actions secrets. Only publishable Supabase values may reach the browser. Never expose `DATABASE_URL`, provider keys, Gemini keys, service-role credentials, access tokens, or Sentry auth tokens through `NEXT_PUBLIC_*`, logs, API metadata, fixtures, or commits.

## Financial research wording

EagleEyes provides comparative research and deterministic portfolio analysis. It does not submit trades or label candidates as buy recommendations. Results must disclose universe, freshness, assumptions, limitations, lineage, and what could change the view. Portfolio-fit evidence stays separate from company quality. Legal review is required before changing the product promise to individualized investment advice.

## Production smoke

Set `RUN_PRODUCTION_SMOKE=1`, `PRODUCTION_API_URL`, and a short-lived `PRODUCTION_SMOKE_ACCESS_TOKEN`, then run `pytest backend/tests/test_production_smoke.py`. The test verifies health, authenticated briefing and Research, operational monitoring, trading-disabled status, request IDs, and security headers.

For the controlled-production owner workflow, use
`scripts/run_controlled_production_smoke.py` as documented in the active beta
plan. Do not run provider-refresh or the full local suite against production.
