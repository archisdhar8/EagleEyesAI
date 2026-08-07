# EagleEyesAI

## InvestmentDashboard

A single-user portfolio research sandbox with a local FastAPI analysis service and Supabase-backed durable storage. Prediction-market probabilities set macro scenario weights; existing company research and an explainable statistical model test portfolio alternatives against those scenarios.

The app does not connect to a broker, submit trades, or claim to produce a best portfolio.

## Start locally

From this folder, install the two runtimes once:

```bash
npm install
../.venv/bin/python -m pip install -r backend/requirements.txt
```

Then start both the local API and dashboard:

```bash
npm run local
```

Open `http://localhost:3000`. When `DATABASE_URL` is configured in `backend/.env`, portfolios, profiles, scenario history, and saved analyses use Supabase. Without it, the app falls back to `data/dashboard.db` for local development and tests.

## Supabase schema

Put the private Postgres connection string in `backend/.env` as `DATABASE_URL`; never put it in an example file or commit it.

Test the connection and inspect migration status:

```bash
../.venv/bin/python -m backend.migrations check
../.venv/bin/python -m backend.migrations validate
../.venv/bin/python -m backend.migrations status
```

`validate` executes the migrations in a transaction and rolls them back, so it checks the SQL without changing the remote database.

Apply pending migrations:

```bash
../.venv/bin/python -m backend.migrations apply
../.venv/bin/python -m backend.migrations verify
```

Migration SQL is stored in `supabase/migrations`. Applied files are immutable; create a new timestamped migration for every later schema change.

To copy an existing local SQLite database into Supabase, first inspect the source counts and then apply the idempotent migration:

```bash
../.venv/bin/python -m backend.migrate_sqlite
../.venv/bin/python -m backend.migrate_sqlite --apply
```

The migration creates a timestamped SQLite backup under `data/backups` before writing to Supabase. SQLite is retained as a recovery copy after migration.

## Provider ingestion

Backfill the existing repository caches into Supabase with idempotent upserts:

```bash
../.venv/bin/python -m backend.ingestion backfill
../.venv/bin/python -m backend.ingestion status
```

Incremental refreshes are provider-selectable:

```bash
../.venv/bin/python -m backend.ingestion refresh --providers markets
../.venv/bin/python -m backend.ingestion refresh --providers polygon,fred,news
../.venv/bin/python -m backend.ingestion refresh --providers sec
```

GitHub Actions schedules prediction markets hourly, prices/macro/news on weekdays, and SEC fundamentals weekly. Configure repository Actions secrets named `DATABASE_URL`, `POLYGON_API_KEY`, `FRED_API_KEY`, and `SEC_USER_AGENT`. Use the Supabase session-pooler URL for `DATABASE_URL`; never commit these values.

Legacy FRED cache rows are explicitly marked as not point-in-time because they contain latest-known observations. Scheduled FRED rows preserve their retrieval vintage so model validation can distinguish them.

## Optional explanations

Calculations do not require an LLM. Choose Template only, Local Ollama, or an OpenAI-compatible endpoint in Optimize. For an authenticated compatible endpoint, set `DASHBOARD_LLM_API_KEY` in the API process environment. The key is never stored in the dashboard database.

## CSV format

Required: `ticker` plus one of `shares`, `weight`, or `market_value`.

Optional: `cost_basis`, `account_type`, and `acquisition_date`.
