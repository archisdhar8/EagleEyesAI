# EagleEyes Vercel + Render deployment

EagleEyes uses three deployment surfaces:

- Vercel runs the Next.js frontend.
- Render runs the FastAPI service.
- Supabase provides Postgres and authentication.

The frontend and backend must be deployed separately. Never add server-side
database or provider secrets to a `NEXT_PUBLIC_*` variable.

## 1. Verify the release locally

```bash
npm run build:vercel
npm run typecheck
.venv/bin/python -m pytest
```

Commit only after the complete release candidate passes. Vercel and Render
should deploy the same Git commit.

## 2. Create the Render API

Create a Render Blueprint from the repository's `render.yaml`, or create a
Python Web Service with these settings:

```text
Build command: pip install -r backend/requirements.txt
Start command: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
Health check: /api/health
```

Populate every `sync: false` environment variable in Render. Set
`CORS_ALLOWED_ORIGINS` to exact comma-separated browser origins, for example:

```text
https://eagleeyes-ai.vercel.app
```

Do not use `*`. Localhost origins are allowed separately for development.

## 3. Create the Vercel frontend

Import the GitHub repository into Vercel with the Next.js framework preset.
The checked-in `vercel.json` selects `npm run build:vercel`.

Configure these variables for Production and Preview as appropriate:

```text
NEXT_PUBLIC_API_URL=https://eagleeyes-api.onrender.com/api
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
```

The production frontend deliberately falls back to same-origin `/api`, never
the visitor's localhost, when `NEXT_PUBLIC_API_URL` is missing. Because the API
is deployed separately, treat a missing Vercel variable as a deployment error.

## 4. Finish authentication and CORS

Add the final Vercel origin and `http://localhost:3000` to Supabase Auth's Site
URL/redirect allowlist. Add the exact final Vercel origin to Render's
`CORS_ALLOWED_ORIGINS`, then redeploy the API.

## 5. Smoke test

- `/api/health` reports trading disabled.
- Sign-up/sign-in and sign-out work on the Vercel origin.
- Portfolio, Research, Decisions, and Ask load authenticated data.
- An AI dashboard survives a dropped event stream and reaches a terminal state.
- Browser requests never target `127.0.0.1` or `localhost` in production.
- No database URL, provider key, or Supabase secret appears in browser assets.

Render Free can sleep or restart. Dashboard jobs currently execute in the API
process, so a durable external job worker remains required before EagleEyes is
treated as reliable production infrastructure.
