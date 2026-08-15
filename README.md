# EagleEyesAI

## InvestmentDashboard

An authenticated, market-first investment research workspace with a local FastAPI analysis service and Supabase-backed durable storage. EagleEyes combines searchable stock research, macroeconomic market-state identification, historical regime comparisons, Kalshi and Polymarket evidence, portfolio analysis, goal and policy context, AI-generated research boards, and a configurable advanced terminal.

The default experience uses plain-language evidence buckets, portfolio relevance, confidence, freshness, and explicit limitations. Historical macro data, prediction markets, company fundamentals, valuation, price behavior, and portfolio risk remain separate evidence layers rather than being collapsed into one unexplained score.

The app does not connect to a broker, submit trades, or claim to produce a best portfolio.

For a detailed description of every user-facing page, widget, calculation layer, workflow, and limitation, read the [complete user guide](docs/USER_GUIDE.md).

This repository is standalone: its Python environment, private backend configuration, local SQLite fallback, and optional provider caches all live inside `InvestmentDashboard`. It does not require the older parent `investment-thesis` project.

## Start locally

From this folder, install the two runtimes once:

```bash
npm install
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
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
.venv/bin/python -m backend.migrations check
.venv/bin/python -m backend.migrations validate
.venv/bin/python -m backend.migrations status
```

`validate` executes the migrations in a transaction and rolls them back, so it checks the SQL without changing the remote database.

Apply pending migrations:

```bash
.venv/bin/python -m backend.migrations apply
.venv/bin/python -m backend.migrations verify
```

Migration SQL is stored in `supabase/migrations`. Applied files are immutable; create a new timestamped migration for every later schema change.

To copy an existing local SQLite database into Supabase, first inspect the source counts and then apply the idempotent migration:

```bash
.venv/bin/python -m backend.migrate_sqlite
.venv/bin/python -m backend.migrate_sqlite --apply
```

The migration creates a timestamped SQLite backup under `data/backups` before writing to Supabase. SQLite is retained as a recovery copy after migration.

## Provider ingestion

Backfill the existing repository caches into Supabase with idempotent upserts:

```bash
.venv/bin/python -m backend.ingestion backfill
.venv/bin/python -m backend.ingestion status
```

Incremental refreshes are provider-selectable:

```bash
.venv/bin/python -m backend.ingestion refresh --providers markets
.venv/bin/python -m backend.ingestion refresh --providers polygon,tiingo,fred,news
.venv/bin/python -m backend.ingestion refresh --providers sec
```

Extend the modeling history and rebuild monthly point-in-time macro regimes:

```bash
.venv/bin/python -m backend.ingestion history --providers tiingo,alfred,regimes
```

The historical job requests broad and sector ETF prices from 2005 (or fund inception), active stock prices for ten years, and month-end ALFRED vintages for the regime feature set. Actual price depth depends on the Polygon subscription; the importer prints every symbol whose returned start date is later than requested. ALFRED imports retain an 18-month window for each vintage, which is sufficient for year-over-year and three-month regime features without storing every unchanged historical value for every vintage. Daily market-observed series that ALFRED does not revision-track (the Treasury curve, high-yield spread, and oil) are aggregated locally and explicitly stored as non-revised month-end point-in-time proxies.

Regime labels are stored monthly using `macro-regime-rules-v1`. Every label records the vintage cutoff, latest observation and vintage dates, feature values, scenario probabilities, confidence, and coverage. Labels are skipped when fewer than five required series were available, rather than filling missing history with revised future data.

Prediction-market refreshes run hourly. Venue-specific contracts are linked to canonical macro series across expirations, while every probability, bid/ask, confidence score, and scenario snapshot remains timestamped. Once at least six monthly genuine-market forecasts have a subsequently realized point-in-time macro regime, monitoring reports Brier score and calibration error rather than substituting macro priors.

## Quantitative model validation

The optimizer uses `walk-forward-regime-shrinkage-v2`:

- Daily covariance is winsorized and dynamically shrunk toward a constant-correlation target. The result records sample counts, shrinkage intensity, missing-data fraction, condition numbers, effective rank, and minimum eigenvalue.
- Fixed sector scenario shocks are not used. Each macro state uses the next-month returns historically observed after point-in-time regime labels. Sparse state/security estimates shrink toward sector-ETF, asset-unconditional, and cross-sectional priors.
- Current prediction-market probabilities weight those empirical state returns. Company research adjusts the result with a disclosed weight; it does not replace price history.
- The walk-forward runner uses an expanding regime window, trailing 504 trading days for covariance, quarterly re-estimation, and non-overlapping three-month tests.
- Every run compares the Balanced model with a quarterly equal-weight benchmark and the user's static current allocation. Results include annualized return/volatility, maximum drawdown, Sharpe ratio, turnover, and quarter-level hit rates.

Historical macro probabilities substitute for unavailable historical prediction-market snapshots during validation. Returns exclude fees, spreads, taxes, and execution delay; these limitations are displayed beside the results.

### Stored validation and ML challenger

Supabase stores an immutable model registry plus queryable validation runs and folds. Each fold records train/test dates, the information cutoff, sample counts, model and benchmark metrics, diagnostics, and an explicit leakage check. The API exposes recent records at `GET /api/model-validation`.

The experimental regime challenger is an L2-regularized multinomial logistic regression. It predicts next month's dominant regime from point-in-time macro features using expanding training windows, twelve-month tests, and a one-month embargo. It is compared with the transparent rules probabilities on Brier score, log loss, calibration, accuracy, probability stability, and fold consistency. The production regime model is never changed automatically: the challenger must improve Brier score by at least 2%, improve log loss, win at least 60% of folds, and pass every leakage check before the UI recommends considering a probability blend.

GitHub Actions schedules prediction markets hourly, prices/macro/news on weekdays, SEC fundamentals weekly, and extended Tiingo/ALFRED history monthly. Configure repository Actions secrets named `DATABASE_URL`, `POLYGON_API_KEY`, `TIINGO_API_KEY`, `FRED_API_KEY`, and `SEC_USER_AGENT`. Tiingo supplies the coherent adjusted return history; Polygon remains the recent market-data source. Use the Supabase session-pooler URL for `DATABASE_URL`; never commit these values.

Daily and monthly data jobs also run `python -m backend.monitoring run`. Each run persists prediction-market calibration, covariance conditioning, regime counts, benchmark performance, turnover, allocation stability, freshness, and coverage. New model versions enter evaluation first; a database promotion gate requires an immutable promotion decision before production status is allowed.

Legacy FRED cache rows are explicitly marked as not point-in-time because they contain latest-known observations. Scheduled FRED rows preserve their retrieval vintage so model validation can distinguish them.

## Verification

Run the complete local regression matrix with:

```bash
npm run test:all
```

This builds the frontend, runs the TypeScript and backend suites, then exercises authenticated browser journeys with Playwright. Browser tests use deterministic provider fixtures and intercepted Supabase test responses; production authentication is not bypassed. See [`docs/PHASE_8_TEST_STRATEGY.md`](docs/PHASE_8_TEST_STRATEGY.md) for coverage, golden quantitative contracts, and the phase-by-phase verification record.

Real integrations use a separate opt-in suite so normal CI never depends on credentials or provider uptime. See [`docs/LIVE_PROVIDER_SMOKE_TESTS.md`](docs/LIVE_PROVIDER_SMOKE_TESTS.md). Advanced → Provider health displays configuration state, last validated ingestion, stored coverage, fallbacks, errors, and reported rate-limit metadata without exposing secret values.

## Historical coverage contract

Research security responses now include a versioned adjusted-price coverage record with provider, first and last date, observations, estimated missing sessions, corporate-action adjustment method, full-cycle eligibility, direct factor-model eligibility, sector/broad-ETF fallback, warnings, and lineage. A seven-year span is the disclosed full-cycle minimum. Shorter histories remain researchable, but factor and regime conclusions are visibly weakened and return adjustments are shrunk toward transparent priors.

Use `GET /api/research/coverage?tickers=AAPL,SPY` to audit symbols before relying on backtests. Provider capability and ingestion health are available at `GET /api/providers/health`.

## Optional explanations

Calculations do not require an LLM. Choose Template only, Local Ollama, or an OpenAI-compatible endpoint in Optimize. For an authenticated compatible endpoint, set `DASHBOARD_LLM_API_KEY` in the API process environment. The key is never stored in the dashboard database.

## CSV format

Required: `ticker` plus one of `shares`, `weight`, or `market_value`.

Optional: `cost_basis`, `account_type`, and `acquisition_date`.
