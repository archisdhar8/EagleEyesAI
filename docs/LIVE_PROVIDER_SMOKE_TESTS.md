# Live provider smoke tests

These tests are intentionally excluded from normal deterministic test runs. They require a running EagleEyes API, a dedicated non-production Supabase user, and real provider credentials configured only on the API.

Required environment variables:

- `RUN_LIVE_SMOKE=1`
- `LIVE_API_URL=http://127.0.0.1:8000`
- `LIVE_ACCESS_TOKEN=<short-lived safe-test-user token>`
- `LIVE_SECOND_ACCESS_TOKEN=<optional second safe-test-user token for RLS isolation>`
- `LIVE_SMOKE_TICKER=SPY`

Run:

```bash
.venv/bin/python -m pytest -m live backend/tests/test_live_provider_smoke.py
```

The suite verifies authenticated Supabase access, optional two-user RLS isolation, FRED, adjusted-price history, Kalshi/Polymarket discovery, SEC Company Facts, and the Gemini planner → deterministic widgets → narrator path. It never prints credentials and does not run in CI unless explicitly enabled.
