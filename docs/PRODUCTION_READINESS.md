# EagleEyes production runbook

## Release gate

1. Apply additive migrations in order and record the migration commit.
2. Run the complete local suite, then the live provider/RLS suite against test users.
3. Create and restore-test a database backup in an isolated Supabase project.
4. Deploy a candidate, run the production smoke test, and inspect operational metrics.
5. Promote only when provider freshness, coverage, board verification, and financial wording checks pass.

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
