import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const routes = readFileSync(new URL("app/lib/routes.ts", root), "utf8");
const workspace = readFileSync(new URL("app/components/shared/workspace-implementations.tsx", root), "utf8");
const etfs = readFileSync(new URL("app/components/research/ETFResearch.tsx", root), "utf8");

test("Research exposes a dedicated ETF catalog route and tab", () => {
  assert.match(routes, /"etfs"/);
  assert.match(workspace, /\["etfs","ETFs"\]/);
  assert.match(workspace, /<ETFResearch request=\{request\}/);
});

test("ETF detail discloses holdings availability and required analytics", () => {
  assert.match(etfs, /Refresh ETF catalog/);
  for (const label of ["Complete dated snapshot", "Sector exposure", "Portfolio overlap", "Expense ratio", "Benchmark", "Concentration", "How this was calculated"]) {
    assert.match(etfs, new RegExp(label));
  }
  for (const state of ["daily", "delayed", "stale", "unavailable"]) assert.match(etfs, new RegExp(state));
});
