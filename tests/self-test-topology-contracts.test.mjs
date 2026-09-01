import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");

test("owner self-test runs one Free Render API and disables every durable heavy capability", () => {
  const render = read("render.yaml");
  assert.match(render, /type: web[\s\S]*plan: free/);
  assert.doesNotMatch(render, /type: (worker|cron)/);
  for (const flag of [
    "HEAVY_ANALYTICS_ENABLED",
    "SIMULATION_ENABLED",
    "OPTIMIZER_ENABLED",
    "BACKTESTING_ENABLED",
    "DEEP_COMPANY_RESEARCH_ENABLED",
  ]) {
    assert.match(render, new RegExp(`key: ${flag}\\n\\s+value: "0"`));
  }
  for (const flag of ["ASK_ROUTER_V2", "PREDICTION_MARKET_ENRICHMENT_ENABLED", "CONVERSATIONAL_DASHBOARDS_ENABLED"]) {
    assert.match(render, new RegExp(`key: ${flag}\\n\\s+value: "1"`));
  }
});

test("scheduled ingestion and maintenance reconcile stored read models", () => {
  for (const workflow of ["ingest-daily.yml", "ingest-sec.yml", "ingest-markets.yml", "ingest-history.yml"]) {
    const source = read(`.github/workflows/${workflow}`);
    assert.match(source, /schedule:/);
    assert.match(source, /scripts\/reconcile_read_models\.py/);
    assert.match(source, /secrets\.DATABASE_URL/);
  }
  const maintenance = read(".github/workflows/self-test-maintenance.yml");
  assert.match(maintenance, /schedule:/);
  assert.match(maintenance, /environment: production/);
  assert.match(maintenance, /timeout-minutes: 20/);
  assert.match(maintenance, /concurrency:[\s\S]*cancel-in-progress: false/);
  assert.match(maintenance, /workflow_dispatch:/);
  assert.doesNotMatch(maintenance, /recover_analytics_jobs\.py/);
  assert.match(maintenance, /scripts\/reconcile_read_models\.py/);
});

test("owner identity template declares disabled worker and keeps beta evidence false", () => {
  const manifest = JSON.parse(read("docs/templates/owner-self-test-identity-manifest.json"));
  assert.equal(manifest.deployment.profile, "owner_self_test");
  assert.deepEqual(manifest.deployment.services.worker, {
    name: "eagleeyes-analytics-worker",
    id: null,
    mode: "disabled",
  });
  assert.deepEqual(manifest.deployment.services.recovery, {
    name: "eagleeyes-job-recovery",
    id: null,
    mode: "disabled",
  });
  assert.equal(manifest.self_test_deployable, false);
  assert.equal(manifest.deployable, false);
  assert.equal(manifest.evidence.restore_verified, false);
  assert.equal(manifest.evidence.alert_delivery_verified, false);
});
