import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspace = readFileSync("app/components/shared/workspace-implementations.tsx", "utf8");
const research = readFileSync("app/components/research/ResearchDiscovery.tsx", "utf8");
const backend = readFileSync("backend/main.py", "utf8");

test("market expectations keep market and user probabilities distinct", () => {
  assert.match(workspace, /source_type:\"MARKET_IMPLIED\"/);
  assert.match(workspace, /Compare my probability/);
  assert.match(workspace, /append-only user forecast/);
  assert.match(workspace, /percentage points/);
});

test("company research exposes mapped forward-looking context", () => {
  assert.match(research, /Forward statistics/);
  assert.match(research, /Prediction-market evidence is shown only when a verified company mapping exists/);
  assert.match(backend, /forecasting\.build_intelligence\(user\.id, ticker=normalized/);
});

test("forecasting APIs remain authenticated and scenario overrides preserve sources", () => {
  assert.match(backend, /def forecasting_markets[\s\S]*Depends\(require_user\)/);
  assert.match(backend, /def create_user_forecast[\s\S]*Depends\(require_user\)/);
  assert.match(backend, /\"source_type\": \"USER_DEFINED\"/);
  assert.match(backend, /does not overwrite market evidence/);
});
