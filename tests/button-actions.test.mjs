import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const dashboardPath = new URL("../app/Dashboard.tsx", import.meta.url);

test("every rendered button has an action", async () => {
  const source = await readFile(dashboardPath, "utf8");
  const buttons = [...source.matchAll(/<button\b[\s\S]*?<\/button>/g)].map(match => match[0]);
  assert.ok(buttons.length >= 15, "expected the dashboard interaction surface");
  const inert = buttons.filter(button => !/\bonClick\s*=/.test(button));
  assert.deepEqual(inert, []);
});

test("critical portfolio and analysis actions remain wired", async () => {
  const source = await readFile(dashboardPath, "utf8");
  for (const action of [
    "savePortfolio", "importCsv", "refreshMarkets", "refreshResearch",
    "runOptimization", "generateNarrative", "toggleTheme",
  ]) {
    assert.match(source, new RegExp(`function ${action}\\(`));
  }
  assert.match(source, /Duplicate ticker/);
  assert.match(source, /Unsaved changes/);
  assert.match(source, /Weight \(%\)/);
  assert.match(source, /ingest_tickers/);
});
