import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");

test("Vercel uses the standard Next build without replacing the local vinext workflow", () => {
  const manifest = JSON.parse(read("package.json"));
  const vercel = JSON.parse(read("vercel.json"));
  assert.equal(manifest.scripts["build:vercel"], "next build --webpack");
  assert.match(manifest.scripts.build, /vinext build/);
  assert.equal(vercel.framework, "nextjs");
  assert.equal(vercel.buildCommand, "npm run build:vercel");
  assert.doesNotMatch(read("app/layout.tsx"), /next\/font\/google/);
});

test("production frontend never defaults to a visitor localhost API", () => {
  const dashboard = read("app/Dashboard.tsx");
  assert.match(dashboard, /process\.env\.NODE_ENV === "development"/);
  assert.match(dashboard, /: "\/api"/);
  assert.doesNotMatch(dashboard, /NEXT_PUBLIC_API_URL \|\| "http:\/\/127\.0\.0\.1/);
});

test("Render blueprint runs FastAPI with external secrets and a health check", () => {
  const render = read("render.yaml");
  assert.match(render, /runtime: python/);
  assert.match(render, /pip install -r backend\/requirements\.txt/);
  assert.match(render, /uvicorn backend\.main:app --host 0\.0\.0\.0 --port \$PORT/);
  assert.match(render, /healthCheckPath: \/api\/health/);
  for (const key of ["DATABASE_URL", "SUPABASE_SECRET_KEY", "CORS_ALLOWED_ORIGINS", "GEMINI_API_KEY"]) {
    assert.match(render, new RegExp(`key: ${key}\\n\\s+sync: false`));
  }
});

test("dashboard event transport has keepalives and authoritative reconnect recovery", () => {
  const dashboard = read("app/Dashboard.tsx");
  const backend = read("backend/main.py");
  assert.match(dashboard, /maxReconnects = 4/);
  assert.match(dashboard, /dashboardStatus\(jobId\)/);
  assert.match(dashboard, /DASHBOARD_TERMINAL_STATES\.has\(job\.state\)/);
  assert.match(backend, /yield ": keepalive\\n\\n"/);
  assert.match(backend, /"Cache-Control": "no-cache, no-transform"/);
  assert.match(backend, /"X-Accel-Buffering": "no"/);
});
