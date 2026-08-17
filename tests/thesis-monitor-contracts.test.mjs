import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const decisions = readFileSync(new URL("../app/components/decisions/DecisionsPage.tsx", import.meta.url), "utf8");
const monitor = readFileSync(new URL("../backend/thesis_monitor.py", import.meta.url), "utf8");
const main = readFileSync(new URL("../backend/main.py", import.meta.url), "utf8");

test("Decisions exposes the evidence-first thesis review hierarchy", () => {
  assert.match(decisions, /Thesis Monitor/);
  assert.match(decisions, /Breakers and warnings/);
  assert.match(decisions, /Assumptions affected/);
  assert.match(decisions, /Coverage and unavailable evidence/);
  assert.match(decisions, /Thesis review history/);
  assert.match(decisions, /Mark reviewed/);
  assert.match(decisions, /You choose whether to keep or update the thesis/);
});

test("monitor policy is deterministic, traceable, and separate from portfolio fit", () => {
  for (const state of ["SUPPORTS", "WEAKENS", "CONTRADICTS", "UNCHANGED", "UNRELATED", "INSUFFICIENT_EVIDENCE"])
    assert.match(monitor, new RegExp(state));
  assert.match(monitor, /def evaluate_condition/);
  assert.match(monitor, /def overall_status/);
  assert.match(monitor, /independence_group/);
  assert.doesNotMatch(monitor, /portfolio_fit.*overall_status/s);
});

test("thesis monitor APIs remain authenticated and AI-callable", () => {
  assert.match(main, /\/api\/theses\/\{thesis_id\}\/monitor/);
  assert.match(main, /\/api\/theses\/\{thesis_id\}\/reviews/);
  assert.match(main, /Depends\(require_user\)/);
  assert.match(main, /tool_name": "thesis_monitor"/);
});
