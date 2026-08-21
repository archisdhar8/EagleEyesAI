import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const decisions = await readFile(new URL("../app/components/decisions/DecisionsPage.tsx", import.meta.url), "utf8");
const guided = await readFile(new URL("../app/components/decisions/GuidedThesisEditor.tsx", import.meta.url), "utf8");
const contracts = await readFile(new URL("../app/components/decisions/contracts.ts", import.meta.url), "utf8");
const research = await readFile(new URL("../app/components/research/ResearchDiscovery.tsx", import.meta.url), "utf8");
const portfolio = await readFile(new URL("../app/components/shared/workspace-implementations.tsx", import.meta.url), "utf8");

test("decision contracts include the complete action and thesis status vocabulary", () => {
  for (const action of ["WATCH", "BUY", "ADD", "HOLD", "REDUCE", "SELL", "AVOID"])
    assert.match(contracts, new RegExp(`\\b${action}\\b`));
  for (const status of ["DRAFT", "ACTIVE", "UNDER_REVIEW", "CLOSED", "ARCHIVED"])
    assert.match(contracts, new RegExp(`\\b${status}\\b`));
});

test("decisions workspace makes assisted drafts editable and explicitly unsaved", () => {
  assert.match(guided, /Build an evidence-assisted thesis/);
  assert.match(guided, /No investment decision is recorded automatically/);
  assert.match(guided, /Confirm and save new version/);
  assert.match(guided, /Suggested by EagleEyes/);
  assert.match(guided, /Your belief/);
  assert.match(guided, /I reviewed this thesis/);
  assert.match(guided, /setReviewConfirmed\(false\)/);
  assert.match(decisions, /Append-only journal/);
  assert.match(decisions, /Price unavailable/);
});

test("decision reports auto-build complete scenarios and use compact editable rows", () => {
  assert.match(decisions, /autoDraftedTickers/);
  assert.match(decisions, /Three distinct paths/);
  assert.match(decisions, /Each case is a short memo explaining a different outcome/);
  assert.match(decisions, /Better than current path/);
  assert.match(decisions, /Worse than current path/);
  assert.match(decisions, /Current path persists/);
  assert.match(decisions, /scenarioParagraphs/);
  assert.match(decisions, /scenario-paragraphs/);
  assert.match(guided, /guided-factor-list/);
  assert.match(guided, /guided-edit-row/);
});

test("research retires decision editing while preserved history remains portfolio context", () => {
  assert.match(research, /Generated research case; not saved as your belief/);
  assert.match(research, /saved thesis history/);
  assert.doesNotMatch(research, /\/decisions\?ticker=/);
  assert.match(portfolio, /Decision memory/);
  assert.match(portfolio, /No thesis/);
  assert.match(portfolio, /Optional context/);
});

test("legacy scenario comparison remains secondary and available", () => {
  assert.match(decisions, /Scenario comparison lab/);
  assert.match(decisions, /<DecisionLab/);
});
