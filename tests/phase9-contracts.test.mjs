import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const dashboard = readFileSync("app/Dashboard.tsx", "utf8");
const ask = readFileSync("app/components/ask/AskPage.tsx", "utf8");
const shared = readFileSync("app/components/shared/workspace-implementations.tsx", "utf8");
const research = readFileSync("app/components/research/ResearchDiscovery.tsx", "utf8");
const backend = readFileSync("backend/main.py", "utf8");

test("primary Ask is a split conversational workspace using the calculated board directly", () => {
  assert.match(ask, /ResearchChat/);
  assert.match(ask, /ask-split-shell/);
  assert.match(ask, /role="separator"/);
  assert.match(ask, /Chat<\/button>/);
  assert.match(ask, /Dashboard<\/button>/);
  assert.match(ask, /<AIWorkspace \{\.\.\.dashboardProps\} variant="canvas"/);
  assert.doesNotMatch(ask, /Expert tool/);
  assert.match(shared, /Your analysis will appear here/);
  assert.match(dashboard, /messages=\{researchChatMessages\}/);
});

test("page context is visible, controllable, and sent to the typed chat contract", () => {
  assert.match(ask, /Latest evidence/);
  assert.match(ask, /Saved thesis/);
  assert.match(ask, /Portfolio context/);
  assert.match(dashboard, /page_context:/);
  assert.match(backend, /class ChatPageContext/);
});

test("internal execution stays hidden while grounded navigation remains visible", () => {
  assert.doesNotMatch(shared, /className="ask-execution-plan"/);
  assert.doesNotMatch(shared, /className="ask-grounded-tool"/);
  assert.match(shared, /Continue in EagleEyes/);
  assert.match(backend, /execution_state/);
  assert.match(backend, /analysis_context/);
});

test("company research leads with one evidence report and only the approved actions", () => {
  for (const section of ["Price", "Fundamentals", "Valuation", "Momentum", "Risk", "Portfolio fit"]) assert.ok(research.includes(section), section);
  assert.match(research, /Add to watchlist/);
  assert.match(research, /Ask EagleEyes/);
  assert.doesNotMatch(research, /Record WATCH decision/);
  assert.doesNotMatch(research, /Test portfolio scenario/);
});
